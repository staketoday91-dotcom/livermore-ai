"""
Backfill historico desde Unusual Whales para senales BACKTEST.
"""
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from core.models import Alert, Base, engine, SessionLocal  # noqa: E402
from core.scorer import DarkPoolSignal, LivermoreScorer, OptionsFlowSignal, MacroContext  # noqa: E402

UW_BASE = "https://api.unusualwhales.com/api"
UW_TOKEN = os.getenv("UNUSUAL_WHALES_TOKEN", "")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {UW_TOKEN}",
        "Accept": "application/json",
    }


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _int(value, default: int = 0) -> int:
    try:
        return int(float(value or default))
    except (TypeError, ValueError):
        return default


def _bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _pick(data: dict, *keys, default=None):
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


def _ticker(data: dict) -> str:
    return str(_pick(data, "ticker", "underlying_symbol", "symbol", default="")).upper()


def _contract(data: dict) -> str:
    direct = _pick(data, "option_chain", "contract", "option_symbol", "symbol", default="")
    if direct:
        return str(direct)

    ticker = _ticker(data)
    strike = _pick(data, "strike", "strike_price", default="")
    expiry = _pick(data, "expiration", "expiry", "expiry_date", "expiration_date", default="")
    option_type = str(_pick(data, "option_type", "type", "call_put", default="")).upper()
    return " ".join(str(v) for v in (ticker, strike, option_type, expiry) if v)


def _alert_date(data: dict) -> str | None:
    raw = _pick(data, "created_at", "executed_at", "date", default=None)
    if not raw:
        return None
    return str(raw)[:10]


def _direction(data: dict) -> str:
    option_type = str(_pick(data, "option_type", "type", "call_put", default="")).lower()
    sentiment = str(_pick(data, "sentiment", "side", "direction", default="")).lower()
    if "put" in option_type or "bear" in sentiment:
        return "BEARISH"
    return "BULLISH"


def _nominal_value(data: dict) -> float:
    total_premium = _float(_pick(data, "total_premium", default=0))
    if total_premium > 0:
        return total_premium

    contracts = _float(_pick(data, "contracts", "volume", "total_volume", "size", "quantity", default=0))
    premium = _float(_pick(data, "premium", "price", "avg_price", "last_price", default=0))
    return contracts * premium * 100


async def fetch_dark_pool(client: httpx.AsyncClient, ticker: str) -> list[dict]:
    response = await client.get(
        f"{UW_BASE}/darkpool/{ticker}",
        headers=_headers(),
        params={"limit": 20},
    )
    if response.status_code != 200:
        return []
    payload = response.json()
    return payload.get("data", payload if isinstance(payload, list) else [])


async def fetch_option_historic(client: httpx.AsyncClient, contract: str) -> list[dict]:
    if not contract:
        return []
    response = await client.get(
        f"{UW_BASE}/option-contract/{contract}/historic",
        headers=_headers(),
    )
    if response.status_code != 200:
        return []
    payload = response.json()
    return payload.get("chains", payload.get("data", payload if isinstance(payload, list) else []))


async def fetch_oi_change(client: httpx.AsyncClient, ticker: str) -> dict:
    response = await client.get(
        f"{UW_BASE}/stock/{ticker}/option-volume-history",
        headers=_headers(),
        params={"limit": 3},
    )
    if response.status_code != 200:
        return {"oi_growing": False, "oi_change_pct": 0, "days_growing": 0}

    data = response.json().get("data", [])
    if len(data) < 2:
        return {"oi_growing": False, "oi_change_pct": 0, "days_growing": 0}

    sorted_data = sorted(data, key=lambda x: x.get("date", ""), reverse=True)
    today_oi = _float(sorted_data[0].get("open_interest", 0))
    yesterday_oi = _float(sorted_data[1].get("open_interest", 0))
    oi_change_pct = ((today_oi - yesterday_oi) / yesterday_oi * 100) if yesterday_oi > 0 else 0

    days_growing = 0
    for i in range(len(sorted_data) - 1):
        curr = _float(sorted_data[i].get("open_interest", 0))
        prev = _float(sorted_data[i + 1].get("open_interest", 0))
        if curr > prev:
            days_growing += 1
        else:
            break

    return {
        "oi_growing": oi_change_pct > 0,
        "oi_change_pct": round(oi_change_pct, 2),
        "days_growing": days_growing,
        "today_oi": int(today_oi),
        "yesterday_oi": int(yesterday_oi),
    }


def _price_from_historic(row: dict) -> float:
    return _float(_pick(row, "last_price", "close", "avg_price", "price", default=0))


