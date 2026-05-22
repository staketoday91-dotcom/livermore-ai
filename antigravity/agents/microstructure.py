from __future__ import annotations

from antigravity.agents.base import BaseAgent
from antigravity.db import DarkPoolActivity, GexLevel, OptionFlowSignal, session_scope
from antigravity.services.uw_client import UnusualWhalesClient, UnusualWhalesError, to_float


class MicrostructureAgent(BaseAgent):
    name = "microstructure_agent"

    def __init__(self) -> None:
        self.uw = UnusualWhalesClient()

    def execute(self) -> int:
        with session_scope() as session:
            tickers = [
                row[0]
                for row in session.query(OptionFlowSignal.ticker)
                .filter(OptionFlowSignal.status == "QUALIFIED")
                .distinct()
                .limit(20)
                .all()
            ]

        processed = 0
        for ticker in tickers:
            try:
                support, resistance, raw_gex = self._read_gex(ticker)
            except UnusualWhalesError:
                support, resistance, raw_gex = None, None, []

            try:
                dark_pool = self._read_dark_pool(ticker)
            except UnusualWhalesError:
                dark_pool = {
                    "total_premium": 0,
                    "largest_print": 0,
                    "print_count": 0,
                    "accumulation": False,
                    "raw": [],
                }

            with session_scope() as session:
                session.add(GexLevel(ticker=ticker, support_level=support, resistance_level=resistance, raw=raw_gex))
                session.add(
                    DarkPoolActivity(
                        ticker=ticker,
                        total_premium=dark_pool["total_premium"],
                        largest_print=dark_pool["largest_print"],
                        print_count=dark_pool["print_count"],
                        accumulation=dark_pool["accumulation"],
                        raw=dark_pool["raw"],
                    )
                )
            processed += 1

        return processed

    def _read_gex(self, ticker: str) -> tuple[float | None, float | None, list[dict]]:
        rows = self.uw.get_gex_by_strike(ticker)
        if not rows:
            return None, None, []

        ranked = sorted(rows, key=lambda row: abs(to_float(row.get("gamma_exposure"))), reverse=True)
        strikes = [to_float(row.get("strike")) for row in ranked[:2] if to_float(row.get("strike")) > 0]
        if not strikes:
            return None, None, rows
        if len(strikes) == 1:
            return strikes[0], strikes[0], rows
        return min(strikes), max(strikes), rows

    def _read_dark_pool(self, ticker: str) -> dict:
        rows = self.uw.get_dark_pool(ticker, limit=10)
        premiums = [to_float(row.get("premium") or row.get("dollar_value")) for row in rows]
        total = sum(premiums)
        largest = max(premiums, default=0)
        return {
            "total_premium": total,
            "largest_print": largest,
            "print_count": len(rows),
            "accumulation": largest >= 1_000_000 or total >= 3_000_000,
            "raw": rows,
        }

