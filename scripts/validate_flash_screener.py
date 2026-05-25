#!/usr/bin/env python3
"""
Validación local — preset Jorge (UW option-contract screener + filtro direccional).

Uso:
  python scripts/validate_flash_screener.py
  python scripts/validate_flash_screener.py --ohlc NVDA

Requiere UNUSUAL_WHALES_TOKEN en .env o entorno.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

load_dotenv()


async def main() -> int:
    parser = argparse.ArgumentParser(description="Validar Flash screener UW")
    parser.add_argument("--ohlc", metavar="TICKER", help="Probar velas 1H/4H para un ticker")
    parser.add_argument("--no-watchlist", action="store_true", help="Omitir UW_SCREENER_WATCHLIST")
    args = parser.parse_args()

    token = os.getenv("UNUSUAL_WHALES_TOKEN", "").strip()
    if not token:
        print("ERROR: falta UNUSUAL_WHALES_TOKEN en .env")
        return 1

    from core.flash_feed import (
        filter_directional_universe,
        normalize_screener_row,
        poll_flash_universe,
        tickers_from_flash,
    )
    from core.uw_fetcher import UWFetcher

    uw = UWFetcher()
    if args.no_watchlist:
        os.environ["UW_SCREENER_WATCHLIST"] = ""

    print("=== 1) API screener (raw) ===")
    raw = await uw.get_jorge_option_screener()
    print(f"Filas API: {len(raw)}")
    if not raw:
        print("  (0 filas: revisa token, limite diario UW 429, o quita watchlist con --no-watchlist)")
    if raw:
        sample = raw[0]
        print(f"  Ejemplo keys: {list(sample.keys())[:12]}...")
        print(
            f"  ticker={sample.get('ticker_symbol')} "
            f"premium={sample.get('premium')} "
            f"vol={sample.get('volume')} oi={sample.get('open_interest')}"
        )

    print("\n=== 2) Flash poll (normalizado + direccional + agrupado) ===")
    grouped = await poll_flash_universe(uw)
    tickers = tickers_from_flash(grouped, 15)
    print(f"Contratos agrupados: {len(grouped)}")
    print(f"Tickers direccionales (top 15): {tickers}")

    if grouped:
        top = grouped[0]
        print(
            f"  Top contrato: {top.get('option_chain')} "
            f"nominal={top.get('accumulated_nominal')} hits={top.get('flow_count')}"
        )

    # Direccional: cuántos se habrían descartado
    norm = [normalize_screener_row(r) for r in raw]
    norm = [n for n in norm if n.get("ticker")]
    before = len({n["ticker"] for n in norm})
    after_rows = filter_directional_universe(norm)
    after = len({n["ticker"] for n in after_rows})
    print(f"\n  Tickers antes filtro C+P: {before} -> despues: {after}")

    if args.ohlc:
        ticker = args.ohlc.upper()
        print(f"\n=== 3) OHLC {ticker} (ICC) ===")
        c1h = await uw.get_stock_ohlc(ticker, "1h", limit=40)
        c4h = await uw.get_stock_ohlc(ticker, "4h", limit=20)
        print(f"  Velas 1H: {len(c1h)}  4H: {len(c4h)}")
        if c1h:
            last = c1h[-1]
            print(f"  Última 1H: O={last.open} H={last.high} L={last.low} C={last.close}")
        from core.icc_engine import ICCDetector

        if len(c1h) >= 5:
            avg_vol = sum(c.volume for c in c1h) / len(c1h)
            icc = ICCDetector().detect(c1h, avg_vol)
            print(f"  ICC 1H: phase={icc.phase.value} dir={icc.direction} score={icc.score}")
            print(f"  {icc.description}")

    print("\nOK — revisa filas > 0 y tickers coherentes con tu preset web.")
    if not raw and not grouped:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
