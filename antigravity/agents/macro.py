from __future__ import annotations

import yfinance as yf

from antigravity.agents.base import BaseAgent
from antigravity.db import MarketRegime, session_scope


class MacroAgent(BaseAgent):
    name = "macro_agent"

    def execute(self) -> int:
        dxy = yf.Ticker("DX-Y.NYB").history(period="5d")
        vix = yf.Ticker("^VIX").history(period="1d")
        spy = yf.Ticker("SPY").history(period="50d")

        if dxy.empty or len(dxy) < 2 or vix.empty or spy.empty:
            raise RuntimeError("Missing macro market data from yfinance")

        dxy_last = float(dxy["Close"].iloc[-1])
        dxy_prev = float(dxy["Close"].iloc[-2])
        vix_last = float(vix["Close"].iloc[-1])
        spy_last = float(spy["Close"].iloc[-1])
        spy_sma_50 = float(spy["Close"].mean())
        dxy_trend = "BULLISH" if dxy_last > dxy_prev else "BEARISH"

        risk_points = 0
        if vix_last > 20:
            risk_points += 1
        if dxy_trend == "BULLISH":
            risk_points += 1
        if spy_last < spy_sma_50:
            risk_points += 1

        if risk_points >= 2:
            market_bias = "RISK_OFF"
            liquidity_index = "LOW"
        elif risk_points == 1:
            market_bias = "NEUTRAL"
            liquidity_index = "MEDIUM"
        else:
            market_bias = "RISK_ON"
            liquidity_index = "HIGH"

        with session_scope() as session:
            session.add(
                MarketRegime(
                    dxy_trend=dxy_trend,
                    vix_level=vix_last,
                    spy_price=spy_last,
                    spy_sma_50=spy_sma_50,
                    liquidity_index=liquidity_index,
                    market_bias=market_bias,
                    raw={
                        "dxy_last": dxy_last,
                        "dxy_prev": dxy_prev,
                        "risk_points": risk_points,
                    },
                )
            )
        return 1

