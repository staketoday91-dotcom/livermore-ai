from __future__ import annotations

from datetime import datetime, timedelta

import yfinance as yf

from antigravity.agents.base import BaseAgent
from antigravity.db import BacktestContract, session_scope


class ContractBacktestAgent(BaseAgent):
    name = "contract_backtest_agent"

    def execute(self) -> int:
        with session_scope() as session:
            jobs = session.query(BacktestContract).filter(BacktestContract.status == "QUEUED").limit(20).all()

        processed = 0
        for job in jobs:
            result = self._run_backtest(job)
            with session_scope() as session:
                row = session.get(BacktestContract, job.id)
                if not row:
                    continue
                row.status = "DONE" if result["ok"] else "NEEDS_DATA"
                row.result_summary = result["summary"]
                row.result_json = result
                row.updated_at = datetime.utcnow()
                processed += 1

        return processed

    def _run_backtest(self, job: BacktestContract) -> dict:
        start_dt = job.alert_tape_time or job.created_at or datetime.utcnow()
        start_date = start_dt.date()
        end_date = (datetime.utcnow() + timedelta(days=2)).date()
        data = yf.download(job.ticker, start=start_date, end=end_date, interval="1d", progress=False, auto_adjust=True)
        if data.empty or not job.alert_underlying_price:
            return {
                "ok": False,
                "summary": "No hay suficientes datos de precio subyacente para evaluar todavia.",
            }

        closes = [float(value) for value in data["Close"].dropna().tolist()]
        if not closes:
            return {"ok": False, "summary": "No hay cierres disponibles para el subyacente."}

        last_close = closes[-1]
        max_close = max(closes)
        min_close = min(closes)
        direction = job.direction or ("SHORT" if job.contract_type == "PUT" else "LONG")
        if direction == "SHORT":
            best_move = (job.alert_underlying_price - min_close) / job.alert_underlying_price
            current_move = (job.alert_underlying_price - last_close) / job.alert_underlying_price
        else:
            best_move = (max_close - job.alert_underlying_price) / job.alert_underlying_price
            current_move = (last_close - job.alert_underlying_price) / job.alert_underlying_price

        return {
            "ok": True,
            "alert_price": job.alert_underlying_price,
            "last_close": last_close,
            "best_move_pct": best_move,
            "current_move_pct": current_move,
            "days_tested": len(closes),
            "summary": (
                f"{job.ticker} {job.contract_type} {job.strike}: movimiento actual {current_move:.2%}, "
                f"mejor excursion {best_move:.2%} en {len(closes)} sesiones."
            ),
        }