def _result_from_prices(data: dict, historic: list[dict]) -> tuple[str, float | None]:
    entry_price = _float(_pick(data, "price", "avg_price", "last_price", default=0))
    alert_date = _alert_date(data)

    if not entry_price and alert_date:
        for row in historic:
            if str(row.get("date", ""))[:10] == alert_date:
                entry_price = _price_from_historic(row)
                break

    valid_rows = [row for row in historic if _price_from_historic(row) > 0]
    if not entry_price or not valid_rows:
        return "pending", None

    latest = max(valid_rows, key=lambda row: str(_pick(row, "date", "last_tape_time", default="")))
    current_price = _price_from_historic(latest)
    pnl_pct = round(((current_price - entry_price) / entry_price) * 100, 2)

    if pnl_pct > 20:
        return "win", pnl_pct
    if pnl_pct < -20:
        return "loss", pnl_pct
    return "pending", pnl_pct


def _dark_pool_signal(rows: list[dict], current_price: float) -> DarkPoolSignal | None:
    if not rows:
        return None

    premiums = [_float(_pick(row, "premium", "total_premium", "size", "notional", default=0)) for row in rows]
    total_premium = sum(premiums)
    if total_premium <= 0:
        return None

    largest = max(rows, key=lambda row: _float(_pick(row, "premium", "total_premium", "size", "notional", default=0)))
    largest_price = _float(_pick(largest, "price", "executed_price", default=current_price), current_price)
    prices = [_float(_pick(row, "price", "executed_price", default=0)) for row in rows]
    prices = [price for price in prices if price > 0]

    cluster = False
    for ref in prices:
        near = [price for price in prices if abs(price - ref) / ref < 0.005]
        if len(near) >= 3:
            cluster = True
            break

    absorption = False
    for row in rows[:5]:
        ask = _float(_pick(row, "nbbo_ask", "ask", default=0))
        bid = _float(_pick(row, "nbbo_bid", "bid", default=0))
        premium = _float(_pick(row, "premium", "total_premium", "size", "notional", default=0))
        if ask > 0 and bid > 0 and premium > 200_000:
            spread = (ask - bid) / ask
            if spread < 0.0015:
                absorption = True
                break

    return DarkPoolSignal(
        print_price=largest_price,
        print_size=total_premium,
        above_vwap=largest_price >= current_price * 0.995 if current_price else True,
        cluster=cluster,
        absorption=absorption,
        session="BACKTEST",
        velocity="BURST" if len(rows) >= 3 else "STEADY",
    )


def _score_backtest(data: dict, dark_pool: DarkPoolSignal | None, oi_data: dict):
    nominal_value = _nominal_value(data)
    volume = _int(_pick(data, "volume", "total_volume", default=0))
    open_interest = max(_int(_pick(data, "open_interest", "oi", default=1), 1), 1)
    vol_oi = _float(_pick(data, "volume_oi_ratio", "vol_oi_ratio", default=volume / open_interest))
    ask_premium = _float(_pick(data, "total_ask_side_prem", "ask_side_premium", default=nominal_value))
    executed_ask = ask_premium / nominal_value if nominal_value > 0 else 0
    is_sweep = _bool(_pick(data, "has_sweep", "is_sweep", "sweep", default=False))
    is_floor = _bool(_pick(data, "has_floor", "floor", default=False))
    delta = abs(_float(_pick(data, "delta", default=0.5), 0.5))
    iv_rank = _float(_pick(data, "iv_rank", default=50), 50)
    dte = _int(_pick(data, "dte", "days_to_expiration", default=30), 30)
    direction = _direction(data)

    icc_score = 25
    if nominal_value >= 500_000:
        icc_score += 5
    if executed_ask >= 0.70:
        icc_score += 5

    options = OptionsFlowSignal(
        volume=volume,
        open_interest=open_interest,
        vol_oi_ratio=vol_oi,
        executed_ask=executed_ask,
        nominal_value=nominal_value,
        is_sweep=is_sweep,
        is_golden_sweep=(is_sweep or is_floor) and nominal_value >= 10_000_000,
        delta=delta if delta > 0 else 0.5,
        iv_rank=iv_rank,
        expiration_dte=dte,
        contract=_contract(data),
    )
    macro = MacroContext(market_session="BACKTEST", vix_level=15.0)

    result = LivermoreScorer().score(
        ticker=_ticker(data),
        icc_score=icc_score,
        icc_direction=direction,
        entry_price=_float(_pick(data, "underlying_price", "spot_price", "price", default=0)),
        stop_loss=0,
        target1=0,
        target2=0,
        dark_pool=dark_pool,
        options_flow=options,
        macro=macro,
        adx=25.0,
        regime="BACKTEST_TRENDING",
        oi_data=oi_data,
    )
    return result, nominal_value, direction, options


