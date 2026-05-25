"""
ICC en gráfico — velas UW + alineación MTF (4H > 1H).
"""
from __future__ import annotations

from typing import Optional

from core.icc_engine import Candle, ICCDetector, ICCDirection, ICCPhase, ICCResult


def structure_bias_4h(candles: list[Candle]) -> Optional[str]:
    """
    BULLISH | BEARISH | NEUTRAL según últimos swings en 4H.
    """
    if len(candles) < 3:
        return None
    a, b = candles[-2], candles[-1]
    hh = b.high > a.high
    hl = b.low > a.low
    lh = b.high < a.high
    ll = b.low < a.low
    if hh and hl:
        return "BULLISH"
    if lh and ll:
        return "BEARISH"
    return "NEUTRAL"


def mtf_conflicts(flow_direction: ICCDirection, bias_4h: Optional[str]) -> bool:
    """True si 4H contradice la dirección del flujo (doctrina: 4H gana)."""
    if not bias_4h or bias_4h == "NEUTRAL":
        return False
    return bias_4h != flow_direction.value


def detect_icc_1h(
    candles_1h: list[Candle],
    expected_direction: ICCDirection,
) -> tuple[ICCResult, Optional[str]]:
    """
    ICC en 1H. Devuelve (resultado, bias_4h opcional ya calculado fuera).
    """
    if len(candles_1h) < 5:
        empty = ICCResult(
            ICCPhase.NONE,
            None,
            0,
            "none",
            None,
            None,
            None,
            0.0,
            "Insufficient 1H candles",
        )
        return empty, None

    avg_vol = sum(c.volume for c in candles_1h) / max(len(candles_1h), 1) or 1.0
    result = ICCDetector().detect(candles_1h, avg_vol)

    if (
        result.phase == ICCPhase.CONTINUATION
        and result.direction
        and result.direction != expected_direction
    ):
        result = ICCResult(
            phase=ICCPhase.CORRECTION,
            direction=result.direction,
            score=max(result.score - 5, 0),
            signal_type=result.signal_type,
            entry_zone=result.entry_zone,
            invalidation=result.invalidation,
            aoi_level=result.aoi_level,
            confidence=result.confidence * 0.5,
            description=f"ICC continuation vs flujo ({result.direction.value} != {expected_direction.value})",
        )
    return result, None
