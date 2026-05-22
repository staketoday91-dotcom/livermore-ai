from __future__ import annotations

from datetime import datetime, timedelta

from antigravity.agents.base import BaseAgent
from antigravity.config import get_settings
from antigravity.db import (
    DarkPoolActivity,
    GexLevel,
    MarketRegime,
    MarketTide,
    OptionFlowSignal,
    SectorRotation,
    TradeIdea,
    TradePlan,
    session_scope,
)


class PortfolioCommitteeAgent(BaseAgent):
    name = "portfolio_committee_agent"
    max_approved_per_cycle = 5

    def __init__(self) -> None:
        self.settings = get_settings()

    def execute(self) -> int:
        with session_scope() as session:
            self._expire_stale_pending(session)
            signals = (
                session.query(OptionFlowSignal)
                .filter(OptionFlowSignal.status == "QUALIFIED")
                .order_by(OptionFlowSignal.premium.desc(), OptionFlowSignal.created_at.desc())
                .limit(100)
                .all()
            )

            macro = session.query(MarketRegime).order_by(MarketRegime.id.desc()).first()
            tide = session.query(MarketTide).order_by(MarketTide.id.desc()).first()
            candidates = []

            for signal in signals:
                gex = session.query(GexLevel).filter(GexLevel.ticker == signal.ticker).order_by(GexLevel.id.desc()).first()
                dark = session.query(DarkPoolActivity).filter(DarkPoolActivity.ticker == signal.ticker).order_by(DarkPoolActivity.id.desc()).first()
                sector = self._latest_sector(session)
                assessment = self._assess_signal(signal, macro, tide, dark, gex, sector)
                candidates.append((assessment["score"], signal, gex, dark, sector, assessment))

            candidates.sort(key=lambda row: (row[0], row[1].premium or 0, row[1].volume_oi_ratio or 0), reverse=True)
            approved_count = 0
            processed = 0

            for _, signal, gex, dark, sector, assessment in candidates:
                approved_slot_available = approved_count < self.max_approved_per_cycle
                decision = self._decision(assessment, approved_slot_available)
                if decision == "APPROVED":
                    approved_count += 1

                direction = "LONG" if signal.contract_type == "CALL" else "SHORT"

                idea = TradeIdea(
                    ticker=signal.ticker,
                    direction=direction,
                    source_signal_id=signal.id,
                    thesis=self._build_thesis(signal, macro, tide, dark),
                    macro_bias=macro.market_bias if macro else "UNKNOWN",
                    sector_status=sector.status if sector else "UNKNOWN",
                    tide_sentiment=tide.sentiment if tide else "UNKNOWN",
                    conviction_score=assessment["score"],
                    status=decision,
                    rejection_reason=None if decision == "APPROVED" else assessment["blocker"],
                )
                session.add(idea)
                session.flush()

                plan = self._build_plan(idea.id, signal, direction, gex, assessment, decision)
                if decision == "APPROVED":
                    self._save_approved_plan(session, plan)
                else:
                    session.add(plan)

                signal.status = "PLANNED"
                processed += 1

        return processed

    def _expire_stale_pending(self, session, hours: int = 48) -> None:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        session.query(TradePlan).filter(
            TradePlan.execution_status == "PENDING",
            TradePlan.updated_at < cutoff,
        ).update(
            {"execution_status": "SUPERSEDED", "updated_at": datetime.utcnow()},
            synchronize_session=False,
        )

    def _save_approved_plan(self, session, plan: TradePlan) -> TradePlan:
        existing = (
            session.query(TradePlan)
            .filter(TradePlan.ticker == plan.ticker, TradePlan.execution_status == "PENDING")
            .order_by(TradePlan.id.desc())
            .first()
        )
        if existing:
            for field in (
                "idea_id",
                "direction",
                "entry_zone",
                "stop_loss",
                "target_zone",
                "invalidation",
                "approval_reason",
                "risk_notes",
                "setup_grade",
                "conviction_score",
            ):
                setattr(existing, field, getattr(plan, field))
            existing.updated_at = datetime.utcnow()
            session.query(TradePlan).filter(
                TradePlan.ticker == plan.ticker,
                TradePlan.execution_status == "PENDING",
                TradePlan.id != existing.id,
            ).update(
                {"execution_status": "SUPERSEDED", "updated_at": datetime.utcnow()},
                synchronize_session=False,
            )
            return existing

        session.add(plan)
        return plan

    def _latest_sector(self, session):
        return session.query(SectorRotation).order_by(SectorRotation.check_date.desc(), SectorRotation.capital_flow_rank.asc()).first()

    def _assess_signal(
        self,
        signal: OptionFlowSignal,
        macro: MarketRegime | None,
        tide: MarketTide | None,
        dark: DarkPoolActivity | None,
        gex: GexLevel | None,
        sector: SectorRotation | None,
    ) -> dict:
        score = 0
        reasons = []
        risks = []
        blockers = []
        entry_price = self._entry_price(signal)

        if signal.premium >= 1_000_000:
            score += 25
            reasons.append("premium above $1M")
        elif signal.premium >= 500_000:
            score += 18
            reasons.append("premium above $500K")
        elif signal.premium >= 250_000:
            score += 12
            reasons.append("premium above $250K")
        else:
            score += 5
            risks.append("premium is relatively small")

        if signal.ask_side_pct >= 0.85:
            score += 20
            reasons.append("ASK dominance above 85%")
        elif signal.ask_side_pct >= 0.7:
            score += 14
            reasons.append("ASK dominance above 70%")
        else:
            blockers.append("ASK dominance below institutional threshold")

        if signal.volume_oi_ratio >= 5:
            score += 20
            reasons.append("volume/OI ratio above 5x")
        elif signal.volume_oi_ratio >= 2:
            score += 15
            reasons.append("volume/OI ratio above 2x")
        elif signal.oi_broken:
            score += 10
            reasons.append("volume broke previous OI")
        else:
            blockers.append("volume did not break previous OI")

        if signal.is_single_leg:
            score += 12
            reasons.append("single-leg structure")
        else:
            blockers.append("multi-leg or ambiguous structure")

        if gex and gex.support_level and gex.resistance_level:
            gex_valid = self._gex_is_directionally_valid(signal, entry_price, gex)
            if gex_valid:
                score += 18
                reasons.append("GEX walls available for risk control")
            else:
                blockers.append(
                    f"GEX walls not actionable versus underlying price {entry_price:.2f}"
                    if entry_price
                    else "GEX walls not actionable because underlying price is missing"
                )
        else:
            blockers.append("missing GEX walls for dynamic stop/target")

        if dark and dark.accumulation:
            score += 10
            reasons.append("dark pool accumulation present")
        else:
            risks.append("no dark pool confirmation")

        if macro and macro.market_bias == "RISK_OFF":
            blockers.append("macro regime is RISK_OFF")
        elif macro and macro.market_bias == "RISK_ON":
            score += 5
            reasons.append("macro regime RISK_ON")

        if sector and sector.status == "DISTRIBUTION":
            risks.append(f"sector proxy {sector.sector_ticker} in DISTRIBUTION")

        if tide and tide.sentiment == "BULLISH_PRESSURE" and signal.contract_type == "CALL":
            score += 5
            reasons.append("market tide supports calls")
        elif tide and tide.sentiment == "BEARISH_PRESSURE" and signal.contract_type == "PUT":
            score += 5
            reasons.append("market tide supports puts")
        else:
            risks.append("market tide not aligned or unavailable")

        score = min(score, 100)
        if score < 85:
            blockers.append(f"score {score} below institutional approval threshold 85")

        blocker_text = "; ".join(blockers) if blockers else None
        return {
            "score": score,
            "reasons": "; ".join(reasons) or "qualified tape flow",
            "risks": "; ".join(risks) or "standard overnight OI confirmation risk",
            "blocker": blocker_text,
            "has_hard_blocker": bool(blockers),
            "entry_price": entry_price,
        }

    def _decision(self, assessment: dict, approved_slot_available: bool) -> str:
        if not assessment["has_hard_blocker"] and assessment["score"] >= 85 and approved_slot_available:
            return "APPROVED"
        if assessment["score"] >= 70:
            return "WATCHLIST"
        return "REJECTED"

    def _build_plan(self, idea_id: int, signal: OptionFlowSignal, direction: str, gex: GexLevel | None, assessment: dict, decision: str) -> TradePlan:
        entry_price = assessment.get("entry_price") or signal.underlying_price or signal.strike or 0
        if decision == "APPROVED":
            if direction == "LONG":
                stop = gex.support_level * 0.98
                target = f"Gamma resistance near {gex.resistance_level}"
                invalidation = f"Break below GEX support {gex.support_level}"
            else:
                stop = gex.resistance_level * 1.02
                target = f"Gamma support near {gex.support_level}"
                invalidation = f"Break above GEX resistance {gex.resistance_level}"

            return TradePlan(
                idea_id=idea_id,
                ticker=signal.ticker,
                direction=direction,
                entry_zone=f"Underlying near {entry_price:.2f}; option strike {signal.strike}",
                stop_loss=stop,
                target_zone=target,
                invalidation=invalidation,
                approval_reason=assessment["reasons"],
                risk_notes=assessment["risks"],
                setup_grade="A",
                execution_status="PENDING",
                conviction_score=assessment["score"],
            )

        status = "WATCHLIST" if decision == "WATCHLIST" else "INVALIDATED"
        return TradePlan(
            idea_id=idea_id,
            ticker=signal.ticker,
            direction=direction,
            entry_zone="WATCHLIST_ONLY" if decision == "WATCHLIST" else "REJECTED",
            stop_loss=0,
            target_zone=assessment["blocker"] or "Needs additional confirmation",
            invalidation=assessment["blocker"] or "Not enough confirmation",
            approval_reason=assessment["reasons"],
            risk_notes=assessment["risks"],
            setup_grade="B" if decision == "WATCHLIST" else "C",
            execution_status=status,
            conviction_score=assessment["score"],
        )

    def _entry_price(self, signal: OptionFlowSignal) -> float:
        if signal.underlying_price and signal.underlying_price > 0:
            return float(signal.underlying_price)
        raw = signal.raw or {}
        for key in ("stock_price", "underlying_price", "underlyingPrice"):
            try:
                value = float(raw.get(key) or 0)
                if value > 0:
                    return value
            except (TypeError, ValueError):
                pass
        return 0.0

    def _gex_is_directionally_valid(self, signal: OptionFlowSignal, entry_price: float, gex: GexLevel) -> bool:
        if not entry_price or not gex.support_level or not gex.resistance_level:
            return False
        if signal.contract_type == "CALL":
            return gex.support_level < entry_price < gex.resistance_level
        if signal.contract_type == "PUT":
            return gex.support_level < entry_price < gex.resistance_level
        return False

    def _build_thesis(self, signal: OptionFlowSignal, macro: MarketRegime | None, tide: MarketTide | None, dark: DarkPoolActivity | None) -> str:
        parts = [
            f"{signal.ticker} {signal.contract_type} flow on {signal.side}",
            f"premium ${signal.premium:,.0f}",
            f"vol/OI {signal.volume_oi_ratio:.2f}",
        ]
        if macro:
            parts.append(f"macro {macro.market_bias}")
        if tide:
            parts.append(f"tide {tide.sentiment}")
        if dark and dark.accumulation:
            parts.append("dark pool accumulation")
        return " | ".join(parts)

