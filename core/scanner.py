"""
Livermore AI — Scanner Principal
Fuente unica: Unusual Whales API
Corre cada 5 min en market hours
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional
import pytz

from core.icc_engine import ICCDetector, RegimeDetector, ICCPhase, ICCDirection
from core.scorer import LivermoreScorer, DarkPoolSignal, OptionsFlowSignal, MacroContext
from core.uw_fetcher import UWFetcher, classify_ticker
from core.models import Alert, WatchlistItem, SessionLocal

logger = logging.getLogger("livermore.scanner")
NY_TZ  = pytz.timezone("America/New_York")


class LivermoreScanner:

    def __init__(self, discord_bot=None):
        self.icc        = ICCDetector()
        self.regime_det = RegimeDetector()
        self.scorer     = LivermoreScorer()
        self.uw         = UWFetcher()
        self.discord    = discord_bot
        self.alerts_today = set()

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
        if not self.is_market_hours():
            logger.info("Outside market hours — skipping")
            return

        session = self.get_session()
        logger.info(f"Scan iniciado — {session}")

        # Market tide: contexto global antes de escanear tickers
        market_tide = await self.uw.get_market_tide()
        market_direction = market_tide.get("market_direction", "NEUTRAL") if market_tide else "NEUTRAL"
        logger.info(f"Market Tide: {market_direction}")

        # Tickers activos segun UW screener (no watchlist hardcoded)
        tickers = await self._get_tickers()
        results = []

        for ticker in tickers:
            try:
                result = await self._analyze_ticker(ticker, session, market_tide)
                if result:
                    results.append(result)
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"Error {ticker}: {e}")

        results.sort(key=lambda x: x["score"], reverse=True)

        for result in results:
            if result["score"] >= 75:
                await self._fire_alert(result)

        logger.info(f"Scan completo — {len(results)} analizados, "
                    f"{sum(1 for r in results if r['score'] >= 75)} alertas")

    async def _analyze_ticker(self, ticker: str, session: str,
                               market_tide: Optional[dict]) -> Optional[dict]:

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
        opt_signal = None
        eligible_flow_alerts = [
            flow for flow in flow_alerts
            if float(flow.get("nominal_value", 0) or 0) >= LivermoreScorer.min_nominal_for_category(category)
        ]
        if eligible_flow_alerts:
            best = max(eligible_flow_alerts, key=lambda f: float(f.get("nominal_value", 0) or 0))
            nominal_value = float(best.get("nominal_value", 0) or 0)
            vol_oi     = float(best.get("volume_oi_ratio", 0))
            has_sweep  = best.get("has_sweep", False)
            has_floor  = best.get("has_floor", False)
            ask_prem   = float(best.get("total_ask_side_prem", 0))
            executed_ask = ask_prem / nominal_value if nominal_value > 0 else 0

            is_golden = (has_sweep or has_floor) and nominal_value >= 10_000_000

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
                contract=best.get("option_chain", ""),
                repeated_flow=bool(best.get("repeated_flow")),
                flow_count=int(best.get("flow_count", 0) or 0),
                accumulated_nominal=float(best.get("accumulated_nominal", nominal_value) or nominal_value),
                is_single_leg=bool(best.get("is_single_leg", True)),
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
        sl    = entry * 0.97 if direction == ICCDirection.BULLISH else entry * 1.03
        tp1   = entry * 1.06 if direction == ICCDirection.BULLISH else entry * 0.94
        tp2   = entry * 1.10 if direction == ICCDirection.BULLISH else entry * 0.90

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
        )

        # ─── 15. Contrato recomendado del flow alert ──────────
        contract_label = ""
        nominal_value = None
        if eligible_flow_alerts:
            best = max(eligible_flow_alerts, key=lambda f: float(f.get("nominal_value", 0) or 0))
            contract_label = best.get("option_chain", "")
            nominal_value = float(best.get("nominal_value", 0) or 0)

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
            "delta":      float(best.get("delta", 0.50) or 0.50) if eligible_flow_alerts else None,
            "premium":    nominal_value,
            "nominal_value": nominal_value,
            "oi_data": oi_data,
            "chain_map": chain_map,
            "repeated_flow": bool(best.get("repeated_flow")) if eligible_flow_alerts else False,
            "flow_count": int(best.get("flow_count", 0) or 0) if eligible_flow_alerts else 0,
            "accumulated_nominal": float(best.get("accumulated_nominal", 0) or 0) if eligible_flow_alerts else 0,
            "is_single_leg": bool(best.get("is_single_leg", True)) if eligible_flow_alerts else True,
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
        return all_tickers[:20]

    async def _fire_alert(self, result: dict):
        alert_key = f"{result['ticker']}-{result['tier']}-{datetime.now(NY_TZ).strftime('%Y%m%d%H')}"
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
