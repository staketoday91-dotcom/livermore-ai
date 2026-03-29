"""
Livermore AI — Main Scanner
Runs every 5 minutes during market hours
Beta mode: Polygon + Tradier (UW desactivado)
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional
import pytz

from core.icc_engine import ICCDetector, RegimeDetector, ICCPhase, ICCDirection
from core.scorer import LivermoreScorer, DarkPoolSignal, OptionsFlowSignal, MacroContext
from core.fetcher import PolygonFetcher, TradierFetcher, UnusualWhalesFetcher
from core.models import Alert, WatchlistItem, SessionLocal

logger = logging.getLogger("livermore.scanner")
NY_TZ  = pytz.timezone("America/New_York")

DEFAULT_WATCHLIST = [
    "SPY", "QQQ", "NVDA", "AAPL", "TSLA",
    "MSFT", "AMZN", "META", "GOOGL", "AMD",
]


class LivermoreScanner:

    def __init__(self, discord_bot=None):
        self.icc        = ICCDetector()
        self.regime_det = RegimeDetector()
        self.scorer     = LivermoreScorer()
        self.polygon    = PolygonFetcher()
        self.tradier    = TradierFetcher()
        self.uw         = UnusualWhalesFetcher()   # desactivado, retorna listas vacias
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
            logger.info("Outside market hours — skipping scan")
            return

        session = self.get_session()
        logger.info(f"Starting scan — session: {session}")

        tickers = await self._get_watchlist()
        results = []

        for ticker in tickers[:15]:   # cap conservador para plan free de Polygon
            try:
                result = await self._analyze_ticker(ticker, session)
                if result:
                    results.append(result)
                await asyncio.sleep(0.5)  # rate limit Polygon free tier
            except Exception as e:
                logger.error(f"Error analyzing {ticker}: {e}")

        results.sort(key=lambda x: x["score"], reverse=True)
        for result in results:
            if result["score"] >= 75:
                await self._fire_alert(result)

        logger.info(f"Scan complete — {len(results)} analizados, "
                    f"{sum(1 for r in results if r['score'] >= 75)} alertas")

    async def _analyze_ticker(self, ticker: str, session: str) -> Optional[dict]:

        # ─── 1. Precio y candles ─────────────────────────────
        candles = await self.polygon.get_candles_1h(ticker)
        if len(candles) < 10:
            return None

        snapshot = await self.polygon.get_snapshot(ticker)
        current_price = snapshot.get("price", 0)
        vwap          = snapshot.get("vwap", 0)
        avg_vol       = await self.polygon.get_avg_volume(ticker)

        if not current_price:
            return None

        # ─── 2. Regime ───────────────────────────────────────
        adx    = self._estimate_adx(candles)
        regime = self.regime_det.classify(adx, candles)

        # ─── 3. ICC ──────────────────────────────────────────
        icc_result = self.icc.detect(candles, avg_vol)
        if icc_result.phase != ICCPhase.CONTINUATION:
            return None

        # ─── 4. Options flow via Tradier (proxy UW) ──────────
        opt_signal  = None
        dp_signal   = None
        flow_data   = await self.tradier.get_options_flow_proxy(ticker)

        direction = icc_result.direction
        side_flow = flow_data.get("call") if direction == ICCDirection.BULLISH else flow_data.get("put")

        if side_flow:
            greeks    = side_flow.get("greeks") or {}
            vol_oi    = side_flow.get("vol_oi_ratio", 0)
            prem_est  = side_flow.get("premium_estimate", 0)
            volume    = side_flow.get("volume") or 0
            oi        = side_flow.get("open_interest") or 1
            delta     = abs(greeks.get("delta", 0.5))

            is_sweep        = vol_oi >= 3.0
            is_golden_sweep = vol_oi >= 5.0 and prem_est >= 250_000

            opt_signal = OptionsFlowSignal(
                volume=volume,
                open_interest=oi,
                vol_oi_ratio=vol_oi,
                executed_ask=0.80 if is_sweep else 0.60,  # estimado
                premium_total=prem_est,
                is_sweep=is_sweep,
                is_golden_sweep=is_golden_sweep,
                delta=delta,
                iv_rank=50.0,   # TODO: calcular de IV historica
                expiration_dte=30,
                contract=side_flow.get("symbol", ""),
            )

            # Dark pool proxy: si hay actividad fuerte de opciones = acumulacion
            if prem_est >= 100_000:
                dp_signal = DarkPoolSignal(
                    print_price=current_price,
                    print_size=prem_est * 5,  # estimado equity equivalente
                    above_vwap=current_price > vwap if vwap > 0 else False,
                    cluster=vol_oi >= 3,
                    absorption=False,
                    session=session,
                    velocity="BURST" if vol_oi >= 5 else "STEADY",
                )

        # ─── 5. Contrato recomendado ─────────────────────────
        contract = None
        if direction == ICCDirection.BULLISH:
            contract = await self.tradier.find_best_contract(ticker, "CALL")
        elif direction == ICCDirection.BEARISH:
            contract = await self.tradier.find_best_contract(ticker, "PUT")

        # ─── 6. Macro ────────────────────────────────────────
        macro = MacroContext(market_session=session, vix_level=15.0)

        # ─── 7. Niveles ──────────────────────────────────────
        entry = icc_result.entry_zone or current_price
        sl = icc_result.invalidation or (
            entry * 0.98 if direction == ICCDirection.BULLISH else entry * 1.02
        )
        if direction == ICCDirection.BULLISH:
            tp1 = entry + (entry - sl) * 2
            tp2 = entry + (entry - sl) * 3.5
        else:
            tp1 = entry - (sl - entry) * 2
            tp2 = entry - (sl - entry) * 3.5

        # ─── 8. Score ────────────────────────────────────────
        score_result = self.scorer.score(
            ticker=ticker,
            icc_score=icc_result.score,
            icc_direction=direction.value if direction else "NEUTRAL",
            entry_price=entry,
            stop_loss=sl,
            target1=tp1,
            target2=tp2,
            dark_pool=dp_signal,
            options_flow=opt_signal,
            macro=macro,
            adx=adx,
            regime=regime,
        )

        return {
            "ticker":     ticker,
            "score":      score_result.total,
            "tier":       score_result.tier,
            "direction":  direction.value if direction else "N/A",
            "icc_phase":  icc_result.phase.value,
            "icc_signal": icc_result.signal_type,
            "regime":     regime,
            "session":    session,
            "entry":      round(entry, 2),
            "stop_loss":  round(sl, 2),
            "target1":    round(tp1, 2),
            "target2":    round(tp2, 2),
            "contract":   contract.get("contract_label", "") if contract else "",
            "strike":     contract.get("strike") if contract else None,
            "expiration": contract.get("expiration") if contract else None,
            "delta":      contract.get("delta") if contract else None,
            "premium":    contract.get("mid") if contract else None,
            "reason":     score_result.reason,
            "score_breakdown": {
                "icc":      score_result.icc,
                "dark_pool": score_result.dark_pool,
                "options":  score_result.options_flow,
                "macro":    score_result.macro_bonus,
                "pre_post": score_result.pre_post_bonus,
            },
            "channels": score_result.alert_channels,
        }

    def _estimate_adx(self, candles) -> float:
        if len(candles) < 14:
            return 15.0
        ranges = [c.range for c in candles[-14:]]
        avg_range = sum(ranges) / len(ranges)
        bodies = [abs(c.close - c.open) for c in candles[-14:]]
        avg_body = sum(bodies) / len(bodies)
        ratio = avg_body / avg_range if avg_range > 0 else 0
        return min(ratio * 50, 50)

    async def _get_watchlist(self) -> list[str]:
        try:
            db = SessionLocal()
            items = db.query(WatchlistItem).filter(WatchlistItem.active == True).all()
            db.close()
            custom = [item.ticker for item in items]
            return list(set(DEFAULT_WATCHLIST + custom))
        except:
            return DEFAULT_WATCHLIST

    async def _fire_alert(self, result: dict):
        alert_key = f"{result['ticker']}-{result['score']}-{datetime.now().strftime('%Y%m%d%H')}"
        if alert_key in self.alerts_today:
            return
        self.alerts_today.add(alert_key)

        try:
            db = SessionLocal()
            alert = Alert(
                ticker=result["ticker"],
                asset_type="OPTION" if result.get("contract") else "STOCK",
                mode="SWING" if result.get("contract") else "DAY_TRADE",
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
                strike=result.get("strike"),
                expiration=result.get("expiration"),
                delta=result.get("delta"),
                premium=result.get("premium"),
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
            logger.info(f"Alert saved — {result['ticker']} score={result['score']} tier={result['tier']}")
        except Exception as e:
            logger.error(f"DB save failed: {e}")
            alert_id = 0

        if self.discord:
            await self.discord.send_alert(result, alert_id)
