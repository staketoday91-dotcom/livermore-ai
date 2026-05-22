from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any, Optional

import httpx

from antigravity.config import get_settings
from antigravity.db import RawUwEvent, session_scope

logger = logging.getLogger("antigravity.uw")
_OCC_RE = re.compile(r"^([A-Z]+)\d{6}[CP]\d{8}$")

ALLOWED_ENDPOINT_PATTERNS = (
    re.compile(r"^option-trades/flow-alerts$"),
    re.compile(r"^screener/option-contracts$"),
    re.compile(r"^stock/[A-Za-z0-9.\-]+/flow-recent$"),
    re.compile(r"^darkpool/recent$"),
    re.compile(r"^darkpool/[A-Za-z0-9.\-]+$"),
    re.compile(r"^market/market-tide$"),
    re.compile(r"^stock/[A-Za-z0-9.\-]+/net-prem-ticks$"),
    re.compile(r"^stock/[A-Za-z0-9.\-]+/option-contracts$"),
    re.compile(r"^stock/[A-Za-z0-9.\-]+/option-chains$"),
    re.compile(r"^stock/[A-Za-z0-9.\-]+/greeks$"),
    re.compile(r"^stock/[A-Za-z0-9.\-]+/greek-exposure/strike$"),
    re.compile(r"^stock/[A-Za-z0-9.\-]+/spot-exposures/strike$"),
    re.compile(r"^stock/[A-Za-z0-9.\-]+/interpolated-iv$"),
    re.compile(r"^stock/[A-Za-z0-9.\-]+/options-volume$"),
    re.compile(r"^insider/transactions$"),
    re.compile(r"^congress/recent-trades$"),
    re.compile(r"^news/headlines$"),
    re.compile(r"^stock/[A-Za-z0-9.\-]+/financials$"),
    re.compile(r"^stock/[A-Za-z0-9.\-]+/income-statements$"),
    re.compile(r"^stock/[A-Za-z0-9.\-]+/balance-sheets$"),
    re.compile(r"^stock/[A-Za-z0-9.\-]+/cash-flows$"),
    re.compile(r"^stock/[A-Za-z0-9.\-]+/earnings$"),
    re.compile(r"^stock/[A-Za-z0-9.\-]+/technical-indicator/[A-Za-z0-9_\-]+$"),
)


class UnusualWhalesError(RuntimeError):
    pass


class UnusualWhalesAuthError(UnusualWhalesError):
    pass


class UnusualWhalesRateLimitError(UnusualWhalesError):
    pass


class UnusualWhalesEndpointError(UnusualWhalesError):
    pass


@dataclass
class UwResponse:
    endpoint: str
    status_code: int
    data: list[dict[str, Any]]
    raw_payload: dict[str, Any]
    headers: dict[str, str]


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def parse_occ_details(contract: str) -> dict[str, Any]:
    match = _OCC_RE.match((contract or "").strip().upper())
    if not match:
        return {}

    ticker = match.group(1)
    expiry_raw = contract[len(ticker) : len(ticker) + 6]
    option_type = contract[len(ticker) + 6]
    strike_raw = contract[-8:]

    try:
        expiry = datetime.strptime(expiry_raw, "%y%m%d").date()
    except ValueError:
        expiry = None

    return {
        "ticker": ticker,
        "contract_type": "CALL" if option_type == "C" else "PUT",
        "expiry": expiry,
        "strike": to_float(strike_raw) / 1000,
    }


def normalize_occ_contract(item: dict[str, Any]) -> str:
    for key in ("option_chain", "option_symbol", "contract", "symbol"):
        raw = str(item.get(key) or "").strip().upper().replace(" ", "")
        if _OCC_RE.match(raw):
            return raw
    return ""


