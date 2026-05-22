"""
Reglas institucionales de tape reading — usadas por dos PROYECTOS SEPARADOS:

- Livermore AI (web/pago, suscriptores)
- Antigravity (local, agentes; nombre del producto Antigravity, NO Sanchez Forge)

Misma doctrina de flujo; productos, deploy y código no se mezclan sin decisión explícita.
Ver docs/PROJECTS.md
"""
from __future__ import annotations

import os
from typing import Tuple

# ─── Doctrina (misma para ambos productos) ───────────────────────────────────

TAPE_READING_PRINCIPLES: tuple[str, ...] = (
    "El volumen de contratos no manda; manda el valor nominal en dólares.",
    "Separar siempre STOCK, ETF e INDEX; no mezclar SPX/SPXW/NDX/RUT/VIX con equities.",
    "Los ETFs pueden ser hedge; exigen umbral de premium más alto que stocks.",
    "Single-leg es la señal direccional más limpia; multi-leg reduce claridad.",
    "Delta 0.30-0.70 es zona de convicción; OTM extremo no se descarta si hay escalera, flujo repetido, OI y net premium.",
    "OI day-over-day confirma posición abierta y sostenida.",
    "Flujo repetido en el mismo contrato acumula convicción institucional.",
    "Escalera de strikes puede mostrar el camino del movimiento esperado.",
    "Rollover tracking sigue a la ballena hacia el siguiente destino.",
    "Eventos macro (FOMC/CPI/NFP/OPEX) reducen o silencian confianza.",
    "Dark pool encima de VWAP + cluster = acumulación; absorción es señal fuerte.",
    "Solo publicar alertas con score GBDS ≥ 75; Premium ≥ 85; Livermore ≥ 95.",
)

PRODUCT_ROLES = {
    "livermore": (
        "Livermore AI es el producto web de pago: escanea Unusual Whales, "
        "puntúa oportunidades y alerta a suscriptores. No ejecuta trades."
    ),
    "aetheris": (
        "Aetheris opera en Antigravity (local): mentora la mesa interna, "
        "lee la base unificada de agentes y explica decisiones del comité."
    ),
}

# ─── Umbrales de tier (fijos) ────────────────────────────────────────────────

TIER_ALERT = 75
TIER_PREMIUM = 85
TIER_LIVERMORE = 95

# ─── Premium: tolerancia solo aquí (factor 0.85 = ~15% menos en pisos mínimos) ─

DEFAULT_MIN_OPTION_PREMIUM = 100_000
PREMIUM_RELAX_FACTOR = float(os.getenv("LIVERMORE_PREMIUM_RELAX", "0.85"))
PREMIUM_RELAX_FACTOR = max(0.70, min(1.0, PREMIUM_RELAX_FACTOR))


def relaxed_premium_floor(value: float) -> float:
    return value * PREMIUM_RELAX_FACTOR


def min_option_premium() -> float:
    raw = os.getenv("MIN_OPTION_PREMIUM", str(DEFAULT_MIN_OPTION_PREMIUM))
    try:
        base = float(raw)
    except ValueError:
        base = DEFAULT_MIN_OPTION_PREMIUM
    return relaxed_premium_floor(base)


# Nominal tiers: (low_usd, high_usd, score_points) per category
_RAW_FLOW_THRESHOLDS = {
    "STOCK": (
        (500_000, 1_000_000, 5),
        (1_000_000, 3_000_000, 10),
        (3_000_000, 10_000_000, 18),
        (10_000_000, float("inf"), 25),
    ),
    "ETF": (
        (1_000_000, 3_000_000, 5),
        (3_000_000, 5_000_000, 10),
        (5_000_000, 10_000_000, 18),
        (10_000_000, float("inf"), 25),
    ),
    "INDEX": (
        (3_000_000, 5_000_000, 5),
        (5_000_000, 10_000_000, 12),
        (10_000_000, 50_000_000, 20),
        (50_000_000, float("inf"), 25),
    ),
}


def flow_thresholds(category: str) -> Tuple[Tuple[float, float, int], ...]:
    key = (category or "STOCK").upper()
    rows = _RAW_FLOW_THRESHOLDS.get(key, _RAW_FLOW_THRESHOLDS["STOCK"])
    out = []
    for low, high, pts in rows:
        out.append((relaxed_premium_floor(low), high, pts))
    return tuple(out)


def min_nominal_for_category(category: str) -> float:
    thresholds = flow_thresholds(category)
    return thresholds[0][0]


def flow_score_for_nominal(nominal: float, category: str) -> int:
    for low, high, score in flow_thresholds(category):
        if low <= nominal < high:
            return score
    return 0


def principles_block() -> str:
    return "\n".join(f"- {p}" for p in TAPE_READING_PRINCIPLES)
