"""
Livermore AI — Scanner Principal
Fuente unica: Unusual Whales API
Corre cada 5 min en market hours
"""
import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional
import pytz

from core.icc_engine import ICCDetector, RegimeDetector, ICCPhase, ICCDirection
from core.institutional_rules import TIER_ALERT
from core.scorer import LivermoreScorer, DarkPoolSignal, OptionsFlowSignal, MacroContext
from core.uw_fetcher import UWFetcher, classify_ticker, normalize_occ_contract
from core.models import Alert, WatchlistItem, ContractFlowSnapshot, SessionLocal

logger = logging.getLogger("livermore.scanner")
NY_TZ  = pytz.timezone("America/New_York")
_OCC_RE = re.compile(r"^([A-Z]+)\d{6}[CP]\d{8}$")
INDEX_ETFS = {"SPY", "QQQ", "IWM", "DIA"}
MEGA_CAPS = {"AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "TSLA", "AVGO"}


def _flow_belongs_to_ticker(flow_obj: dict, ticker: str) -> bool:
    chain = normalize_occ_contract(flow_obj)
    if chain:
        match = _OCC_RE.match(chain)
        return bool(match) and match.group(1) == ticker.upper()

    flow_ticker = str(flow_obj.get("ticker") or flow_obj.get("underlying_symbol") or "").upper()
    if not flow_ticker:
        return False
    return flow_ticker == ticker.upper()


def _contract_belongs_to_ticker(contract: str, ticker: str) -> bool:
    match = _OCC_RE.match((contract or "").strip().upper())
    return bool(match) and match.group(1) == ticker.upper()


def _flow_contract(flow_obj: dict) -> str:
    return normalize_occ_contract(flow_obj)


def _assert_contract_belongs(ticker: str, contract: str) -> bool:
    if not contract:
        return True
    if not _contract_belongs_to_ticker(contract, ticker):
        logger.error(
            f"CONTRACT MISMATCH AT PUBLISH: "
            f"ticker={ticker} contract={contract} — SKIPPING"
        )
        return False
    return True


def _fallback_atm_contract(ticker: str, entry: float, direction: ICCDirection) -> str:
    today = datetime.now(NY_TZ).date()
    days_until_fri = (4 - today.weekday()) % 7 or 7
    expiry = today + timedelta(days=days_until_fri)
    expiry_str = expiry.strftime("%y%m%d")

    ticker = ticker.upper()
    if ticker in INDEX_ETFS:
        strike_int = round(entry)
    elif ticker in MEGA_CAPS:
        strike_int = round(entry / 5) * 5
    else:
        strike_int = round(entry)

    opt_type = "C" if direction == ICCDirection.BULLISH else "P"
    strike_str = f"{int(strike_int * 1000):08d}"
    return f"{ticker}{expiry_str}{opt_type}{strike_str}"


def _price_levels(entry: float, direction: ICCDirection, ticker: str) -> tuple[float, float, float]:
    ticker = ticker.upper()
    if ticker in INDEX_ETFS:
        sl_pct, tp1_pct, tp2_pct = 0.005, 0.010, 0.018
    elif ticker in MEGA_CAPS:
        sl_pct, tp1_pct, tp2_pct = 0.012, 0.025, 0.040
    else:
        sl_pct, tp1_pct, tp2_pct = 0.020, 0.040, 0.065

    if direction == ICCDirection.BULLISH:
        return entry * (1 - sl_pct), entry * (1 + tp1_pct), entry * (1 + tp2_pct)
    return entry * (1 + sl_pct), entry * (1 - tp1_pct), entry * (1 - tp2_pct)


class LivermoreScanner:

    def __init__(self, discord_bot=None):
        self.icc        = ICCDetector()
        self.regime_det = RegimeDetector()
        self.scorer     = LivermoreScorer()
        self.uw         = UWFetcher()
        self.discord    = discord_bot
        self.alerts_today = set()
        self.ticker_delay = float(os.getenv("SCAN_TICKER_DELAY_SECONDS", "4.0"))
        self.max_scan_tickers = int(os.getenv("MAX_SCAN_TICKERS", "20"))

    def _compute_flow_acceleration(self, contract: str, ticker: str,
                                   accumulated: float, flow_count: int) -> dict:
        """
        Memoria de flujo entre scans. Compara el acumulado actual del contrato
        contra el último snapshot guardado y calcula la derivada.

        Devuelve: delta_nominal, accel_ratio, is_accelerating.
        Persiste el snapshot de este scan para la próxima comparación.
        """
        result = {"delta_nominal": 0.0, "accel_ratio": 0.0, "is_accelerating": False}
        if not contract or contract in ("", "--"):
            return result

        # Umbral mínimo de crecimiento para considerar "acelerando" (anti-ruido)
        MIN_DELTA = 25_000  # $25K de crecimiento nuevo

        db = SessionLocal()
        try:
            prev = (
                db.query(ContractFlowSnapshot)
                .filter(ContractFlowSnapshot.contract == contract)
                .order_by(ContractFlowSnapshot.snapshot_at.desc())
                .first()
            )
            prev_accum = float(prev.accumulated_nominal) if prev else 0.0

            delta = accumulated - prev_accum
            accel_ratio = (delta / prev_accum) if prev_accum > 0 else 0.0
            # Acelera si creció de forma material vs el scan anterior.
            # Primer avistamiento (prev=0) NO cuenta como aceleración: es nivel, no derivada.
            is_accel = bool(prev and delta >= MIN_DELTA)

            result = {
                "delta_nominal": round(delta, 2),
                "accel_ratio": round(accel_ratio, 4),
                "is_accelerating": is_accel,
            }

            snap = ContractFlowSnapshot(
                contract=contract,
                ticker=ticker,
                accumulated_nominal=accumulated,
                flow_count=flow_count,
                prev_accumulated=prev_accum,
                delta_nominal=round(delta, 2),
                accel_ratio=round(accel_ratio, 4),
                is_accelerating=is_accel,
            )
            db.add(snap)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"flow_acceleration error para {contract}: {e}")
        finally:
            db.close()

        return result

    async def hydrate_watchlist_prices(self):
        """
        Recorre el watchlist activo y guarda current_price/prev_close/day_change_pct
        en la tabla. El endpoint /api/watchlist lee de aquí (no llama UW por request).
        Pensado para correr en el loop del scanner (background).
        """
        db = SessionLocal()
        updated = 0
        try:
            items = db.query(WatchlistItem).filter(WatchlistItem.active == True).all()
            for item in items:
                ticker = item.ticker.upper()
                try:
                    quote = await self.uw.get_stock_price(ticker)
                except Exception as e:
                    logger.warning(f"hydrate precio {ticker}: {e}")
                    quote = None
                if not quote:
                    continue
                item.current_price    = quote["price"]
                item.prev_close       = quote.get("prev_close")
                item.day_change_pct   = quote.get("change_pct", 0)
                item.price_updated_at = datetime.utcnow()
                updated += 1
                await asyncio.sleep(0.3)  # cortesía con rate limit de UW
            db.commit()
            logger.info(f"watchlist precios hidratados: {updated}/{len(items)}")
        except Exception as e:
            db.rollback()
            logger.error(f"hydrate_watchlist_prices error: {e}")
        finally:
            db.close()
        return updated

    def is_market_hours(self) -> bool:
        now = datetime.now(NY_TZ)
        return now.weekday() < 5 and 8 <= now.hour < 20

    def get_session(self) -> str:
        now = datetime.now(NY_TZ)
        h = now.hour
        if h < 9 or (h == 9 and now.minute < 30):
            return "PRE"
        elif h >= 16:
            return "POST"
        return "REGULAR"

    async def run_scan(self):
        # Hidratar precios del watchlist SIEMPRE (incluso fuera de market hours:
        # el watchlist debe mostrar el último close aunque el mercado esté cerrado).
        try:
            await self.hydrate_watchlist_prices()
        except Exception as e:
            logger.warning(f"hydrate_watchlist_prices en run_scan: {e}")

        closed = not self.is_market_hours()
        session = self.get_session()
        if closed:
            logger.info(
                f"Scan fuera de RTH — analizando flujo acumulado de la sesión ({session})"
            )
        else:
            logger.info(f"Scan iniciado — {session}")

        # Market tide: contexto global antes de escanear tickers
        market_tide = await self.uw.get_market_tide()
        market_direction = market_tide.get("market_direction", "NEUTRAL") if market_tide else "NEUTRAL"
        logger.info(f"Market Tide: {market_direction}")
        macro_calendar = await self.uw.get_macro_calendar()
        if macro_calendar.get("events"):
            logger.info(f"Eventos macro proximos: {', '.join(macro_calendar.get('events', [])[:3])}")

        # Tickers activos segun UW screener (no watchlist hardcoded)
        tickers = await self._get_tickers()
        rollovers = await self.uw.detect_rollover()
        rollover_targets = {r["to_ticker"] for r in rollovers if r.get("to_ticker")}
        if rollovers:
            logger.info(f"Rollovers detectados: {len(rollovers)}")
            # Si el ticker destino del rollover está en watchlist, boost su score
            for r in rollovers:
                if r["to_ticker"] in tickers:
                    logger.info(f"ROLLOVER → {r['to_ticker']} desde {r['from_ticker']}")
        results = []

        for ticker in tickers:
            try:
                result = await self._analyze_ticker(
                    ticker,
                    session,
                    market_tide,
                    macro_calendar,
                    rollover_detected=ticker in rollover_targets,
                )
                if result:
                    results.append(result)
                await asyncio.sleep(self.ticker_delay)
            except Exception as e:
                logger.error(f"Error {ticker}: {e}")

        results.sort(key=lambda x: x["score"], reverse=True)

        for result in results:
            if result["score"] >= TIER_ALERT:
                await self._fire_alert(result)

        logger.info(f"Scan completo — {len(results)} analizados, "
                    f"{sum(1 for r in results if r['score'] >= TIER_ALERT)} alertas")

    async def _analyze_ticker(self, ticker: str, session: str,
                               market_tide: Optional[dict],
                               macro_calendar: Optional[dict],
                               rollover_detected: bool = False) -> Optional[dict]:

        # ─── 1. Datos del ticker via UW ──────────────────────
        ticker_data = await self.uw.get_ticker_data(ticker)
        if not ticker_data:
            return None

        current_price = ticker_data.get("prev_close", 0)
        iv_rank       = ticker_data.get("iv_rank", 50)
        category      = classify_ticker(ticker)
        if not current_price:
            return None

        # ─── 2. Flow de opciones del ticker ──────────────────
        flow_alerts = await self.uw.get_ticker_flow(ticker)
        oi_data = await self.uw.get_oi_change(ticker)

        # ─── 3. Dark pool ─────────────────────────────────────
        dp_raw = await self.uw.analyze_dark_pool(ticker, current_price)

        # ─── 4. Net premium ───────────────────────────────────
        net_prem = await self.uw.get_net_premium(ticker)

        # ─── 5. GEX ───────────────────────────────────────────
        gex = await self.uw.get_gex(ticker)
        chain_map = await self.uw.get_option_chain_map(ticker)

        # ─── 6. Earnings DTE ──────────────────────────────────
        earnings_dte = await self.uw.get_earnings_dte(ticker)

        # ─── 7. Determinar direccion via net premium ──────────
        direction = ICCDirection.BULLISH
        if net_prem:
            if net_prem.get("bearish_pressure"):
                direction = ICCDirection.BEARISH

        # Confirmar con market tide
        if market_tide:
            tide_dir = market_tide.get("market_direction", "NEUTRAL")
            if tide_dir == "BEARISH" and direction == ICCDirection.BULLISH:
                # Contra la marea — reducir conviccion
                pass

        # ─── 8. ICC simulado con net premium como proxy ───────
        # Sin candles 1H de UW Basic, usamos net premium como señal de
        # continuation: call premium sube = continuation bullish
        icc_score = 0
        icc_phase = ICCPhase.NONE

        if net_prem:
            call_prem = float(net_prem.get("net_call_premium", 0))
            put_prem  = float(net_prem.get("net_put_premium", 0))
            call_trend = float(net_prem.get("call_trend", 0))

            if direction == ICCDirection.BULLISH:
                if call_prem > 0:
                    icc_score += 15
                if call_trend > 0:
                    icc_score += 10
                    icc_phase = ICCPhase.CONTINUATION
                if call_prem > 200_000:
                    icc_score += 10
            else:
                if put_prem < 0:
                    icc_score += 15
                if float(net_prem.get("put_trend", 0)) < 0:
                    icc_score += 10
                    icc_phase = ICCPhase.CONTINUATION

        if icc_phase != ICCPhase.CONTINUATION:
            return None  # Solo alertar en continuation

        # ─── 9. Construir señal de dark pool ──────────────────
        dp_signal = None
        if dp_raw and dp_raw.get("print_size", 0) > 100_000:
            dp_signal = DarkPoolSignal(
                print_price=dp_raw["print_price"],
                print_size=dp_raw["print_size"],
                above_vwap=dp_raw["above_vwap"],
                cluster=dp_raw["cluster"],
                absorption=dp_raw["absorption"],
                session=dp_raw["session"],
                velocity=dp_raw["velocity"],
            )

        # ─── 10. Construir señal de opciones flow ─────────────
        # Acumulación POR CONTRATO (no por ticker). _group_repeated_flow ya
        # agrupó por contrato y dejó accumulated_nominal + flow_count.
        # Elegible = nivel acumulado >= umbral Y al menos 2 hits en el contrato.
        opt_signal = None
        best = None
        MIN_ACCUM = 250_000   # nivel acumulado mínimo por contrato (STOCK)
        MIN_HITS  = 2         # nº de hits mínimo en el mismo contrato

        eligible_flow_alerts = [
            flow for flow in flow_alerts
            if float(flow.get("accumulated_nominal", flow.get("nominal_value", 0)) or 0) >= MIN_ACCUM
            and int(flow.get("flow_count", 0) or 0) >= MIN_HITS
            and _flow_belongs_to_ticker(flow, ticker)
        ]
        if eligible_flow_alerts:
            best = max(
                eligible_flow_alerts,
                key=lambda f: float(f.get("accumulated_nominal", f.get("nominal_value", 0)) or 0),
            )
            nominal_value = float(best.get("nominal_value", 0) or 0)
            accumulated   = float(best.get("accumulated_nominal", nominal_value) or nominal_value)
            vol_oi     = float(best.get("volume_oi_ratio", 0))
            has_sweep  = best.get("has_sweep", False)
            has_floor  = best.get("has_floor", False)
            ask_prem   = float(best.get("total_ask_side_prem", 0))
            executed_ask = ask_prem / nominal_value if nominal_value > 0 else 0

            is_golden = (has_sweep or has_floor) and accumulated >= 10_000_000

            # ─── DERIVADA: comparar contra el scan anterior ───
            accel = self._compute_flow_acceleration(
                contract=_flow_contract(best),
                ticker=ticker,
                accumulated=accumulated,
                flow_count=int(best.get("flow_count", 0) or 0),
            )

            opt_signal = OptionsFlowSignal(
                volume=int(best.get("volume", 0)),
                open_interest=int(best.get("open_interest", 1)),
                vol_oi_ratio=vol_oi,
                executed_ask=executed_ask,
                nominal_value=nominal_value,
                is_sweep=has_sweep,
                has_floor=has_floor,
                is_golden_sweep=is_golden,
                delta=float(best.get("delta", 0.50) or 0.50),
                iv_rank=iv_rank,
                expiration_dte=30,
                contract=_flow_contract(best),
                repeated_flow=bool(best.get("repeated_flow")),
                flow_count=int(best.get("flow_count", 0) or 0),
                accumulated_nominal=accumulated,
                is_single_leg=bool(best.get("is_single_leg", True)),
                delta_nominal=accel["delta_nominal"],
                accel_ratio=accel["accel_ratio"],
                is_accelerating=accel["is_accelerating"],
            )

        # ─── 11. Macro context ────────────────────────────────
        macro = MacroContext(
            has_earnings=earnings_dte <= 5,
            earnings_dte=earnings_dte,
            market_session=session,
            vix_level=15.0,
        )

        # ─── 12. Niveles de precio ────────────────────────────
        entry = current_price
        sl, tp1, tp2 = _price_levels(entry, direction, ticker)

        # ─── 13. ADX estimado via GEX ─────────────────────────
        adx = 25.0  # default trending
        regime = "TRENDING_UP" if direction == ICCDirection.BULLISH else "TRENDING_DOWN"
        if gex and not gex.get("gex_positive"):
            adx = 28.0  # GEX negativo = moves mas fuertes

        # ─── 14. Score final ──────────────────────────────────
        score_result = self.scorer.score(
            ticker=ticker,
            icc_score=icc_score,
            icc_direction=direction.value,
            entry_price=entry,
            stop_loss=sl,
            target1=tp1,
            target2=tp2,
            dark_pool=dp_signal,
            options_flow=opt_signal,
            macro=macro,
            adx=adx,
            regime=regime,
            oi_data=oi_data,
            category=category,
            chain_map=chain_map,
            rollover_detected=rollover_detected,
            macro_calendar=macro_calendar,
        )

        # ─── 15. Contrato recomendado del flow alert ──────────
        contract_label = ""
        nominal_value = None
        if eligible_flow_alerts:
            best = max(eligible_flow_alerts, key=lambda f: float(f.get("nominal_value", 0) or 0))
            contract_label = _flow_contract(best)
            nominal_value = float(best.get("nominal_value", 0) or 0)
        if not contract_label:
            contract_label = _fallback_atm_contract(ticker, entry, direction)

        if contract_label and not _contract_belongs_to_ticker(contract_label, ticker):
            logger.error(
                f"INVARIANTE VIOLADA: contrato {contract_label} "
                f"no pertenece al ticker {ticker}. Alerta abortada."
            )
            return None

        return {
            "ticker":     ticker,
            "score":      score_result.total,
            "tier":       score_result.tier,
            "category":   category,
            "direction":  direction.value,
            "icc_phase":  icc_phase.value,
            "icc_signal": "net_premium_continuation",
            "regime":     regime,
            "session":    session,
            "entry":      round(entry, 2),
            "stop_loss":  round(sl, 2),
            "target1":    round(tp1, 2),
            "target2":    round(tp2, 2),
            "contract":   contract_label,
            "strike":     None,
            "expiration": None,
            "delta":      float(best.get("delta", 0.50) or 0.50) if best else None,
            "premium":    nominal_value,
            "nominal_value": nominal_value,
            "oi_data": oi_data,
            "chain_map": chain_map,
            "repeated_flow": bool(best.get("repeated_flow")) if best else False,
            "flow_count": int(best.get("flow_count", 0) or 0) if best else 0,
            "accumulated_nominal": float(best.get("accumulated_nominal", 0) or 0) if best else 0,
            "is_single_leg": bool(best.get("is_single_leg", True)) if best else True,
            "reason":     score_result.reason,
            "score_breakdown": {
                "icc":      score_result.icc,
                "dark_pool": score_result.dark_pool,
                "options":  score_result.options_flow,
                "macro":    score_result.macro_bonus,
                "pre_post": score_result.pre_post_bonus,
            },
            "channels": score_result.alert_channels,
            "market_tide": market_tide.get("market_direction") if market_tide else "NEUTRAL",
            "macro_calendar": macro_calendar or {},
        }

    async def _get_tickers(self) -> list[str]:
        try:
            # Primero tickers del watchlist de DB
            db = SessionLocal()
            items = db.query(WatchlistItem).filter(WatchlistItem.active == True).all()
            db.close()
            custom = [item.ticker for item in items]
        except:
            custom = []

        # UW screener como fuente principal
        uw_tickers = await self.uw.get_active_tickers()

        # Merge: custom primero, luego UW screener
        all_tickers = list(dict.fromkeys(custom + uw_tickers))
        return all_tickers[:self.max_scan_tickers]

    async def _fire_alert(self, result: dict):
        if not _assert_contract_belongs(result["ticker"], result.get("contract", "")):
            return

        alert_key = (
            f"{result['ticker']}-{result.get('contract', '')}-{result['tier']}-"
            f"{datetime.now(NY_TZ).strftime('%Y%m%d%H')}"
        )
        if alert_key in self.alerts_today:
            return
        self.alerts_today.add(alert_key)

        try:
            db = SessionLocal()
            alert = Alert(
                ticker=result["ticker"],
                asset_type="OPTION" if result.get("contract") else "STOCK",
                mode="SWING",
                category=result.get("category", "STOCK"),
                score_total=result["score"],
                score_icc=result["score_breakdown"]["icc"],
                score_darkpool=result["score_breakdown"]["dark_pool"],
                score_flow=result["score_breakdown"]["options"],
                score_regime=result["score_breakdown"]["macro"],
                entry_price=result["entry"],
                stop_loss=result["stop_loss"],
                target1=result["target1"],
                target2=result["target2"],
                contract=result.get("contract", ""),
                delta=result.get("delta"),
                premium=result.get("nominal_value"),
                oi_growing=bool(result.get("oi_data", {}).get("oi_growing")),
                oi_change_pct=result.get("oi_data", {}).get("oi_change_pct", 0),
                oi_days_growing=result.get("oi_data", {}).get("days_growing", 0),
                oi_today=result.get("oi_data", {}).get("today_oi"),
                oi_yesterday=result.get("oi_data", {}).get("yesterday_oi"),
                has_ladder=bool(result.get("chain_map", {}).get("has_ladder")),
                ladder_strikes=result.get("chain_map", {}).get("ladder_strikes", []),
                put_gaps=result.get("chain_map", {}).get("put_gaps", []),
                target_strike=result.get("chain_map", {}).get("target_strike"),
                repeated_flow=bool(result.get("repeated_flow")),
                flow_count=result.get("flow_count", 0),
                accumulated_nominal=result.get("accumulated_nominal", 0),
                is_single_leg=bool(result.get("is_single_leg", True)),
                signal_summary=result["reason"],
                icc_phase=result["icc_phase"],
                icc_signal=result["icc_signal"],
                regime=result["regime"],
                market_session=result["session"],
                status="pending",
                sent_to_tiers=result["channels"],
            )
            db.add(alert)
            db.commit()
            alert_id = alert.id
            db.close()
            logger.info(f"Alert — {result['ticker']} {result['score']}/100 {result['tier']}")
        except Exception as e:
            logger.error(f"DB error: {e}")
            alert_id = 0

        if self.discord:
            await self.discord.send_alert(result, alert_id)
