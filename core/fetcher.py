"""
Livermore AI — Data Fetcher
Connects to Polygon.io, Tradier, and Unusual Whales
"""
import os
import httpx
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from core.icc_engine import Candle


POLYGON_KEY = os.getenv("POLYGON_API_KEY", "")
TRADIER_KEY = os.getenv("TRADIER_API_KEY", "")
UW_TOKEN    = os.getenv("UNUSUAL_WHALES_TOKEN", "")


class PolygonFetcher:
    """Fetches price data, volume, VWAP from Polygon.io"""

    BASE = "https://api.polygon.io"

    async def get_candles_1h(self, ticker: str, days: int = 5) -> list[Candle]:
        """Get 1H candles for ICC analysis"""
        end   = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        url   = f"{self.BASE}/v2/aggs/ticker/{ticker}/range/1/hour/{start}/{end}"

        async with httpx.AsyncClient() as client:
            r = await client.get(url, params={"apiKey": POLYGON_KEY, "adjusted": "true", "sort": "asc"})

        if r.status_code != 200:
            return []

        data = r.json()
        results = data.get("results", [])

        candles = []
        for bar in results:
            candles.append(Candle(
                open=bar["o"], high=bar["h"],
                low=bar["l"],  close=bar["c"],
                volume=bar["v"],
                timestamp=str(bar["t"])
            ))
        return candles

    async def get_vwap(self, ticker: str) -> Optional[float]:
        """Get current day VWAP"""
        today = datetime.now().strftime("%Y-%m-%d")
        url   = f"{self.BASE}/v2/aggs/ticker/{ticker}/range/1/day/{today}/{today}"

        async with httpx.AsyncClient() as client:
            r = await client.get(url, params={"apiKey": POLYGON_KEY})

        if r.status_code != 200:
            return None

        results = r.json().get("results", [])
        return results[0].get("vw") if results else None

    async def get_snapshot(self, ticker: str) -> dict:
        """Get current price snapshot"""
        url = f"{self.BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"

        async with httpx.AsyncClient() as client:
            r = await client.get(url, params={"apiKey": POLYGON_KEY})

        if r.status_code != 200:
            return {}

        data = r.json()
        ticker_data = data.get("ticker", {})
        day = ticker_data.get("day", {})

        return {
            "price":  ticker_data.get("lastTrade", {}).get("p", 0),
            "volume": day.get("v", 0),
            "vwap":   day.get("vw", 0),
            "change_pct": ticker_data.get("todaysChangePerc", 0),
        }

    async def get_avg_volume(self, ticker: str, days: int = 20) -> float:
        """Get 20-day average volume"""
        end   = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days + 5)).strftime("%Y-%m-%d")
        url   = f"{self.BASE}/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"

        async with httpx.AsyncClient() as client:
            r = await client.get(url, params={"apiKey": POLYGON_KEY, "adjusted": "true"})

        if r.status_code != 200:
            return 0

        results = r.json().get("results", [])
        if not results:
            return 0

        volumes = [bar["v"] for bar in results[-days:]]
        return sum(volumes) / len(volumes) if volumes else 0