def normalize_flow_item(item: dict[str, Any]) -> dict[str, Any]:
    contract = normalize_occ_contract(item)
    occ = parse_occ_details(contract)
    ticker = (
        item.get("ticker")
        or item.get("ticker_symbol")
        or item.get("underlying_symbol")
        or item.get("symbol")
        or ""
    )
    if occ.get("ticker"):
        ticker = occ["ticker"]

    side = str(item.get("side") or item.get("sale_cond_code") or "").upper()
    ask_side_premium = to_float(item.get("total_ask_side_prem") or item.get("ask_side_premium"))
    bid_side_premium = to_float(item.get("total_bid_side_prem") or item.get("bid_side_premium"))
    ask_pct = to_float(item.get("ask_side_pct") or item.get("total_ask_side_pct"))
    if ask_pct == 0 and (ask_side_premium or bid_side_premium):
        ask_pct = ask_side_premium / max(ask_side_premium + bid_side_premium, 1)
    if not side and ask_pct >= 0.7:
        side = "ASK"
    elif not side and bid_side_premium > ask_side_premium:
        side = "BID"

    volume = to_int(item.get("volume") or item.get("total_size") or item.get("total_volume") or item.get("size") or item.get("contracts"))
    open_interest = to_int(item.get("open_interest"))
    premium = to_float(item.get("total_premium") or item.get("premium") or item.get("notional_value"))
    if premium == 0:
        premium = volume * to_float(item.get("price") or item.get("avg_price") or item.get("last_price")) * 100
    underlying_price = to_float(item.get("underlying_price") or item.get("stock_price") or item.get("marketcap"))

    is_call = item.get("is_call")
    contract_type = (
        "CALL"
        if is_call is True
        else "PUT"
        if is_call is False
        else str(item.get("type") or item.get("option_type") or occ.get("contract_type") or "").upper()
    )
    if contract_type == "CALLS":
        contract_type = "CALL"
    if contract_type == "PUTS":
        contract_type = "PUT"
    if contract_type == "CALL":
        contract_type = "CALL"
    if contract_type == "PUT":
        contract_type = "PUT"

    execution_type = str(item.get("execution_type") or item.get("trade_code") or item.get("alert_rule") or item.get("trade_type") or "FLOW_ALERT")
    tags = str(item.get("tags") or "").lower()
    has_singleleg = item.get("has_singleleg")
    has_multileg = item.get("has_multileg")
    if has_singleleg is not None:
        is_single_leg = bool(has_singleleg)
    elif has_multileg is not None:
        is_single_leg = not bool(has_multileg)
    else:
        is_single_leg = not any(word in tags or word in execution_type.lower() for word in ("spread", "condor", "butterfly", "straddle", "strangle", "multi"))
    volume_oi_ratio = (volume / open_interest) if open_interest > 0 else 0
    oi_broken = volume > open_interest > 0

    score = 0
    if "ASK" in side or ask_pct >= 0.7:
        score += 25
    if oi_broken:
        score += 30
    if premium >= 100_000:
        score += 15
    if premium >= 500_000:
        score += 10
    if is_single_leg:
        score += 10
    if execution_type.upper() in {"ISO", "ISOI", "AUTO", "SINGLE LEG"}:
        score += 10

    return {
        "uw_alert_id": str(item.get("id") or "").strip() or None,
        "ticker": str(ticker).upper(),
        "contract_symbol": contract,
        "contract_type": contract_type or "UNKNOWN",
        "strike": to_float(item.get("strike")) or occ.get("strike"),
        "expiry": parse_date(item.get("expiry") or item.get("expiration")) or occ.get("expiry"),
        "tape_time": parse_datetime(item.get("created_at") or item.get("time") or item.get("executed_at")) or datetime.utcnow(),
        "side": side or "UNKNOWN",
        "execution_type": execution_type,
        "volume": volume,
        "open_interest": open_interest,
        "premium": premium,
        "underlying_price": underlying_price or None,
        "ask_side_pct": ask_pct,
        "volume_oi_ratio": volume_oi_ratio,
        "oi_broken": oi_broken,
        "is_single_leg": is_single_leg,
        "score": min(score, 100),
        "raw": item,
    }


def normalize_screener_item(item: dict[str, Any]) -> dict[str, Any]:
    contract = str(item.get("option_symbol") or "").strip().upper().replace(" ", "")
    occ = parse_occ_details(contract)
    ticker = str(item.get("ticker_symbol") or occ.get("ticker") or "").upper()
    volume = to_int(item.get("volume"))
    open_interest = to_int(item.get("open_interest"))
    ask_volume = to_int(item.get("ask_side_volume"))
    bid_volume = to_int(item.get("bid_side_volume"))
    mid_volume = to_int(item.get("mid_volume"))
    ask_pct = ask_volume / max(ask_volume + bid_volume + mid_volume, 1)
    premium = to_float(item.get("premium"))
    underlying_price = to_float(item.get("stock_price") or item.get("underlying_price"))
    multileg_volume = to_int(item.get("multileg_volume") or item.get("stock_multi_leg_volume"))
    multileg_ratio = multileg_volume / max(volume, 1)
    volume_oi_ratio = (volume / open_interest) if open_interest > 0 else volume
    oi_broken = volume > open_interest
    is_single_leg = multileg_ratio <= 0.1

    score = 0
    if ask_pct >= 0.7:
        score += 25
    if oi_broken:
        score += 30
    if premium >= 100_000:
        score += 15
    if premium >= 500_000:
        score += 10
    if is_single_leg:
        score += 10
    if to_int(item.get("floor_volume")) > 0 or to_int(item.get("sweep_volume")) > 0:
        score += 5
    if to_int(item.get("days_of_vol_greater_than_oi")) >= 1:
        score += 5

    return {
        "ticker": ticker,
        "contract_symbol": contract,
        "contract_type": occ.get("contract_type") or "UNKNOWN",
        "strike": occ.get("strike"),
        "expiry": occ.get("expiry"),
        "tape_time": parse_datetime(item.get("last_fill")) or datetime.utcnow(),
        "side": "ASK" if ask_pct >= 0.7 else "BID" if bid_volume > ask_volume else "MIXED",
        "execution_type": "SCREENER_AUTO_ISOI_PROXY",
        "volume": volume,
        "open_interest": open_interest,
        "premium": premium,
        "underlying_price": underlying_price or None,
        "ask_side_pct": ask_pct,
        "volume_oi_ratio": volume_oi_ratio,
        "oi_broken": oi_broken,
        "is_single_leg": is_single_leg,
        "score": min(score, 100),
        "raw": item,
    }