def _tier_num(score: int) -> int:
    if score >= 95:
        return 3
    if score >= 85:
        return 2
    return 1


async def fetch_flow_alerts() -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{UW_BASE}/option-trades/flow-alerts",
            headers=_headers(),
            params={"limit": 100},
        )
    response.raise_for_status()
    payload = response.json()
    return payload.get("data", payload if isinstance(payload, list) else [])


async def main():
    if not UW_TOKEN:
        raise RuntimeError("UNUSUAL_WHALES_TOKEN no configurado")

    Base.metadata.create_all(bind=engine)
    rows = await fetch_flow_alerts()
    loaded = 0
    max_score = 0
    dark_pool_cache: dict[str, list[dict]] = {}
    historic_cache: dict[str, list[dict]] = {}
    oi_cache: dict[str, dict] = {}

    async with httpx.AsyncClient(timeout=30) as client:
        for row in rows:
            ticker = _ticker(row)
            if ticker and ticker not in dark_pool_cache:
                dark_pool_cache[ticker] = await fetch_dark_pool(client, ticker)
            if ticker and ticker not in oi_cache:
                oi_cache[ticker] = await fetch_oi_change(client, ticker)
            contract = _contract(row)
            if contract and contract not in historic_cache:
                historic_cache[contract] = await fetch_option_historic(client, contract)

    db = SessionLocal()
    try:
        deleted = db.query(Alert).filter(Alert.mode == "BACKTEST").delete(synchronize_session=False)
        db.commit()
        print(f"Backtest previo borrado: {deleted} alertas")

        for row in rows:
            nominal_value = _nominal_value(row)
            if nominal_value < 500_000:
                continue

            ticker = _ticker(row)
            if not ticker:
                continue

            current_price = _float(_pick(row, "underlying_price", "spot_price", "price", default=0))
            dark_pool = _dark_pool_signal(dark_pool_cache.get(ticker, []), current_price)
            oi_data = oi_cache.get(ticker, {"oi_growing": False, "oi_change_pct": 0, "days_growing": 0})
            score, nominal_value, direction, options = _score_backtest(row, dark_pool, oi_data)
            result_status, pnl_pct = _result_from_prices(row, historic_cache.get(options.contract, []))
            max_score = max(max_score, score.total)
            alert = Alert(
                ticker=ticker,
                asset_type="OPTION",
                mode="BACKTEST",
                tier=_tier_num(score.total),
                score_total=score.total,
                score_icc=score.icc,
                score_darkpool=score.dark_pool,
                score_flow=score.options_flow,
                score_regime=score.macro_bonus,
                score_macro=score.macro_bonus,
                entry_price=score.entry or None,
                stop_loss=score.stop_loss or None,
                target1=score.target1 or None,
                target2=score.target2 or None,
                contract=options.contract,
                strike=_float(_pick(row, "strike", "strike_price", default=0)) or None,
                expiration=_pick(row, "expiration", "expiry", "expiry_date", "expiration_date", default=None),
                delta=options.delta,
                premium=nominal_value,
                volume=options.volume,
                open_interest=options.open_interest,
                vol_oi_ratio=options.vol_oi_ratio,
                oi_growing=bool(oi_data.get("oi_growing")),
                oi_change_pct=oi_data.get("oi_change_pct", 0),
                oi_days_growing=oi_data.get("days_growing", 0),
                oi_today=oi_data.get("today_oi"),
                oi_yesterday=oi_data.get("yesterday_oi"),
                dp_print_price=dark_pool.print_price if dark_pool else None,
                dp_print_size=dark_pool.print_size if dark_pool else None,
                dp_above_vwap=dark_pool.above_vwap if dark_pool else None,
                dp_cluster=dark_pool.cluster if dark_pool else None,
                signal_summary=f"BACKTEST GBDS: {score.reason}",
                icc_phase=direction,
                icc_signal="historical_uw_flow_alert",
                regime="BACKTEST_TRENDING",
                market_session="BACKTEST",
                status=result_status,
                pnl_pct=pnl_pct,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(alert)
            loaded += 1

        db.commit()
        wins = db.query(Alert).filter(Alert.mode == "BACKTEST", Alert.status == "win").count()
        losses = db.query(Alert).filter(Alert.mode == "BACKTEST", Alert.status == "loss").count()
    finally:
        db.close()

    print(f"Backtest cargado: {loaded} alertas")
    print(f"Score maximo: {max_score}")
    print(f"WIN: {wins}")
    print(f"LOSS: {losses}")


async def run_backfill():
    await main()


if __name__ == "__main__":
    asyncio.run(main())
