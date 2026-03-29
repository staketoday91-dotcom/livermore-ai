"""
Livermore AI — Master Scoring Engine
Combines ICC + Dark Pool + Options Flow + Macro into final score
"""
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, time
import pytz


@dataclass
class DarkPoolSignal:
    print_price:    float
    print_size:     float           # in dollars
    above_vwap:     bool
    cluster:        bool            # 3+ prints same price in 30min
    absorption:     bool            # high volume, tight range
    session:        str             # PRE / REGULAR / POST
    velocity:       str             # BURST / STEADY (burst = options setup)
    score:          int = 0


@dataclass
class OptionsFlowSignal:
    volume:         int
    open_interest:  int
    vol_oi_ratio:   float
    executed_ask:   float           # % executed at ask
    premium_total:  float           # total premium in dollars
    is_sweep:       bool
    is_golden_sweep:bool
    delta:          float
    iv_rank:        float
    expiration_dte: int
    contract:       str
    score:          int = 0


@dataclass
class MacroContext:
    has_fomc:       bool = False
    has_cpi:        bool = False
    has_nfp:        bool = False
    has_earnings:   bool = False
    earnings_dte:   int  = 99       # days to earnings
    opex_week:      bool = False
    vix_level:      float = 15.0
    market_session: str  = "REGULAR"


@dataclass
class LivermoreScorecardResult:
    total:          int
    icc:            int
    dark_pool:      int
    options_flow:   int
    macro_bonus:    int
    pre_post_bonus: int

    tier:           str             # ALERT / PREMIUM / LIVERMORE
    should_alert:   bool
    alert_channels: list[int]       # which tiers to notify
    reason:         str
    contract:       str = ""
    entry:          float = 0
    stop_loss:      float = 0
    target1:        float = 0
    target2:        float = 0