class UnusualWhalesClient:
    """Single gateway for all Unusual Whales calls."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._blocked_until = 0.0

    @property
    def headers(self) -> dict[str, str]:
        token = self.settings.unusual_whales_token.strip()
        if token.startswith("api-"):
            token = token[4:]
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if self.settings.uw_client_api_id:
            headers["UW-CLIENT-API-ID"] = self.settings.uw_client_api_id
        return headers

    def request(self, endpoint: str, params: Optional[dict[str, Any]] = None, symbol: Optional[str] = None) -> UwResponse:
        now = time.time()
        if now < self._blocked_until:
            raise UnusualWhalesRateLimitError("Unusual Whales client is in rate-limit backoff")

        endpoint = endpoint.lstrip("/")
        if not self._is_allowed_endpoint(endpoint):
            raise UnusualWhalesEndpointError(f"Endpoint is not in the Unusual Whales whitelist: /api/{endpoint}")

        url = f"{self.settings.uw_base_url.rstrip('/')}/{endpoint}"
        params = params or {}

        with httpx.Client(timeout=20) as client:
            response = client.get(url, headers=self.headers, params=params)

        try:
            payload = response.json()
        except ValueError:
            payload = {"data": [], "text": response.text}

        self._persist_raw(endpoint, symbol, response.status_code, payload, response.headers, params)

        if response.status_code == 401:
            raise UnusualWhalesAuthError(payload.get("message", "Unusual Whales authentication failed"))
        if response.status_code == 429:
            self._blocked_until = time.time() + self.settings.daily_limit_backoff_seconds
            raise UnusualWhalesRateLimitError(payload.get("message", "Unusual Whales rate limit reached"))
        if response.status_code >= 400:
            raise UnusualWhalesError(f"Unusual Whales error {response.status_code}: {payload}")

        data = payload.get("data", [])
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            data = []

        return UwResponse(endpoint=endpoint, status_code=response.status_code, data=data, raw_payload=payload, headers=dict(response.headers))

    @staticmethod
    def _is_allowed_endpoint(endpoint: str) -> bool:
        return any(pattern.match(endpoint) for pattern in ALLOWED_ENDPOINT_PATTERNS)

    def _persist_raw(
        self,
        endpoint: str,
        symbol: Optional[str],
        status_code: int,
        payload: dict[str, Any],
        headers: httpx.Headers,
        params: dict[str, Any],
    ) -> None:
        try:
            with session_scope() as session:
                session.add(
                    RawUwEvent(
                        endpoint=endpoint,
                        symbol=(symbol or "").upper() or None,
                        event_type="uw_response",
                        status_code=status_code,
                        payload=payload,
                        response_headers={
                            "x-uw-daily-req-count": headers.get("x-uw-daily-req-count"),
                            "x-uw-token-req-limit": headers.get("x-uw-token-req-limit"),
                        },
                        request_params=params,
                    )
                )
        except Exception as exc:
            logger.warning("Could not persist raw UW response: %s", exc)

    def get_flow_alerts(self, limit: int = 150, min_premium: Optional[float] = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if min_premium is not None:
            params["min_premium"] = min_premium
        response = self.request("option-trades/flow-alerts", params=params)
        return response.data

    def get_option_contract_screener(self, limit: int = 100, min_premium: Optional[float] = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "limit": limit,
            "min_ask_perc": 0.7,
            "vol_greater_oi": True,
            "max_multileg_volume_ratio": 0.1,
            "issue_types[]": ["Common Stock", "ADR", "ETF"],
        }
        if min_premium is not None:
            params["min_premium"] = min_premium
        response = self.request("screener/option-contracts", params=params)
        return response.data

    def get_recent_flow_for_ticker(self, ticker: str, limit: int = 50) -> list[dict[str, Any]]:
        return self.request(f"stock/{ticker.lower()}/flow-recent", params={"limit": limit}, symbol=ticker).data

    def get_market_tide(self) -> list[dict[str, Any]]:
        return self.request("market/market-tide").data

    def get_gex_by_strike(self, ticker: str) -> list[dict[str, Any]]:
        return self.request(f"stock/{ticker.lower()}/spot-exposures/strike", symbol=ticker).data

    def get_dark_pool(self, ticker: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.request(f"darkpool/{ticker.upper()}", params={"limit": limit}, symbol=ticker).data

    def get_option_chain(self, ticker: str, expiry: Optional[str] = None) -> list[dict[str, Any]]:
        params = {"expiry": expiry} if expiry else {}
        return self.request(f"stock/{ticker.lower()}/option-chains", params=params, symbol=ticker).data

