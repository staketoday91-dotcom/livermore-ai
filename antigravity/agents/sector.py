from __future__ import annotations

from datetime import date

import yfinance as yf

from antigravity.agents.base import BaseAgent
from antigravity.db import SectorRotation, session_scope

SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLI", "XLP", "XLU", "XLB", "XLC", "XLRE"]


class SectorAgent(BaseAgent):
    name = "sector_agent"

    def execute(self) -> int:
        sectors = []
        for ticker in SECTOR_ETFS:
            hist = yf.Ticker(ticker).history(period="20d")
            if hist.empty:
                continue

            start = float(hist["Close"].iloc[0])
            last = float(hist["Close"].iloc[-1])
            perf = ((last - start) / start) * 100 if start else 0
            if perf > 2:
                status = "ACCUMULATION"
            elif perf < -2:
                status = "DISTRIBUTION"
            else:
                status = "NEUTRAL"
            sectors.append({"ticker": ticker, "performance": perf, "status": status})

        sectors.sort(key=lambda item: item["performance"], reverse=True)
        today = date.today()

        with session_scope() as session:
            for rank, sector in enumerate(sectors, start=1):
                existing = (
                    session.query(SectorRotation)
                    .filter(SectorRotation.check_date == today, SectorRotation.sector_ticker == sector["ticker"])
                    .one_or_none()
                )
                row = existing or SectorRotation(check_date=today, sector_ticker=sector["ticker"])
                row.capital_flow_rank = rank
                row.performance_20d = sector["performance"]
                row.status = sector["status"]
                row.raw = sector
                session.add(row)
        return len(sectors)

