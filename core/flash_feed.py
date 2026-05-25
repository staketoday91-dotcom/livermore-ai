"""
Flash feed — poll global Unusual Whales (option-contract screener).

Replica el preset web de Jorge (500K OTM, ask-side, vol>OI, etc.)
y aplica regla direccional: mismo ticker con calls Y puts inusuales el mismo día → descartar.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

import pytz

from core.uw_fetcher import (
    UWFetcher,
    _OCC_PARTS_RE,
    _float,
    _group_repeated_flow,
    _with_nominal_value,
    contract_ticker,
    normalize_occ_contract,
)

logger = logging.getLogger("livermore.flash")
NY_TZ = pytz.timezone("America/New_York")


def occ_option_type(contract: str) -> str:
    """C o P desde símbolo OCC."""
    match = _OCC_PARTS_RE.match((contract or "").strip().upper())
    return match.group(3) if match else ""


def normalize_screener_row(item: dict) -> dict:
    """Convierte fila de /screener/option-contracts al shape de flow-alerts."""
    raw = dict(item)
    contract = normalize_occ_contract(
        {
            "option_symbol": item.get("option_symbol") or item.get("option_chain"),
            "option_chain": item.get("option_chain"),
            "contract": item.get("contract"),
        }
    )
    ticker = (
        str(item.get("ticker_symbol") or item.get("ticker") or "").upper()
        or contract_ticker(contract)
    )

    volume = int(_float(item.get("volume")))
    oi = int(_float(item.get("open_interest")))
    premium = _float(item.get("premium") or item.get("total_premium"))
    ask_vol = _float(item.get("ask_side_volume"))
    bid_vol = _float(item.get("bid_side_volume"))
    mid_vol = _float(item.get("mid_volume"))
    side_total = max(ask_vol + bid_vol + mid_vol, 1.0)
    ask_pct = (ask_vol / side_total) * 100.0 if side_total else 0.0

    multileg = _float(item.get("multileg_volume") or item.get("stock_multi_leg_volume"))
    multileg_ratio = multileg / max(volume, 1)

    row = {
        "ticker": ticker,
        "option_chain": contract,
        "option_symbol": contract,
        "total_premium": premium,
        "premium": premium,
        "volume": volume,
        "open_interest": oi,
        "total_ask_side_prem": ask_vol * _float(item.get("avg_price") or item.get("price")) * 100
        if ask_vol and not item.get("total_ask_side_prem")
        else _float(item.get("total_ask_side_prem"), premium * (ask_pct / 100.0)),
        "ask_side_pct": ask_pct,
        "total_ask_side_pct": ask_pct,
        "has_sweep": bool(item.get("sweep_volume") or item.get("has_sweep")),
        "has_floor": bool(item.get("floor_volume") or item.get("has_floor")),
        "tags": item.get("tags", ""),
        "trade_type": item.get("trade_type", ""),
        "created_at": item.get("last_fill") or item.get("created_at"),
        "delta": item.get("delta"),
        "greeks": item.get("greeks"),
        "source": "uw_option_screener",
        "raw_screener": raw,
    }
    if volume and oi:
        row["volume_oi_ratio"] = volume / oi
    return _with_nominal_value(row)


def filter_directional_universe(rows: list[dict]) -> list[dict]:
    """
    Descarta tickers con actividad inusual en calls Y puts el mismo día (NY).
    Solo pasa universo con convicción direccional (solo C o solo P por ticker).
    """
    by_ticker: dict[str, set[str]] = {}
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        cp = occ_option_type(normalize_occ_contract(row))
        if cp in ("C", "P"):
            by_ticker.setdefault(ticker, set()).add(cp)

    mixed = {t for t, sides in by_ticker.items() if "C" in sides and "P" in sides}
    if mixed:
        sample = ", ".join(sorted(mixed)[:12])
        extra = f" (+{len(mixed) - 12} más)" if len(mixed) > 12 else ""
        logger.info(
            "Flash direccional: descartados %d tickers con calls+puts mismo día: %s%s",
            len(mixed),
            sample,
            extra,
        )

    return [r for r in rows if str(r.get("ticker") or "").upper() not in mixed]


def infer_direction_from_flows(flows: list[dict]) -> Optional[str]:
    """BULLISH | BEARISH si todos los contratos son C o P; None si ambiguo."""
    sides: set[str] = set()
    for f in flows:
        cp = occ_option_type(normalize_occ_contract(f))
        if cp in ("C", "P"):
            sides.add(cp)
    if sides == {"C"}:
        return "BULLISH"
    if sides == {"P"}:
        return "BEARISH"
    return None


async def poll_flash_universe(fetcher: Optional[UWFetcher] = None) -> list[dict]:
    """
    Poll global UW option-contract screener → normaliza → filtro direccional
    → agrupa por contrato OCC (accumulated_nominal, flow_count).
    """
    uw = fetcher or UWFetcher()
    raw = await uw.get_jorge_option_screener()
    if not raw:
        logger.warning("Flash screener vacío — sin candidatos")
        return []

    normalized: list[dict] = []
    for r in raw:
        row = normalize_screener_row(r)
        if row.get("ticker"):
            normalized.append(row)
    directional = filter_directional_universe(normalized)
    grouped = _group_repeated_flow(directional)
    logger.info(
        "Flash poll: %d filas UW → %d tras direccional → %d contratos agrupados",
        len(raw),
        len(directional),
        len(grouped),
    )
    return grouped


def tickers_from_flash(grouped_flows: list[dict], limit: int) -> list[str]:
    """Tickers únicos ordenados por mayor nominal acumulado."""
    by_ticker: dict[str, float] = {}
    for row in grouped_flows:
        t = str(row.get("ticker") or contract_ticker(normalize_occ_contract(row))).upper()
        if not t:
            continue
        nom = _float(row.get("accumulated_nominal") or row.get("nominal_value"))
        by_ticker[t] = max(by_ticker.get(t, 0.0), nom)
    ordered = sorted(by_ticker.items(), key=lambda x: x[1], reverse=True)
    return [t for t, _ in ordered[:limit]]


def flows_for_ticker(grouped_flows: list[dict], ticker: str) -> list[dict]:
    ticker = ticker.upper()
    return [
        f
        for f in grouped_flows
        if str(f.get("ticker") or "").upper() == ticker
        or contract_ticker(normalize_occ_contract(f)) == ticker
    ]
