"""
Livermore AI — Data Fetcher
Polygon.io + Tradier (UW desactivado para beta)
"""
import os
import httpx
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from core.icc_engine import Candle

POLYGON_KEY = os.getenv("POLYGON_API_KEY", "")
TRADIER_KEY = os.getenv("TRADIER_API_KEY", "")


class PolygonFetcher:
    BASE = "https://api.polygon.io"

    async def get_candles_1h(self, ticker: str, days: int = 5) -> list[Candle]:
        end   = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        url   = f"{self.BASE}/v2/aggs/ticker/{ticker}/range/1/hour/{start}/{end}"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params={"apiKey": POLYGON_KEY, "adjusted": "true", "sort": "asc"})
        if r.status_code != 200:
            return []
        candles = []
        for bar in r.json().get("results", []):
            candles.append(Candle(
                open=bar["o"], high=bar["h"],
                low=bar["l"],  close=bar["c"],
                volume=bar["v"], timestamp=str(bar["t"])
            ))
        return candles

    async def get_vwap(self, ticker: str) -> Optional[float]:
        today = datetime.now().strftime("%Y-%m-%d")
        url   = f"{self.BASE}/v2/aggs/ticker/{ticker}/range/1/day/{today}/{today}"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params={"apiKey": POLYGON_KEY})
        if r.status_code != 200:
            return None
        results = r.json().get("results", [])
        return results[0].get("vw") if results else None

    async def get_snapshot(self, ticker: str) -> dict:
        url = f"{self.BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params={"apiKey": POLYGON_KEY})
        if r.status_code != 200:
            return {}
        ticker_data = r.json().get("ticker", {})
        day = ticker_data.get("day", {})
        return {
            "price":      ticker_data.get("lastTrade", {}).get("p", 0),
            "volume":     day.get("v", 0),
            "vwap":       day.get("vw", 0),
            "change_pct": ticker_data.get("todaysChangePerc", 0),
        }

    async def get_avg_volume(self, ticker: str, days: int = 20) -> float:
        end   = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days + 5)).strftime("%Y-%m-%d")
        url   = f"{self.BASE}/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, params={"apiKey": POLYGON_KEY, "adjusted": "true"})
        if r.status_code != 200:
            return 0
        results = r.json().get("results", [])
        volumes = [bar["v"] for bar in results[-days:]]
        return sum(volumes) / len(volumes) if volumes else 0


