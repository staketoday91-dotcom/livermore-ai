"""
Livermore AI — Main Scanner
Runs every 5 minutes during market hours
Analyzes watchlist, calculates scores, fires alerts
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

NY_TZ = pytz.timezone("America/New_York")

# Default watchlist — system scans these always
DEFAULT_WATCHLIST = [
    "SPY", "QQQ", "NVDA", "AAPL", "TSLA", "MSFT", "AMZN",
    "META", "GOOGL", "AMD", "NFLX", "CRM", "COIN", "MSTR",
]


class LivermoreScanner:

    def __init__(self, discord_bot=None):
        self.icc        = ICCDetector()
        self.regime_det = RegimeDetector()
        self.scorer     = LivermoreScorer()
        self.polygon    = PolygonFetcher()
        self.tradier    = TradierFetcher()
        self.uw         = UnusualWhalesFetcher()
        self.discord    = discord_bot
        self.alerts_today = set()  # prevent duplicate alerts

    def is_market_hours(self) -> bool:
        now = datetime.now(NY_TZ)
        # Include pre-market (8am) and post-market (8pm)
        return (now.weekday() < 5 and
                8 <= now.hour < 20)

    def get_session(self) -> str:
        now = datetime.now(NY_TZ)
        h = now.hour
        if h < 9 or (h == 9 and now.minute < 30):
            return "PRE"
        elif h >= 16:
            return "POST"
        return "REGULAR"

    async def run_scan(self):
        """Main scan loop — called every 5 minutes"""
        if not self.is_market_hours():
            logger.info("Outside market hours — skipping scan")
            return

        session = self.get_session()
        logger.info(f"Starting scan — session: {session}")

        # Get watchlist from DB + defaults
        tickers = await self._get_watchlist()

        # Get unusual flow from UW (scan-wide)
        uw_flow = await self._get_uw_flow()
        dp_flow = await self._get_dp_flow()

        # Merge flow tickers into scan list
        flow_tickers = set(f.get("ticker", "") for f in uw_flow)
        all_tickers  = list(set(tickers) | flow_tickers)

        results = []
        for ticker in all_tickers[:30]:  # cap at 30 per scan cycle
            try:
                result = await self._analyze_ticker(
                    ticker, session, uw_flow, dp_flow
                )
                if result:
                    results.append(result)
            except Exception as e:
                logger.error(f"Error analyzing {ticker}: {e}")

        # Sort by score and fire alerts
        results.sort(key=lambda x: x["score"], reverse=True)
        for result in results:
            if result["score"] >= 75:
                await self._fire_alert(result)

        logger.info(f"Scan complete — {len(results)} signals, {sum(1 for r in results if r['score']>=75)} alerts")

    async def _analyze_ticker(self, ticker: str, session: str, uw_flow: list, dp_flow: list) -> Optional[dict]:
        """Full analysis pipeline for one ticker"""

        # ─── 1. Get price data ───────────────────────────────
        candles = await self.polygon.get_candles_1h(ticker)
        if len(candles) < 10:
            return None

        avg_vol = await self.polygon.get_avg_volume(ticker)
        snapshot = await self.polygon.get_snapshot(ticker)
        vwap = snapshot.get("vwap", 0)
        current_price = snapshot.get("price", 0)

        if not current_price:
            return None

        # ─── 2. Regime detection ─────────────────────────────
        # Approximate ADX from price data
        adx = self._estimate_adx(candles)
        regime = self.regime_det.classify(adx, candles)

        # ─── 3. ICC Detection ─────────────────────────────────
        icc_result = self.icc.detect(candles, avg_vol)

        if icc_result.phase != ICCPhase.CONTINUATION:
            return None  # No ICC signal — skip

        # ─── 4. Dark Pool Analysis ────────────────────────────
        dp_signal = self._analyze_dp(ticker, dp_flow, vwap, session)

        # ─── 5. Options Flow Analysis ─────────────────────────
        opt_signal = self._analyze_options_flow(ticker, uw_flow)

        # ─── 6. Find best contract ────────────────────────────
        contract = None
        if icc_result.direction == ICCDirection.BULLISH:
            contract = await self.tradier.find_best_contract(ticker, "CALL")
        else:
            contract = await self.tradier.find_best_contract(ticker, "PUT")

        # ─── 7. Macro context ─────────────────────────────────
        macro = MacroContext(
            market_session=session,
            vix_level=15.0  # TODO: fetch real VIX
        )

        # ─── 8. Calculate levels ─────────────────────────────
        entry = icc_result.entry_zone or current_price
        sl    = icc_result.invalidation or (entry * 0.98 if icc_result.direction == ICCDirection.BULLISH else entry * 1.02)
        tp1   = icc_result.aoi_level and (entry + (entry - sl) * 2) or (entry * 1.03)
        tp2   = entry + (entry - sl) * 3.5

        if icc_result.direction == ICCDirection.BEARISH:
            tp1 = entry - (sl - entry) * 2
            tp2 = entry - (sl - entry) * 3.5

        # ─── 9. Master score ──────────────────────────────────
        score_result = self.scorer.score(
            ticker=ticker,
            icc_score=icc_result.score,
            icc_direction=icc_result.direction.value if icc_result.direction else "NEUTRAL",
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
            "direction":  icc_result.direction.value if icc_result.direction else "N/A",
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
                "icc":        score_result.icc,
                "dark_pool":  score_result.dark_pool,
                "options":    score_result.options_flow,
                "macro":      score_result.macro_bonus,
                "pre_post":   score_result.pre_post_bonus,
            },
            "channels":   score_result.alert_channels,
        }

    def _analyze_dp(self, ticker, dp_flow, vwap, session) -> Optional[DarkPoolSignal]:
        """Extract dark pool signal for ticker"""
        ticker_prints = [p for p in dp_flow if p.get("ticker") == ticker]
        if not ticker_prints:
            return None

        latest = ticker_prints[0]
        size   = float(latest.get("size", 0)) * float(latest.get("price", 0))
        price  = float(latest.get("price", 0))

        # Cluster detection
        cluster = len(ticker_prints) >= 3

        # Absorption: multiple prints in tight range
        if len(ticker_prints) >= 2:
            prices = [float(p.get("price", 0)) for p in ticker_prints]
            price_range = max(prices) - min(prices)
            absorption  = price_range / price < 0.003 if price > 0 else False
        else:
            absorption = False

        # Velocity
        velocity = "BURST" if len(ticker_prints) >= 3 else "STEADY"

        return DarkPoolSignal(
            print_price=price,
            print_size=size,
            above_vwap=price > vwap if vwap > 0 else False,
            cluster=cluster,
            absorption=absorption,
            session=session,
            velocity=velocity,
        )

    def _analyze_options_flow(self, ticker, uw_flow) -> Optional[OptionsFlowSignal]:
        """Extract options flow signal for ticker"""
        ticker_flow = [f for f in uw_flow if f.get("ticker") == ticker]
        if not ticker_flow:
            return None

        # Use largest premium order
        latest = max(ticker_flow, key=lambda x: float(x.get("premium", 0)))

        volume = int(latest.get("volume", 0))
        oi     = int(latest.get("open_interest", 1))
        vol_oi = volume / oi if oi > 0 else 0
        prem   = float(latest.get("premium", 0))
        ask_side = float(latest.get("ask_side_pct", 0))
        is_sweep = latest.get("is_sweep", False)

        # Golden sweep: large, aggressive, single order
        is_golden = (is_sweep and prem >= 500_000 and ask_side >= 0.85)

        return OptionsFlowSignal(
            volume=volume,
            open_interest=oi,
            vol_oi_ratio=vol_oi,
            executed_ask=ask_side,
            premium_total=prem,
            is_sweep=is_sweep,
            is_golden_sweep=is_golden,
            delta=float(latest.get("delta", 0.5)),
            iv_rank=float(latest.get("iv_rank", 50)),
            expiration_dte=int(latest.get("dte", 30)),
            contract=latest.get("option_symbol", ""),
        )

    def _estimate_adx(self, candles) -> float:
        """Simple ADX approximation from candles"""
        if len(candles) < 14:
            return 15.0

        ranges = [c.range for c in candles[-14:]]
        avg_range = sum(ranges) / len(ranges)

        # Approximate directionality
        bodies = [abs(c.close - c.open) for c in candles[-14:]]
        avg_body = sum(bodies) / len(bodies)

        # High body/range ratio = trending
        ratio = avg_body / avg_range if avg_range > 0 else 0
        return min(ratio * 50, 50)

    async def _get_watchlist(self) -> list[str]:
        """Get active watchlist from DB"""
        try:
            db = SessionLocal()
            items = db.query(WatchlistItem).filter(WatchlistItem.active == True).all()
            db.close()
            custom = [item.ticker for item in items]
            return list(set(DEFAULT_WATCHLIST + custom))
        except:
            return DEFAULT_WATCHLIST

    async def _get_uw_flow(self) -> list[dict]:
        try:
            return await self.uw.get_option_flow(min_premium=75_000)
        except Exception as e:
            logger.warning(f"UW flow fetch failed: {e}")
            return []

    async def _get_dp_flow(self) -> list[dict]:
        try:
            return await self.uw.get_dark_pool_flow()
        except Exception as e:
            logger.warning(f"UW dark pool fetch failed: {e}")
            return []

    async def _fire_alert(self, result: dict):
        """Save alert to DB and send to Discord"""
        alert_key = f"{result['ticker']}-{result['score']}-{datetime.now().strftime('%Y%m%d%H')}"
        if alert_key in self.alerts_today:
            return
        self.alerts_today.add(alert_key)

        # Save to DB
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
            logger.info(f"Alert saved: {result['ticker']} score={result['score']}")
        except Exception as e:
            logger.error(f"DB save failed: {e}")
            alert_id = 0

        # Send to Discord
        if self.discord:
            await self.discord.send_alert(result, alert_id)
