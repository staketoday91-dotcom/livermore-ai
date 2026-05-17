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
from core.scorer import LivermoreScorer, OptionsFlowSignal, MacroContext  # noqa: E402

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


def _direction(data: dict) -> str:
    option_type = str(_pick(data, "option_type", "type", "call_put", default="")).lower()
    sentiment = str(_pick(data, "sentiment", "side", "direction", default="")).lower()
    if "put" in option_type or "bear" in sentiment:
        return "BEARISH"
    return "BULLISH"


def _score_backtest(data: dict):
    premium = _float(_pick(data, "total_premium", "premium", "ask_side_premium", default=0))
    volume = _int(_pick(data, "volume", "total_volume", default=0))
    open_interest = max(_int(_pick(data, "open_interest", "oi", default=1), 1), 1)
    vol_oi = _float(_pick(data, "volume_oi_ratio", "vol_oi_ratio", default=volume / open_interest))
    ask_premium = _float(_pick(data, "total_ask_side_prem", "ask_side_premium", default=premium))
    executed_ask = ask_premium / premium if premium > 0 else 0
    is_sweep = _bool(_pick(data, "has_sweep", "is_sweep", "sweep", default=False))
    is_floor = _bool(_pick(data, "has_floor", "floor", default=False))
    delta = abs(_float(_pick(data, "delta", default=0.5), 0.5))
    iv_rank = _float(_pick(data, "iv_rank", default=50), 50)
    dte = _int(_pick(data, "dte", "days_to_expiration", default=30), 30)
    direction = _direction(data)

    icc_score = 25
    if premium >= 500_000:
        icc_score += 5
    if executed_ask >= 0.70:
        icc_score += 5

    options = OptionsFlowSignal(
        volume=volume,
        open_interest=open_interest,
        vol_oi_ratio=vol_oi,
        executed_ask=executed_ask,
        premium_total=premium,
        is_sweep=is_sweep,
        is_golden_sweep=(is_sweep or is_floor) and premium >= 500_000 and vol_oi >= 5,
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
        dark_pool=None,
        options_flow=options,
        macro=macro,
        adx=25.0,
        regime="BACKTEST_TRENDING",
    )
    return result, premium, direction, options


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

    db = SessionLocal()
    try:
        for row in rows:
            premium = _float(_pick(row, "total_premium", "premium", "ask_side_premium", default=0))
            if premium <= 100_000:
                continue

            ticker = _ticker(row)
            if not ticker:
                continue

            score, premium, direction, options = _score_backtest(row)
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
                premium=premium,
                volume=options.volume,
                open_interest=options.open_interest,
                vol_oi_ratio=options.vol_oi_ratio,
                signal_summary=f"BACKTEST GBDS: {score.reason}",
                icc_phase=direction,
                icc_signal="historical_uw_flow_alert",
                regime="BACKTEST_TRENDING",
                market_session="BACKTEST",
                status="backtest",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(alert)
            loaded += 1

        db.commit()
    finally:
        db.close()

    print(f"Backtest cargado: {loaded} alertas")


if __name__ == "__main__":
    asyncio.run(main())