class TradierFetcher:
    BASE = "https://api.tradier.com/v1"

    @property
    def headers(self):
        return {"Authorization": f"Bearer {TRADIER_KEY}", "Accept": "application/json"}

    async def get_options_chain(self, ticker: str, expiration: str) -> list[dict]:
        url = f"{self.BASE}/markets/options/chains"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=self.headers,
                                 params={"symbol": ticker, "expiration": expiration, "greeks": "true"})
        if r.status_code != 200:
            return []
        options = r.json().get("options", {})
        return options.get("option", []) or [] if options else []

    async def get_expirations(self, ticker: str) -> list[str]:
        url = f"{self.BASE}/markets/options/expirations"
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=self.headers,
                                 params={"symbol": ticker, "includeAllRoots": "true"})
        if r.status_code != 200:
            return []
        exps = r.json().get("expirations", {})
        return exps.get("date", []) or [] if exps else []

    async def get_options_flow_proxy(self, ticker: str) -> dict:
        """
        Proxy para options flow usando datos de Tradier.
        Detecta actividad inusual comparando vol vs OI en la chain.
        Reemplaza UW para beta.
        """
        expirations = await self.get_expirations(ticker)
        if not expirations:
            return {}

        # Usar la expiracion mas proxima con DTE razonable
        today = datetime.now().date()
        target_exp = None
        for exp_str in expirations[:6]:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - today).days
            if 7 <= dte <= 45:
                target_exp = exp_str
                break

        if not target_exp:
            target_exp = expirations[0]

        chain = await self.get_options_chain(ticker, target_exp)
        if not chain:
            return {}

        # Encontrar el contrato con mayor actividad (vol/OI)
        best_call = None
        best_put  = None
        best_call_score = 0
        best_put_score  = 0

        for opt in chain:
            volume = opt.get("volume") or 0
            oi     = opt.get("open_interest") or 1
            greeks = opt.get("greeks") or {}
            delta  = abs(greeks.get("delta", 0))
            bid    = opt.get("bid") or 0
            ask    = opt.get("ask") or 0
            mid    = (bid + ask) / 2

            if mid <= 0 or not (0.25 <= delta <= 0.75):
                continue

            vol_oi = volume / oi
            premium_est = volume * mid * 100
            score = vol_oi * 10 + min(premium_est / 10000, 50)

            opt_type = opt.get("option_type", "").lower()
            if opt_type == "call" and score > best_call_score:
                best_call_score = score
                best_call = {**opt, "vol_oi_ratio": vol_oi, "premium_estimate": premium_est,
                             "expiration": target_exp, "greeks": greeks}
            elif opt_type == "put" and score > best_put_score:
                best_put_score = score
                best_put = {**opt, "vol_oi_ratio": vol_oi, "premium_estimate": premium_est,
                            "expiration": target_exp, "greeks": greeks}

        return {"call": best_call, "put": best_put, "expiration": target_exp}

    async def find_best_contract(
        self, ticker: str, direction: str,
        min_dte: int = 21, max_dte: int = 60,
        min_delta: float = 0.35, max_delta: float = 0.65,
    ) -> Optional[dict]:
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

        exp_str, dte = min(valid_exps, key=lambda x: x[1])
        chain = await self.get_options_chain(ticker, exp_str)

        best = None
        best_score = -1

        for opt in chain:
            if opt.get("option_type", "").upper() != direction[0]:
                continue
            greeks = opt.get("greeks") or {}
            delta  = abs(greeks.get("delta", 0))
            if not (min_delta <= delta <= max_delta):
                continue
            bid = opt.get("bid", 0)
            ask = opt.get("ask", 0)
            mid = (bid + ask) / 2 if (bid + ask) > 0 else 0
            if mid <= 0:
                continue
            spread_pct = (ask - bid) / mid if mid > 0 else 1
            if spread_pct > 0.05:
                continue
            oi     = opt.get("open_interest", 0)
            volume = opt.get("volume", 0)
            contract_score = (
                (1 - abs(delta - 0.50)) * 40 +
                min(oi / 1000, 20) +
                min(volume / 100, 20) +
                (1 - spread_pct) * 20
            )
            if contract_score > best_score:
                best_score = contract_score
                best = {
                    "symbol":         opt.get("symbol"),
                    "strike":         opt.get("strike"),
                    "expiration":     exp_str,
                    "dte":            dte,
                    "type":           direction,
                    "bid":            bid,
                    "ask":            ask,
                    "mid":            mid,
                    "delta":          delta,
                    "iv":             greeks.get("iv", 0),
                    "open_interest":  oi,
                    "volume":         volume,
                    "spread_pct":     spread_pct,
                    "contract_label": f"{ticker} {opt.get('strike')}{direction[0]} {exp_str}",
                }
        return best


class UnusualWhalesFetcher:
    """
    DESACTIVADO para beta — sin API de pago.
    El scanner usa TradierFetcher.get_options_flow_proxy() en su lugar.
    Cuando se active UW API, descomentar los metodos reales.
    """

    async def get_option_flow(self, min_premium: float = 100_000) -> list[dict]:
        return []

    async def get_dark_pool_flow(self, ticker: str = None) -> list[dict]:
        return []

    async def get_ticker_flow(self, ticker: str) -> dict:
        return {}

    async def get_gex(self, ticker: str) -> Optional[float]:
        return None