class LivermoreScorer:
    """
    Master scoring system — all signals converge here

    Score distribution:
    - ICC complete (35 pts max)
    - Dark Pool cluster + VWAP (30 pts max)
    - Options flow / golden sweep (25 pts max)
    - Macro clean + regime bonus (10 pts max)

    Thresholds:
    - 75-84: browser only (Tier 1)
    - 85-94: browser + Discord (Tier 2)
    - 95+:   all channels (Tier 3 — Livermore would sit down)
    """

    NY_TZ = pytz.timezone("America/New_York")

    def score(
        self,
        ticker:         str,
        icc_score:      int,
        icc_direction:  str,
        entry_price:    float,
        stop_loss:      float,
        target1:        float,
        target2:        float,
        dark_pool:      Optional[DarkPoolSignal],
        options_flow:   Optional[OptionsFlowSignal],
        macro:          MacroContext,
        adx:            float,
        regime:         str,
    ) -> LivermoreScorecardResult:

        score_icc       = 0
        score_dp        = 0
        score_opt       = 0
        score_macro     = 0
        score_prepost   = 0
        reasons         = []
        contract        = ""

        # ─── ICC SCORING ─────────────────────────────────────
        score_icc = min(icc_score, 35)
        if icc_score >= 28:
            reasons.append(f"ICC Continuation fuerte ({icc_score}/35)")
        elif icc_score >= 20:
            reasons.append(f"ICC Continuation ({icc_score}/35)")

        # ─── DARK POOL SCORING ───────────────────────────────
        if dark_pool:
            dp = dark_pool

            # Base: print size
            if dp.print_size >= 1_000_000:
                score_dp += 10
            elif dp.print_size >= 500_000:
                score_dp += 7

            # VWAP position (critical)
            if dp.above_vwap:
                score_dp += 8
                reasons.append("Dark pool ENCIMA del VWAP (compra urgente)")
            else:
                score_dp += 3

            # Cluster = institutional accumulation
            if dp.cluster:
                score_dp += 8
                reasons.append("Cluster de prints (3+ en 30min) = acumulacion")

            # Absorption = strongest signal
            if dp.absorption:
                score_dp += 4
                reasons.append("Absorcion silenciosa detectada")

            # Pre/Post market bonus
            if dp.session in ("PRE", "POST"):
                score_prepost += 5
                reasons.append(f"Dark pool en {dp.session}-market (intencion pura)")

            # Velocity = options setup signal
            if dp.velocity == "BURST":
                score_prepost += 3
                reasons.append("Velocidad BURST = setup de opciones manana")

            score_dp = min(score_dp, 30)

        # ─── OPTIONS FLOW SCORING ────────────────────────────
        if options_flow:
            opt = options_flow

            # Vol/OI ratio
            if opt.vol_oi_ratio >= 5:
                score_opt += 8
                reasons.append(f"Volumen {opt.vol_oi_ratio:.1f}x el OI")
            elif opt.vol_oi_ratio >= 3:
                score_opt += 5

            # Ask execution
            if opt.executed_ask >= 0.85:
                score_opt += 5
                reasons.append(f"{opt.executed_ask*100:.0f}% ejecutado en ask")
            elif opt.executed_ask >= 0.70:
                score_opt += 3

            # Premium size
            if opt.premium_total >= 500_000:
                score_opt += 5
            elif opt.premium_total >= 100_000:
                score_opt += 3

            # Sweep / Golden sweep
            if opt.is_golden_sweep:
                score_opt += 7
                reasons.append("GOLDEN SWEEP detectado")
            elif opt.is_sweep:
                score_opt += 4
                reasons.append("Sweep agresivo en ask")

            # Contract quality
            if 0.35 <= opt.delta <= 0.65:
                score_opt += 3
            if opt.iv_rank <= 60:
                score_opt += 2

            # Expiration quality for swing
            if 21 <= opt.expiration_dte <= 60:
                score_opt += 2

            contract = opt.contract
            score_opt = min(score_opt, 25)

        # ─── MACRO CONTEXT ───────────────────────────────────
        if macro.has_fomc or macro.has_cpi or macro.has_nfp:
            score_macro -= 20  # Hard block on binary events
            reasons.append("MACRO EVENT — score reducido, setup invalido")
        elif macro.has_earnings and macro.earnings_dte <= 5:
            score_macro -= 10
            reasons.append(f"Earnings en {macro.earnings_dte} dias — IV va a explotar")
        else:
            score_macro += 5
            reasons.append("Contexto macro limpio")

        if macro.opex_week:
            score_macro -= 3
            reasons.append("OPEX week — charm pressure activo")

        if macro.vix_level > 30:
            score_macro -= 5
        elif macro.vix_level < 20:
            score_macro += 3

        # Regime bonus
        if "TRENDING" in regime:
            score_macro += 2

        score_macro = max(score_macro, -20)

        # ─── TOTAL ───────────────────────────────────────────
        total = score_icc + score_dp + score_opt + score_macro + score_prepost
        total = max(0, min(total, 100))

        # ─── DECISION ────────────────────────────────────────
        should_alert = total >= 75
        alert_channels = []
        tier = "NONE"

        if total >= 95:
            tier = "LIVERMORE"
            alert_channels = [1, 2, 3]  # All tiers
        elif total >= 85:
            tier = "PREMIUM"
            alert_channels = [1, 2]
        elif total >= 75:
            tier = "ALERT"
            alert_channels = [1]

        reason = " | ".join(reasons) if reasons else "Score insuficiente"

        return LivermoreScorecardResult(
            total=total,
            icc=score_icc,
            dark_pool=score_dp,
            options_flow=score_opt,
            macro_bonus=score_macro,
            pre_post_bonus=score_prepost,
            tier=tier,
            should_alert=should_alert,
            alert_channels=alert_channels,
            reason=reason,
            contract=contract,
            entry=entry_price,
            stop_loss=stop_loss,
            target1=target1,
            target2=target2,
        )

    def classify_flow_intent(
        self,
        dp_session:         str,
        dp_velocity:        str,
        dp_print_time:      datetime,
        options_calls_next: bool,
        gap_type:           str,   # "DIRECT" / "PULLBACK"
    ) -> str:
        """
        Determines if pre/post market activity is:
        - OPTIONS_SETUP: positioning for options play at open
        - EQUITY_ACCUMULATION: pure stock position building
        - DISTRIBUTION: institutional selling
        """
        if dp_session in ("PRE", "POST"):
            if dp_velocity == "BURST" and options_calls_next:
                return "OPTIONS_SETUP"
            elif dp_velocity == "BURST" and gap_type == "PULLBACK":
                return "OPTIONS_SETUP"
            elif dp_velocity == "STEADY":
                return "EQUITY_ACCUMULATION"
            else:
                return "DISTRIBUTION" if not options_calls_next else "OPTIONS_SETUP"
        return "REGULAR_SESSION"

    def get_institutional_window(self) -> str:
        """Returns current institutional activity window"""
        now = datetime.now(self.NY_TZ).time()

        if time(9, 30) <= now <= time(11, 0):
            return "ACCUMULATION_MORNING"
        elif time(11, 30) <= now <= time(13, 0):
            return "DISTRIBUTION_MIDDAY"
        elif time(14, 30) <= now <= time(16, 0):
            return "ACCUMULATION_AFTERNOON"
        elif now < time(9, 30):
            return "PRE_MARKET"
        elif now > time(16, 0):
            return "POST_MARKET"
        else:
            return "QUIET_HOURS"
