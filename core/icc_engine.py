"""
Livermore AI — ICC Detection Engine
Detects Indication / Correction / Continuation patterns on 1H charts
"""
import numpy as np
from dataclasses import dataclass
from typing import Optional
from enum import Enum


class ICCPhase(Enum):
    NONE        = "NONE"
    INDICATION  = "INDICATION"
    CORRECTION  = "CORRECTION"
    CONTINUATION= "CONTINUATION"


class ICCDirection(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


@dataclass
class Candle:
    open:   float
    high:   float
    low:    float
    close:  float
    volume: int
    timestamp: str = ""

    @property
    def body(self): return abs(self.close - self.open)
    @property
    def range(self): return self.high - self.low
    @property
    def body_ratio(self): return self.body / self.range if self.range > 0 else 0
    @property
    def is_bullish(self): return self.close > self.open
    @property
    def is_bearish(self): return self.close < self.open
    @property
    def upper_wick(self): return self.high - max(self.open, self.close)
    @property
    def lower_wick(self): return min(self.open, self.close) - self.low


@dataclass
class ICCResult:
    phase:          ICCPhase
    direction:      Optional[ICCDirection]
    score:          int                 # 0-35 points
    signal_type:    str                 # "false_harami" / "shooting_star" / "engulfing" / "none"
    entry_zone:     Optional[float]
    invalidation:   Optional[float]     # price that breaks the ICC
    aoi_level:      Optional[float]     # Area of Interest
    confidence:     float               # 0.0 - 1.0
    description:    str


class ICCDetector:
    """
    ICC — Indication / Correction / Continuation
    Based on Trades by Sci methodology

    Rules:
    - Indication: Large impulse candle that breaks structure (body > 60% of range)
    - Correction: Counter-candle(s) pulling back to AOI — does NOT break indication high/low
    - Continuation: Price resumes original direction from AOI — ENTRY HERE
    - Key: Never enter on first break — wait for 2nd test (false harami or engulfing)
    """

    # Minimum body ratio to qualify as indication candle
    MIN_INDICATION_BODY  = 0.60
    # Max correction depth as % of indication candle
    MAX_CORRECTION_DEPTH = 0.70
    # Minimum volume multiplier vs average for indication
    MIN_VOLUME_MULTIPLIER = 1.5

    def detect(self, candles: list[Candle], avg_volume: float) -> ICCResult:
        if len(candles) < 5:
            return ICCResult(ICCPhase.NONE, None, 0, "none", None, None, None, 0.0, "Insufficient data")

        score = 0
        latest = candles[-1]
        prev = candles[-2]
        prev2 = candles[-3] if len(candles) > 2 else None

        # ─── STEP 1: Find Indication candle ─────────────────
        indication = self._find_indication(candles, avg_volume)
        if not indication:
            return ICCResult(ICCPhase.NONE, None, 0, "none", None, None, None, 0.0,
                           "No indication candle detected")

        ind_candle, ind_index, ind_direction = indication
        score += 10

        # ─── STEP 2: Validate Correction ────────────────────
        correction = self._validate_correction(candles, ind_index, ind_direction, ind_candle)
        if not correction:
            return ICCResult(ICCPhase.INDICATION, ind_direction, score, "none",
                           None, None, None, 0.3, f"Indication detected — waiting for correction")

        aoi_level, correction_depth = correction
        score += 10

        # Bonus: shallow correction (< 40%) = stronger signal
        if correction_depth < 0.40:
            score += 3

        # ─── STEP 3: Look for Continuation signal ───────────
        continuation = self._find_continuation_signal(candles, ind_direction, aoi_level)
        if not continuation:
            return ICCResult(ICCPhase.CORRECTION, ind_direction, score, "none",
                           aoi_level, None, aoi_level, 0.6,
                           f"Correction in progress — watch for continuation at ${aoi_level:.2f}")

        signal_type, entry_zone, invalidation, signal_score = continuation
        score += signal_score

        # Volume confirmation on continuation
        if latest.volume > avg_volume * self.MIN_VOLUME_MULTIPLIER:
            score += 5
            desc_vol = " + volume confirmation"
        else:
            desc_vol = ""

        confidence = score / 35.0

        return ICCResult(
            phase=ICCPhase.CONTINUATION,
            direction=ind_direction,
            score=min(score, 35),
            signal_type=signal_type,
            entry_zone=entry_zone,
            invalidation=invalidation,
            aoi_level=aoi_level,
            confidence=confidence,
            description=f"ICC {ind_direction.value} Continuation — {signal_type} at AOI ${aoi_level:.2f}{desc_vol}"
        )

    def _find_indication(self, candles, avg_volume):
        """Find the most recent valid indication candle"""
        # Look back up to 10 candles for indication
        lookback = min(10, len(candles) - 3)

        for i in range(len(candles) - 3, len(candles) - 3 - lookback, -1):
            if i < 0:
                break
            c = candles[i]

            # Must have significant body
            if c.body_ratio < self.MIN_INDICATION_BODY:
                continue

            # Must have above-average volume
            if avg_volume > 0 and c.volume < avg_volume * 0.8:
                continue

            # Determine direction
            direction = ICCDirection.BULLISH if c.is_bullish else ICCDirection.BEARISH

            # Must represent a structure break
            if i >= 3:
                recent_highs = [candles[j].high for j in range(max(0, i-5), i)]
                recent_lows  = [candles[j].low  for j in range(max(0, i-5), i)]

                if direction == ICCDirection.BULLISH and c.high > max(recent_highs):
                    return c, i, direction
                elif direction == ICCDirection.BEARISH and c.low < min(recent_lows):
                    return c, i, direction
            else:
                return c, i, direction

        return None

    def _validate_correction(self, candles, ind_index, direction, ind_candle):
        """
        Validate that a correction happened after indication
        Returns (aoi_level, depth_ratio) or None
        """
        correction_candles = candles[ind_index + 1:]

        if len(correction_candles) == 0:
            return None

        ind_body = ind_candle.body
        aoi_level = None

        if direction == ICCDirection.BULLISH:
            # Pullback from indication high
            ind_high = ind_candle.high
            ind_low  = ind_candle.low
            lowest_correction = min(c.low for c in correction_candles)

            # Must not break the indication low
            if lowest_correction < ind_low:
                return None

            # Calculate depth
            depth = (ind_high - lowest_correction) / ind_body if ind_body > 0 else 0
            if depth > self.MAX_CORRECTION_DEPTH:
                return None

            aoi_level = lowest_correction + (ind_high - lowest_correction) * 0.3
            return aoi_level, depth

        else:  # BEARISH
            ind_low  = ind_candle.low
            ind_high = ind_candle.high
            highest_correction = max(c.high for c in correction_candles)

            if highest_correction > ind_high:
                return None

            depth = (highest_correction - ind_low) / ind_body if ind_body > 0 else 0
            if depth > self.MAX_CORRECTION_DEPTH:
                return None

            aoi_level = highest_correction - (highest_correction - ind_low) * 0.3
            return aoi_level, depth

    def _find_continuation_signal(self, candles, direction, aoi_level):
        """
        Look for valid continuation entry signals at AOI
        Returns (signal_type, entry_zone, invalidation, score) or None
        """
        latest = candles[-1]
        prev   = candles[-2] if len(candles) > 1 else None

        if not prev:
            return None

        # Price must be near AOI (within 1%)
        price_near_aoi = abs(latest.close - aoi_level) / aoi_level < 0.015

        if not price_near_aoi:
            return None

        if direction == ICCDirection.BULLISH:

            # False Harami Breakout — best signal per Trades by Sci
            if (prev.is_bearish and latest.is_bullish and
                latest.close > prev.open and
                latest.body_ratio > 0.55):
                return "false_harami_breakout", latest.close, prev.low, 12

            # Engulfing bullish — no wicks (clean)
            if (prev.is_bearish and latest.is_bullish and
                latest.open <= prev.close and
                latest.close >= prev.open and
                latest.lower_wick < latest.body * 0.15):
                return "bullish_engulfing", latest.close, latest.low, 10

            # Shooting star reversal in correction
            if (prev.upper_wick > prev.body * 2 and
                prev.is_bearish and
                latest.is_bullish):
                return "shooting_star_reversal", latest.close, prev.low, 8

        else:  # BEARISH

            # False Harami breakdown
            if (prev.is_bullish and latest.is_bearish and
                latest.close < prev.open and
                latest.body_ratio > 0.55):
                return "false_harami_breakdown", latest.close, prev.high, 12

            # Engulfing bearish — clean
            if (prev.is_bullish and latest.is_bearish and
                latest.open >= prev.close and
                latest.close <= prev.open and
                latest.upper_wick < latest.body * 0.15):
                return "bearish_engulfing", latest.close, latest.high, 10

            # Shooting star in correction
            if (prev.upper_wick > prev.body * 2 and latest.is_bearish):
                return "shooting_star_top", latest.close, prev.high, 8

        return None


# ─── REGIME DETECTOR ─────────────────────────────────────
class RegimeDetector:
    """
    Determines if the market is trending or chopping
    Uses ADX + price structure
    """

    def classify(self, adx: float, candles: list[Candle]) -> str:
        """Returns TRENDING / CHOP / REVERSAL"""

        if adx >= 25:
            # Strong trend
            recent = candles[-5:]
            highs = [c.high for c in recent]
            lows  = [c.low  for c in recent]

            if all(highs[i] > highs[i-1] for i in range(1, len(highs))):
                return "TRENDING_UP"
            elif all(lows[i] < lows[i-1] for i in range(1, len(lows))):
                return "TRENDING_DOWN"
            else:
                return "TRENDING"

        elif adx < 20:
            return "CHOP"

        else:
            return "TRANSITIONING"

    def is_valid_for_icc(self, regime: str) -> bool:
        return "TRENDING" in regime

    def is_valid_for_prima(self, regime: str) -> bool:
        return regime in ("CHOP", "TRANSITIONING")
