from __future__ import annotations

from antigravity.agents.base import BaseAgent
from antigravity.db import MarketTide, session_scope
from antigravity.services.uw_client import UnusualWhalesClient, to_float


class MarketTideAgent(BaseAgent):
    name = "market_tide_agent"

    def __init__(self) -> None:
        self.uw = UnusualWhalesClient()

    def execute(self) -> int:
        rows = self.uw.get_market_tide()
        if not rows:
            return 0

        latest = rows[-1]
        call_premium = to_float(latest.get("net_call_premium") or latest.get("call_premium"))
        put_premium = to_float(latest.get("net_put_premium") or latest.get("put_premium"))
        net_delta = to_float(latest.get("net_delta"))

        if call_premium > put_premium * 1.2:
            sentiment = "BULLISH_PRESSURE"
        elif put_premium > call_premium * 1.2:
            sentiment = "BEARISH_PRESSURE"
        else:
            sentiment = "NEUTRAL"

        with session_scope() as session:
            session.add(
                MarketTide(
                    net_call_premium=call_premium,
                    net_put_premium=put_premium,
                    net_delta=net_delta,
                    sentiment=sentiment,
                    speed_index=str(latest.get("speed_index") or "UNKNOWN"),
                    raw=latest,
                )
            )
        return 1

