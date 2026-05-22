from __future__ import annotations

from datetime import datetime

from antigravity.agents.base import BaseAgent
from antigravity.db import ContractMonitor, session_scope
from antigravity.services.uw_client import UnusualWhalesClient, normalize_flow_item


class ContractMonitorAgent(BaseAgent):
    name = "contract_monitor_agent"

    def __init__(self) -> None:
        self.uw = UnusualWhalesClient()

    def execute(self) -> int:
        processed = 0
        with session_scope() as session:
            monitors = session.query(ContractMonitor).filter(ContractMonitor.status == "ACTIVE").all()

        for monitor in monitors:
            recent = self.uw.get_recent_flow_for_ticker(monitor.ticker, limit=50)
            matches = []
            for item in recent:
                normalized = normalize_flow_item(item)
                if normalized["ticker"] != monitor.ticker:
                    continue
                if monitor.contract_type and normalized["contract_type"] != monitor.contract_type:
                    continue
                if monitor.strike and normalized["strike"] and abs(normalized["strike"] - monitor.strike) > max(0.01, monitor.strike * 0.002):
                    continue
                matches.append(normalized)

            with session_scope() as session:
                row = session.get(ContractMonitor, monitor.id)
                if not row:
                    continue
                if matches:
                    latest = sorted(matches, key=lambda item: item["tape_time"] or datetime.min)[-1]
                    row.last_seen_at = latest["tape_time"] or datetime.utcnow()
                    row.last_premium = latest["premium"]
                    row.last_volume = latest["volume"]
                    row.last_note = (
                        f"Nuevo tape detectado: {latest['side']} premium {latest['premium']:,.0f}, "
                        f"Vol/OI {latest['volume_oi_ratio']:.2f}x"
                    )
                else:
                    row.last_note = "Sin nuevos prints coincidentes en la ultima revision"
                row.updated_at = datetime.utcnow()
                processed += 1

        return processed
