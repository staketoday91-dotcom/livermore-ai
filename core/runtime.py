"""
Runtime guards — Livermore AI solo en hosting cloud (Render, Railway, etc.).
"""
from __future__ import annotations

import os
import sys

_CLOUD_MARKERS = (
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_NAME",
    "RENDER",
    "RENDER_SERVICE_ID",
    "FLY_APP_NAME",
    "VERCEL",
)


def is_cloud_runtime() -> bool:
    if os.getenv("LIVERMORE_FORCE_CLOUD", "").lower() in {"1", "true", "yes"}:
        return True
    return any(os.getenv(key) for key in _CLOUD_MARKERS)


def livermore_local_allowed() -> bool:
    return os.getenv("LIVERMORE_ALLOW_LOCAL", "false").lower() in {"1", "true", "yes"}


def require_cloud_or_exit(process_name: str) -> None:
    if is_cloud_runtime() or livermore_local_allowed():
        return
    print(
        f"\n[Livermore AI] {process_name} bloqueado en local.\n"
        "  Produccion: https://livermore-ai.onrender.com\n"
        "  Para desarrollo puntual: LIVERMORE_ALLOW_LOCAL=true en .env\n"
    )
    sys.exit(0)


def should_run_worker_in_web() -> bool:
    """
    Discord + scanner en el proceso web.
    - Cloud: activo por defecto (Render/Railway).
    - Local: desactivado salvo RUN_WORKER_IN_WEB=true o LIVERMORE_ALLOW_LOCAL.
    """
    explicit = os.getenv("RUN_WORKER_IN_WEB", "").strip().lower()
    if explicit in {"1", "true", "yes"}:
        return True
    if explicit in {"0", "false", "no"}:
        return False
    if is_cloud_runtime():
        return True
    return livermore_local_allowed() and explicit not in {"0", "false", "no"}
