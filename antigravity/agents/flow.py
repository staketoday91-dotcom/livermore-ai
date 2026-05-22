from __future__ import annotations

from antigravity.agents.base import BaseAgent
from antigravity.config import get_settings
from antigravity.db import OptionFlowSignal, session_scope
from antigravity.services.uw_client import UnusualWhalesClient, normalize_flow_item, normalize_screener_item
from core.institutional_rules import min_option_premium


class WhaleScannerAgent(BaseAgent):
    name = "whale_scanner_agent"

    def __init__(self) -> None:
        self.settings = get_settings()
        self.uw = UnusualWhalesClient()

    def execute(self) -> int:
        floor = min_option_premium()
        alerts = [
            ("FLOW_ALERT", item)
            for item in self.uw.get_flow_alerts(limit=150, min_premium=floor)
        ]
        screener_rows = [
            ("SCREENER", item)
            for item in self.uw.get_option_contract_screener(limit=100, min_premium=floor)
        ]
        alerts.extend(screener_rows)
        processed = 0

        with session_scope() as session:
            for source, item in alerts:
                normalized = normalize_screener_item(item) if source == "SCREENER" else normalize_flow_item(item)
                if not normalized["ticker"]:
                    continue

                rejection_reasons = []
                accepted_reasons = []

                if normalized["premium"] < floor:
                    rejection_reasons.append(f"premium below ${floor:,.0f}")
                else:
                    accepted_reasons.append("institutional premium threshold met")

                if "ASK" not in normalized["side"] and normalized["ask_side_pct"] < 0.7:
                    rejection_reasons.append("not aggressive ASK-side flow")
                else:
                    accepted_reasons.append("aggressive ASK-side execution")

                if not normalized["oi_broken"]:
                    rejection_reasons.append("volume did not break open interest")
                else:
                    accepted_reasons.append("volume broke open interest")

                if not normalized["is_single_leg"]:
                    rejection_reasons.append("multi-leg or ambiguous structure")
                else:
                    accepted_reasons.append("single-leg directional structure")

                normalized["status"] = "OBSERVED_REJECTED" if rejection_reasons else "QUALIFIED"
                normalized["rejection_reason"] = "; ".join(rejection_reasons) if rejection_reasons else None
                normalized["accepted_reason"] = f"{source}: " + ("; ".join(accepted_reasons) if accepted_reasons else "observed")

                existing = None
                if normalized.get("uw_alert_id"):
                    existing = (
                        session.query(OptionFlowSignal)
                        .filter(OptionFlowSignal.uw_alert_id == normalized["uw_alert_id"])
                        .first()
                    )
                elif normalized["contract_symbol"]:
                    existing = (
                        session.query(OptionFlowSignal)
                        .filter(
                            OptionFlowSignal.contract_symbol == normalized["contract_symbol"],
                            OptionFlowSignal.tape_time == normalized["tape_time"],
                            OptionFlowSignal.execution_type == normalized["execution_type"],
                        )
                        .first()
                    )
                if existing:
                    continue

                session.add(OptionFlowSignal(**normalized))
                processed += 1

        return processed

