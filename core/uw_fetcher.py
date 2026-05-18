"""
Livermore AI — Unusual Whales Fetcher
Fuente unica de datos: UW API
Endpoints activos: flow alerts, dark pool, net premium, GEX, screener, market tide
"""
import os
import httpx
import asyncio
from datetime import datetime, date
from typing import Optional
import logging

logger = logging.getLogger("livermore.fetcher")

UW_TOKEN = os.getenv("UNUSUAL_WHALES_TOKEN", "")
UW_BASE  = "https://api.unusualwhales.com/api"

ETF_LIST = {"SPY", "QQQ", "IWM", "DIA", "XLF", "XLE", "XLK", "XLV", "XLI", "XLB", "XLU", "XLRE", "XLC", "XLY", "XLP", "GLD", "SLV", "TLT", "HYG", "EEM", "SOXL", "SOXS", "TQQQ", "UVXY", "VXX"}

INDEX_LIST = {"SPX", "SPXW", "NDX", "RUT", "VIX", "COMP"}


def classify_ticker(ticker: str) -> str:
    ticker = (ticker or "").upper()
    if ticker in INDEX_LIST:
        return "INDEX"
    if ticker in ETF_LIST:
        return "ETF"
    return "STOCK"


def _float(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def is_single_leg(flow_item: dict) -> bool:
    """
    Detecta si la transacción es single-leg (señal limpia) o multi-leg (señal ambigua).
    Single-leg = una sola compra/venta direccional.
    Multi-leg = spread, condor, collar, butterfly, ratio spread.
    """
    tags = str(flow_item.get("tags", "")).lower()
    trade_type = str(flow_item.get("trade_type", "")).lower()
    
    multi_leg_keywords = [
        "spread", "condor", "butterfly", "collar", "ratio", 
        "strangle", "straddle", "roll", "multi", "complex"
    ]
    
    for keyword in multi_leg_keywords:
        if keyword in tags or keyword in trade_type:
            return False
    
    # Si tiene has_floor o has_sweep = más probable single-leg con convicción
    has_sweep = flow_item.get("has_sweep", False)
    has_floor = flow_item.get("has_floor", False)
    
    return True  # default a single-leg si no hay indicadores de multi-leg


def _with_nominal_value(alert: dict) -> dict:
    enriched = dict(alert)
    total_premium = _float(enriched.get("total_premium"))
    if total_premium > 0:
        enriched["nominal_value"] = total_premium
    else:
        contracts = _float(
            enriched.get("contracts")
            or enriched.get("volume")
            or enriched.get("total_volume")
            or enriched.get("size")
            or enriched.get("quantity")
        )
        premium = _float(
            enriched.get("premium")
            or enriched.get("price")
            or enriched.get("avg_price")
            or enriched.get("last_price")
        )
        enriched["nominal_value"] = contracts * premium * 100
    enriched["is_single_leg"] = is_single_leg(enriched)
    return enriched


def _flow_contract_key(alert: dict) -> str:
    return str(
        alert.get("option_chain")
        or alert.get("contract")
        or alert.get("option_symbol")
        or "|".join(str(alert.get(k, "")) for k in ("ticker", "strike", "expiration", "expiry", "option_type"))
    )


def _group_repeated_flow(alerts: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for alert in alerts:
        groups.setdefault(_flow_contract_key(alert), []).append(_with_nominal_value(alert))

    grouped = []
    for rows in groups.values():
        accumulated = sum(_float(row.get("nominal_value")) for row in rows)
        best = max(rows, key=lambda row: _float(row.get("nominal_value")))
        enriched = dict(best)
        enriched["accumulated_nominal"] = accumulated
        enriched["flow_count"] = len(rows)
        enriched["repeated_flow"] = len(rows) >= 3
        enriched["is_single_leg"] = all(bool(row.get("is_single_leg", True)) for row in rows)
        enriched["nominal_value"] = accumulated
        grouped.append(enriched)

    return sorted(grouped, key=lambda row: _float(row.get("accumulated_nominal")), reverse=True)


def _headers():
    return {
        "Authorization": f"Bearer {UW_TOKEN}",
        "Accept": "application/json",
    }


class UWFetcher:
    """
    Unusual Whales como fuente unica de datos.
    Todos los endpoints necesarios para el motor GBDS.
    """

    # ─── OPTIONS FLOW ────────────────────────────────────────────────────────

    async def get_flow_alerts(self, min_premium: float = 500_000) -> list[dict]:
        """Flow alerts con filtro de premium minimo."""
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{UW_BASE}/option-trades/flow-alerts",
                headers=_headers(),
                params={"limit": 50}
            )
        if r.status_code != 200:
            logger.error(f"flow_alerts error {r.status_code}")
            return []
        data = r.json().get("data", [])
        enriched = [_with_nominal_value(d) for d in data]
        return [
            d for d in enriched
            if _float(d.get("nominal_value")) >= min_premium
        ]

    async def get_ticker_flow(self, ticker: str) -> list[dict]:
        """Flow de opciones para un ticker especifico."""
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{UW_BASE}/option-trades/flow-alerts",
                headers=_headers(),
                params={"ticker": ticker, "limit": 20}
            )
        if r.status_code != 200:
            return []
        return _group_repeated_flow(r.json().get("data", []))

    async def get_oi_change(self, ticker: str) -> dict:
        """
        Compara OI de hoy vs ayer para detectar convicción institucional.
        Usa el endpoint de historic option volume de UW.
        GET /api/stock/{ticker}/option-volume-history
        """
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{UW_BASE}/stock/{ticker}/option-volume-history",
                headers=_headers(),
                params={"limit": 3}
            )
        if r.status_code != 200:
            return {"oi_growing": False, "oi_change_pct": 0, "days_growing": 0}
        
        data = r.json().get("data", [])
        if len(data) < 2:
            return {"oi_growing": False, "oi_change_pct": 0, "days_growing": 0}
        
        # Ordenar por fecha descendente
        sorted_data = sorted(data, key=lambda x: x.get("date", ""), reverse=True)
        
        today_oi = float(sorted_data[0].get("open_interest", 0))
        yesterday_oi = float(sorted_data[1].get("open_interest", 0))
        
        oi_change_pct = ((today_oi - yesterday_oi) / yesterday_oi * 100) if yesterday_oi > 0 else 0
        oi_growing = oi_change_pct > 0
        
        # Contar dias consecutivos creciendo
        days_growing = 0
        for i in range(len(sorted_data) - 1):
            curr = float(sorted_data[i].get("open_interest", 0))
            prev = float(sorted_data[i+1].get("open_interest", 0))
            if curr > prev:
                days_growing += 1
            else:
                break
        
        return {
            "oi_growing": oi_growing,
            "oi_change_pct": round(oi_change_pct, 2),
            "days_growing": days_growing,
            "today_oi": int(today_oi),
            "yesterday_oi": int(yesterday_oi)
        }

    async def get_option_chain_map(self, ticker: str) -> dict:
        """
        Lee el option chain completo y detecta:
        1. Escalera de calls — strikes consecutivos con OI creciente
        2. Gaps en puts — distancia entre strikes con OI significativo
        3. Strike target más probable — donde se concentra el OI de calls
        """
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{UW_BASE}/stock/{ticker}/option-contracts",
                headers=_headers(),
                params={"limit": 100}
            )
        if r.status_code != 200:
            return {}
        
        data = r.json().get("data", [])
        
        calls = [d for d in data if d.get("option_type") == "call"]
        puts = [d for d in data if d.get("option_type") == "put"]
        
        # Ordenar por strike
        calls.sort(key=lambda x: float(x.get("strike", 0)))
        puts.sort(key=lambda x: float(x.get("strike", 0)))
        
        # Detectar escalera en calls
        # Escalera = 3+ strikes consecutivos con OI > 500 cada uno
        ladder_strikes = []
        for call in calls:
            oi = int(call.get("open_interest", 0))
            strike = float(call.get("strike", 0))
            if oi > 500:
                ladder_strikes.append(strike)
        
        has_ladder = len(ladder_strikes) >= 3
        
        # Detectar gaps en puts (distancia > 10% entre strikes con OI)
        put_strikes_with_oi = [float(p.get("strike", 0)) for p in puts if int(p.get("open_interest", 0)) > 200]
        gaps = []
        for i in range(len(put_strikes_with_oi) - 1):
            gap = put_strikes_with_oi[i+1] - put_strikes_with_oi[i]
            if gap > put_strikes_with_oi[i] * 0.08:  # gap > 8% del precio del strike
                gaps.append({"from": put_strikes_with_oi[i], "to": put_strikes_with_oi[i+1], "gap": gap})
        
        # Strike target = call con mayor OI
        top_call = max(calls, key=lambda x: int(x.get("open_interest", 0)), default={})
        target_strike = float(top_call.get("strike", 0)) if top_call else 0
        
        return {
            "has_ladder": has_ladder,
            "ladder_strikes": ladder_strikes[:5],
            "put_gaps": gaps[:3],
            "target_strike": target_strike,
            "call_count_with_oi": len(ladder_strikes),
            "put_strikes_with_oi": put_strikes_with_oi[:5]
        }

    # ─── DARK POOL ───────────────────────────────────────────────────────────

    async def get_dark_pool(self, ticker: str) -> list[dict]:
        """Prints de dark pool para un ticker."""
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{UW_BASE}/darkpool/{ticker}",
                headers=_headers(),
                params={"limit": 20}
            )
        if r.status_code != 200:
            return []
        return r.json().get("data", [])

    async def analyze_dark_pool(self, ticker: str, current_price: float) -> Optional[dict]:
        """
        Analiza dark pool y retorna señal procesada para el scorer.
        Detecta: cluster, absorcion, VWAP position, velocidad.
        """
        prints = await self.get_dark_pool(ticker)
        if not prints:
            return None

        # Filtrar ultimas 2 horas
        recent = []
        now = datetime.utcnow()
        for p in prints:
            try:
                executed = datetime.strptime(
                    p["executed_at"].replace("Z", ""), "%Y-%m-%dT%H:%M:%S"
                )
                hours_ago = (now - executed).total_seconds() / 3600
                if hours_ago <= 2:
                    recent.append(p)
            except:
                recent.append(p)

        if not recent:
            recent = prints[:5]

        total_premium = sum(float(p.get("premium", 0)) for p in recent)
        largest = max(recent, key=lambda p: float(p.get("premium", 0)))
        largest_price = float(largest.get("price", current_price))

        # Cluster: 3+ prints en precio similar (±0.5%)
        prices = [float(p.get("price", 0)) for p in recent]
        cluster = False
        for ref in prices:
            near = [px for px in prices if abs(px - ref) / ref < 0.005]
            if len(near) >= 3:
                cluster = True
                break

        # Absorcion: volumen alto, rango estrecho (bid-ask tight)
        absorption = False
        for p in recent[:3]:
            ask = float(p.get("nbbo_ask", 0))
            bid = float(p.get("nbbo_bid", 0))
            if ask > 0 and bid > 0:
                spread = (ask - bid) / ask
                if spread < 0.001 and float(p.get("premium", 0)) > 200_000:
                    absorption = True
                    break

        # Velocidad: BURST si 3+ prints en < 5 min
        velocity = "STEADY"
        if len(recent) >= 3:
            try:
                t1 = datetime.strptime(recent[0]["executed_at"].replace("Z",""), "%Y-%m-%dT%H:%M:%S")
                t2 = datetime.strptime(recent[2]["executed_at"].replace("Z",""), "%Y-%m-%dT%H:%M:%S")
                if abs((t1 - t2).total_seconds()) < 300:
                    velocity = "BURST"
            except:
                pass

        # Session
        hour = datetime.utcnow().hour - 4  # ET
        if hour < 9 or (hour == 9 and datetime.utcnow().minute < 30):
            session = "PRE"
        elif hour >= 16:
            session = "POST"
        else:
            session = "REGULAR"

        return {
            "print_price":  largest_price,
            "print_size":   total_premium,
            "above_vwap":   largest_price > current_price * 0.999,  # proxy
            "cluster":      cluster,
            "absorption":   absorption,
            "session":      session,
            "velocity":     velocity,
            "total_premium": total_premium,
            "print_count":  len(recent),
        }

    # ─── NET PREMIUM ─────────────────────────────────────────────────────────

    async def get_net_premium(self, ticker: str) -> Optional[dict]:
        """Net premium ticks — indica presion direccional real."""
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{UW_BASE}/stock/{ticker}/net-prem-ticks",
                headers=_headers(),
            )
        if r.status_code != 200:
            return None
        data = r.json().get("data", [])
        if not data:
            return None

        # Ultimas 5 velas para tendencia
        recent = data[-5:]
        net_calls = [float(d.get("net_call_premium", 0)) for d in recent]
        net_puts  = [float(d.get("net_put_premium", 0)) for d in recent]
        net_delta = [float(d.get("net_delta", 0)) for d in recent]

        latest = recent[-1]
        call_prem = float(latest.get("net_call_premium", 0))
        put_prem  = float(latest.get("net_put_premium", 0))

        # Tendencia: calls subiendo = bullish pressure
        call_trend = net_calls[-1] - net_calls[0] if len(net_calls) > 1 else 0
        put_trend  = net_puts[-1]  - net_puts[0]  if len(net_puts) > 1 else 0

        return {
            "net_call_premium":  call_prem,
            "net_put_premium":   put_prem,
            "net_delta":         float(latest.get("net_delta", 0)),
            "call_trend":        call_trend,
            "put_trend":         put_trend,
            "bullish_pressure":  call_prem > 0 and call_trend > 0,
            "bearish_pressure":  put_prem < 0 and put_trend < 0,
            "call_volume":       latest.get("call_volume", 0),
            "put_volume":        latest.get("put_volume", 0),
        }

    # ─── GEX / GREEKS ────────────────────────────────────────────────────────

    async def get_gex(self, ticker: str) -> Optional[dict]:
        """Gamma exposure — detecta si dealers amplifican o amortiguan moves."""
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{UW_BASE}/stock/{ticker}/greek-exposure",
                headers=_headers(),
            )
        if r.status_code != 200:
            return None
        data = r.json().get("data", [])
        if not data:
            return None

        latest = data[-1]
        call_gamma = float(latest.get("call_gamma", 0))
        put_gamma  = float(latest.get("put_gamma", 0))
        net_gex    = call_gamma + put_gamma

        return {
            "net_gex":     net_gex,
            "call_gamma":  call_gamma,
            "put_gamma":   put_gamma,
            "call_delta":  float(latest.get("call_delta", 0)),
            "put_delta":   float(latest.get("put_delta", 0)),
            "call_vanna":  float(latest.get("call_vanna", 0)),
            "put_vanna":   float(latest.get("put_vanna", 0)),
            "gex_positive": net_gex > 0,  # True = dealers amortiguan volatilidad
        }

    # ─── SCREENER ────────────────────────────────────────────────────────────

    async def get_screener(self, limit: int = 30) -> list[dict]:
        """
        Stock screener — retorna tickers con actividad inusual.
        Filtra por volumen de opciones y premium inusual.
        """
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{UW_BASE}/screener/stocks",
                headers=_headers(),
                params={"limit": limit}
            )
        if r.status_code != 200:
            return []
        return r.json().get("data", [])

    async def get_active_tickers(self) -> list[str]:
        """
        Retorna lista de tickers con mayor actividad institucional hoy.
        Reemplaza el watchlist hardcoded.
        """
        data = await self.get_screener(limit=50)
        if not data:
            return ["SPY", "QQQ", "NVDA", "AAPL", "TSLA", "MSFT", "AMZN", "META"]

        # Ordenar por premium total de opciones
        sorted_data = sorted(
            data,
            key=lambda x: float(x.get("call_premium", 0)) + float(x.get("bearish_premium", 0)),
            reverse=True
        )

        # Top 15 tickers con mayor actividad, excluyendo indices
        exclude = {"SPXW", "SPX", "VIX", "NDX", "RUT"}
        tickers = []
        for item in sorted_data:
            ticker = item.get("ticker", "")
            if ticker and ticker not in exclude:
                tickers.append(ticker)
            if len(tickers) >= 15:
                break

        return tickers if tickers else ["SPY", "QQQ", "NVDA", "AAPL", "TSLA"]

    # ─── MARKET TIDE ─────────────────────────────────────────────────────────

    async def get_market_tide(self) -> Optional[dict]:
        """
        Market Tide — direccion del mercado en tiempo real.
        Net call/put premium del mercado total.
        """
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{UW_BASE}/market/market-tide",
                headers=_headers(),
            )
        if r.status_code != 200:
            return None
        data = r.json().get("data", [])
        if not data:
            return None

        # Ultimas 3 velas para tendencia
        recent = data[-3:]
        latest = recent[-1]

        net_call = float(latest.get("net_call_premium", 0))
        net_put  = float(latest.get("net_put_premium", 0))
        net_vol  = float(latest.get("net_volume", 0))

        # Tendencia de los ultimos periodos
        if len(recent) >= 2:
            prev_call = float(recent[-2].get("net_call_premium", 0))
            call_improving = net_call > prev_call
        else:
            call_improving = net_call > 0

        market_direction = "BULLISH" if net_call > 0 and net_vol > 0 else \
                          "BEARISH" if net_put > 0 and net_vol < 0 else "NEUTRAL"

        return {
            "net_call_premium":  net_call,
            "net_put_premium":   net_put,
            "net_volume":        net_vol,
            "market_direction":  market_direction,
            "call_improving":    call_improving,
            "bullish":           market_direction == "BULLISH",
        }

    # ─── PRECIO (via screener data) ──────────────────────────────────────────

    async def get_ticker_data(self, ticker: str) -> Optional[dict]:
        """Datos basicos del ticker via screener."""
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{UW_BASE}/screener/stocks",
                headers=_headers(),
                params={"ticker": ticker, "limit": 1}
            )
        if r.status_code != 200:
            return None
        data = r.json().get("data", [])
        if not data:
            return None

        d = data[0]
        return {
            "ticker":          d.get("ticker"),
            "prev_close":      float(d.get("prev_close", 0)),
            "iv_rank":         float(d.get("iv_rank", 50)),
            "iv30d":           float(d.get("iv30d", 0)),
            "put_call_ratio":  float(d.get("put_call_ratio", 1)),
            "call_premium":    float(d.get("call_premium", 0)),
            "bearish_premium": float(d.get("bearish_premium", 0)),
            "net_call_prem":   float(d.get("net_call_premium", 0)),
            "total_oi":        int(d.get("total_open_interest", 0)),
            "call_volume":     int(d.get("call_volume", 0)),
            "gex_change":      float(d.get("gex_net_change", 0)),
        }

    # ─── EARNINGS ────────────────────────────────────────────────────────────

    async def get_earnings_dte(self, ticker: str) -> int:
        """Dias hasta earnings. Retorna 99 si no hay datos."""
        try:
            flow = await self.get_ticker_flow(ticker)
            for f in flow[:5]:
                er_time = f.get("er_time") or f.get("next_earnings_date")
                if er_time:
                    er_date = datetime.strptime(er_time[:10], "%Y-%m-%d").date()
                    dte = (er_date - date.today()).days
                    return max(dte, 0)
        except:
            pass
        return 99
