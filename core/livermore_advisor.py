"""
Asistente conversacional Livermore — misma doctrina que Aetheris, fuente UW + Postgres.
No es el chat de la web de Unusual Whales; consulta la API de datos UW.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from core.institutional_rules import (
    PRODUCT_ROLES,
    TIER_ALERT,
    TIER_LIVERMORE,
    TIER_PREMIUM,
    principles_block,
)
from core.models import Alert, WatchlistItem
from core.uw_fetcher import UWFetcher, classify_ticker

logger = logging.getLogger("livermore.advisor")

_TICKER_RE = re.compile(r"\b([A-Z]{1,6})\b")


class LivermoreAdvisor:
  def __init__(self, db: Session):
    self.db = db
    self.uw = UWFetcher()

  async def reply(self, prompt: str) -> str:
    q = (prompt or "").strip().lower()
    if not q:
      return self._intro()

    if any(x in q for x in ("ayuda", "qué puedes", "que puedes", "quien eres", "quién eres")):
      return self._help()

    if "reglas" in q or "doctrina" in q or "educacion" in q or "educación" in q:
      return (
        "Doctrina institucional (Livermore = Antigravity):\n"
        f"{principles_block()}\n\n"
        f"Tiers: ALERT {TIER_ALERT}+, PREMIUM {TIER_PREMIUM}+, LIVERMORE {TIER_LIVERMORE}+."
      )

    ticker = self._extract_ticker(prompt)
    if ticker:
      return await self._ticker_brief(ticker, q)

    if "alerta" in q or "oportunidad" in q or "scan" in q:
      return self._alerts_summary()

    if "macro" in q or "tide" in q or "mercado" in q:
      return await self._market_context()

    return (
      "Livermore Advisor: pregúntame por un ticker (ej. NVDA), alertas activas, "
      "macro/tide, o escribe 'reglas' para la doctrina institucional."
    )

  def _intro(self) -> str:
    return (
      f"{PRODUCT_ROLES['livermore']}\n"
      "Conectado a Unusual Whales (datos) y a tu base de alertas. "
      "Pregunta por ticker, alertas o contexto de mercado."
    )

  def _help(self) -> str:
    return (
      f"{PRODUCT_ROLES['livermore']}\n\n"
      "Puedo:\n"
      "- Resumir flujo UW, dark pool y net premium de un ticker\n"
      "- Listar alertas guardadas y scores GBDS\n"
      "- Explicar market tide y calendario macro\n"
      "- Recordarte las reglas institucionales (mismas que Aetheris en local)\n\n"
      f"{principles_block()}"
    )

  def _extract_ticker(self, prompt: str) -> Optional[str]:
    ignore = {
      "POR", "QUE", "QUÉ", "THE", "AND", "FOR", "MACRO", "TIDE", "ALERT", "SCAN",
      "COMO", "MISMO", "UW", "API", "AI",
    }
    for word in prompt.upper().split():
      w = re.sub(r"[^A-Z]", "", word)
      if 1 <= len(w) <= 6 and w.isalpha() and w not in ignore:
        return w
    return None

  async def _ticker_brief(self, ticker: str, q: str) -> str:
    ticker = ticker.upper()
    category = classify_ticker(ticker)
    lines = [f"**{ticker}** ({category}) — lectura UW en vivo:"]

    try:
      tide = await self.uw.get_market_tide()
      if tide:
        lines.append(
          f"Market tide: {tide.get('market_direction', 'N/A')} | "
          f"calls {tide.get('net_call_premium', 0):,.0f} | puts {tide.get('net_put_premium', 0):,.0f}"
        )
    except Exception as e:
      logger.warning(f"market_tide: {e}")

    try:
      net = await self.uw.get_net_premium(ticker)
      if net:
        lines.append(
          f"Net premium: calls {net.get('net_call_premium', 0):,.0f} | "
          f"puts {net.get('net_put_premium', 0):,.0f}"
        )
    except Exception as e:
      logger.warning(f"net_premium {ticker}: {e}")

    try:
      flows = await self.uw.get_ticker_flow(ticker)
      if flows:
        best = max(flows, key=lambda f: float(f.get("nominal_value") or 0))
        nom = float(best.get("nominal_value") or 0)
        lines.append(
          f"Mejor flujo reciente: nominal ${nom:,.0f} | "
          f"Vol/OI {float(best.get('volume_oi_ratio') or 0):.2f}x | "
          f"single-leg={best.get('is_single_leg', True)}"
        )
      else:
        lines.append("Sin flujo reciente UW que pase filtros institucionales.")
    except Exception as e:
      lines.append(f"Flujo UW: error temporal ({type(e).__name__}).")

    alert = (
      self.db.query(Alert)
      .filter(Alert.ticker == ticker)
      .order_by(Alert.created_at.desc())
      .first()
    )
    if alert and alert.score_total:
      lines.append(
        f"Última alerta Livermore: score {alert.score_total} tier {alert.tier} "
        f"({alert.created_at.date() if alert.created_at else 'n/a'})."
      )
    else:
      lines.append(
        f"Sin alerta Livermore guardada. Publicar requiere score ≥ {TIER_ALERT} "
        f"con continuación ICC + nominal por categoría."
      )

    watch = self.db.query(WatchlistItem).filter(WatchlistItem.ticker == ticker).first()
    if watch:
      lines.append(f"En watchlist interna: precio {watch.current_price}, fase {watch.icc_phase}.")

    return "\n".join(lines)

  def _alerts_summary(self) -> str:
    rows = (
      self.db.query(Alert)
      .filter(Alert.status != "backtest")
      .order_by(Alert.score_total.desc())
      .limit(8)
      .all()
    )
    total = self.db.query(Alert).filter(Alert.status != "backtest").count()
    if not rows:
      return (
        f"No hay alertas publicadas ({total} en histórico filtrado). "
        "El scanner corre cada 5 min en horario de mercado; usa ⚡ SCAN AHORA o despliega el worker."
      )
    parts = [f"Top alertas ({total} total):"]
    for a in rows:
      parts.append(f"- {a.ticker} score {a.score_total} tier {a.tier} {a.direction or ''}")
    return "\n".join(parts)

  async def _market_context(self) -> str:
    lines = ["Contexto de mercado (UW):"]
    try:
      tide = await self.uw.get_market_tide()
      if tide:
        lines.append(
          f"Direction: {tide.get('market_direction')} | "
          f"net calls {tide.get('net_call_premium', 0):,.0f} | "
          f"net puts {tide.get('net_put_premium', 0):,.0f}"
        )
    except Exception as e:
      lines.append(f"Tide: {type(e).__name__}")

    try:
      cal = await self.uw.get_macro_calendar()
      if cal.get("has_event_today"):
        lines.append(f"⚠️ Macro hoy: {', '.join(cal.get('events_today', [])[:3])}")
      elif cal.get("has_event_tomorrow"):
        lines.append(f"Macro mañana: {', '.join(cal.get('events_tomorrow', [])[:3])}")
      else:
        lines.append("Calendario macro limpio próximos días.")
    except Exception as e:
      lines.append(f"Calendario: {type(e).__name__}")

    return "\n".join(lines)