class TradierFetcher:
    """Fetches options data from Tradier"""

    BASE    = "https://api.tradier.com/v1"
    HEADERS = {"Authorization": f"Bearer {TRADIER_KEY}", "Accept": "application/json"}

    async def get_options_chain(self, ticker: str, expiration: str) -> list[dict]:
        """Get full options chain for a specific expiration"""
        url = f"{self.BASE}/markets/options/chains"

        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=self.HEADERS,
                               params={"symbol": ticker, "expiration": expiration, "greeks": "true"})

        if r.status_code != 200:
            return []

        data = r.json()
        options = data.get("options", {})
        if not options:
            return []
        return options.get("option", []) or []

    async def get_expirations(self, ticker: str) -> list[str]:
        """Get available expiration dates"""
        url = f"{self.BASE}/markets/options/expirations"

        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=self.HEADERS,
                               params={"symbol": ticker, "includeAllRoots": "true"})

        if r.status_code != 200:
            return []

        data = r.json()
        exps = data.get("expirations", {})
        if not exps:
            return []
        return exps.get("date", []) or []

    async def find_best_contract(
        self,
        ticker:     str,
        direction:  str,    # CALL / PUT
        min_dte:    int = 21,
        max_dte:    int = 60,
        min_delta:  float = 0.35,
        max_delta:  float = 0.65,
    ) -> Optional[dict]:
        """
        Find the best contract matching Livermore criteria:
        - Delta 0.35-0.65
        - DTE 21-60 days (swing) or 0-5 (day trade)
        - Spread < 5% of mid
        - High OI (liquid)
        """
        expirations = await self.get_expirations(ticker)
        today = datetime.now().date()

        valid_exps = []
        for exp_str in expirations:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if min_dte <= dte <= max_dte:
                valid_exps.append((exp_str, dte))

        if not valid_exps:
            return None

        # Use nearest valid expiration
        exp_str, dte = min(valid_exps, key=lambda x: x[1])
        chain = await self.get_options_chain(ticker, exp_str)

        best = None
        best_score = -1

        for opt in chain:
            if opt.get("option_type", "").upper() != direction[0]:
                continue

            greeks = opt.get("greeks") or {}
            delta = abs(greeks.get("delta", 0))

            if not (min_delta <= delta <= max_delta):
                continue

            # Spread check
            bid = opt.get("bid", 0)
            ask = opt.get("ask", 0)
            mid = (bid + ask) / 2 if (bid + ask) > 0 else 0

            if mid <= 0:
                continue

            spread_pct = (ask - bid) / mid if mid > 0 else 1
            if spread_pct > 0.05:
                continue

            # Score this contract
            oi     = opt.get("open_interest", 0)
            volume = opt.get("volume", 0)
            iv     = greeks.get("iv", 0)

            contract_score = (
                (1 - abs(delta - 0.50)) * 40 +    # prefer near 0.50 delta
                min(oi / 1000, 20) +               # liquidity
                min(volume / 100, 20) +            # volume today
                (1 - spread_pct) * 20              # tight spread
            )

            if contract_score > best_score:
                best_score = contract_score
                best = {
                    "symbol":     opt.get("symbol"),
                    "strike":     opt.get("strike"),
                    "expiration": exp_str,
                    "dte":        dte,
                    "type":       direction,
                    "bid":        bid,
                    "ask":        ask,
                    "mid":        mid,
                    "delta":      delta,
                    "iv":         iv,
                    "open_interest": oi,
                    "volume":     volume,
                    "spread_pct": spread_pct,
                    "contract_label": f"{ticker} {opt.get('strike')}{direction[0]} {exp_str}",
                }

        return best


class UnusualWhalesFetcher:
    """
    Fetches options flow and dark pool data from Unusual Whales
    Uses basis plan endpoints
    """
    BASE    = "https://api.unusualwhales.com/api"
    HEADERS = {"Authorization": f"Bearer {UW_TOKEN}"}

    async def get_option_flow(self, min_premium: float = 100_000) -> list[dict]:
        """Get unusual options flow filtered by minimum premium"""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.BASE}/option-trades/flow-feed",
                headers=self.HEADERS,
                params={"min_premium": int(min_premium), "limit": 50}
            )

        if r.status_code != 200:
            return []

        data = r.json()
        return data.get("data", []) or []

    async def get_dark_pool_flow(self, ticker: str = None) -> list[dict]:
        """Get dark pool prints"""
        params = {"limit": 50}
        if ticker:
            params["ticker"] = ticker

        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.BASE}/darkpool/recent",
                headers=self.HEADERS,
                params=params
            )

        if r.status_code != 200:
            return []

        data = r.json()
        return data.get("data", []) or []

    async def get_ticker_flow(self, ticker: str) -> dict:
        """Get all flow data for a specific ticker"""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.BASE}/stock/{ticker}/option-contracts",
                headers=self.HEADERS,
            )

        if r.status_code != 200:
            return {}

        return r.json().get("data", {}) or {}

    async def get_gex(self, ticker: str) -> Optional[float]:
        """Get Gamma Exposure for ticker"""
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.BASE}/stock/{ticker}/greek-exposure",
                headers=self.HEADERS,
            )

        if r.status_code != 200:
            return None

        data = r.json().get("data", {})
        return data.get("gex") if data else None
