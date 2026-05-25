# Livermore AI — cerebro del producto (fuente única)

Este documento concentra **decisiones de producto** (tiers, Render, roadmap).  
**La doctrina de tape reading de Jorge** vive en **[JORGE_DOCTRINE.md](JORGE_DOCTRINE.md)** y **`docs/doctrine/`** — leer eso antes que este archivo para scanner/alertas/ICC.

**Cursor es el único ejecutor de código** en este repo.

**Repo:** https://github.com/staketoday91-dotcom/livermore-ai  
**Producción:** https://livermore-ai.onrender.com

---

## Identidad del producto

- **No** es un scanner genérico de Unusual Whales — es el **cerebro de Jorge Sanchez automatizado**.
- Filosofía: *"El volumen es el único lenguaje real del mercado."*
- Modelo: **flujo + tiempo de espera + catalizador**. Institucional aguanta 5–30 días.
- Fuente de datos: **Unusual Whales API** únicamente para diagnóstico Livermore.
- **No** ejecuta trades; detecta, puntúa y alerta.

**Proyecto distinto:** Forge Sanchez (IA **Forge Chuki**) — ver [PROJECTS.md](PROJECTS.md).

---

## Dos tipos de “tier” (no mezclar)

| Concepto | Qué es | Dónde vive |
|----------|--------|------------|
| **Tier de señal** | Calidad GBDS: ALERT 75+ / PREMIUM 85+ / LIVERMORE 95+ | `core/institutional_rules.py`, scorer |
| **Tier de suscripción** | Qué paga el miembro → Discord + web + /uw | Roles Discord + Whop (futuro) |

**Precios:** NO definidos aún. No usar cifras del PDF como verdad de producto.

---

## Matriz de beneficios por suscripción (cerrada por Jorge)

### FREE

| Área | Beneficio |
|------|-----------|
| Discord | Acceso general + `#alertas-free` |
| Alertas | **Simples** — ticker, score, dirección; sin contrato ni niveles |
| Web | Landing / demo limitada |
| `/uw` | No |

### Tier 2 (suscripción de pago — nombre comercial TBD)

| Área | Beneficio |
|------|-----------|
| Discord | Alertas **más explicadas** en `#alertas-tier1` (contrato, breakdown, niveles ref) |
| Web | **Scanner Livermore AI** — terminal en livermore-ai.onrender.com |
| `/uw` | Tier 2+: `/uw flow`, `/uw darkpool`, `/uw tide` (ephemeral, canal UW) |
| Señales | Recibe alertas score ≥ 75 (formato explicado) |

### VIP

| Área | Beneficio |
|------|-----------|
| Discord | Todo Tier 2 + **alertas detalladas** en `#alertas-vip` (score ≥ 85) |
| Análisis | Contrato en detalle, dirección, **SL acción + guía SL opción** (según entrada del usuario) |
| `/uw` | Full incl. `/uw alerts` |
| Live | Acceso exclusivo **canal live** (`DISCORD_LIVE_CHANNEL`) — Jorge trading en vivo |
| Futuro | Advisor, `/daytrading`, GEX/Vanna, todo lo que se construya de valor |

**Roles Discord (Render env):**

| Variable | Uso |
|----------|-----|
| `DISCORD_ROLE_TIER2_ID` | Suscripción Tier 2 |
| `DISCORD_ROLE_VIP_ID` | Suscripción VIP |
| `DISCORD_LIVE_CHANNEL` | Canal live exclusivo VIP |

Implementación: `bot/tier_access.py`, `bot/uw_private.py`, `bot/discord_bot.py`.

---

## Doctrina (no negociable)

Vive en `core/institutional_rules.py`:

| Regla | Implementación |
|-------|----------------|
| Nominal USD, no conteo de contratos | `uw_fetcher`, `scorer` |
| STOCK / ETF / INDEX separados | `classify_ticker()` |
| Single-leg > multi-leg | scorer |
| Delta 0.30–0.70 convicción | `delta_modifier()` |
| OI day-over-day | `get_oi_change()` |
| Mismo contrato, flujo repetido | `_group_repeated_flow()` |
| Aceleración entre scans | `ContractFlowSnapshot` |
| Macro FOMC/CPI/NFP/OPEX | `get_macro_calendar()` |
| Tiers señal 75 / 85 / 95 | `TIER_*` |

---

## Workflow automatizado (tipo C — objetivo)

El pipeline **debe** replicar el flujo de Jorge: **Flash → Tape → Auto** (ver [JORGE_DOCTRINE.md](JORGE_DOCTRINE.md)).  
Hoy en código aún predomina **scan por ticker + GBDS**; la migración a feed global + reglas explícitas está pendiente.

```
UW option-contract screener (poll global) → Flash direccional → Tape → ICC → Auto → alerta

**ICC (gráfico):** ver [`doctrine/02-icc.md`](doctrine/02-icc.md) — solo **CONTINUATION** para alerta; 4H > 1H; indicación/corrección = observar, no publicar.
```

Los 20 puntos ciegos (`core/blind_spots.py`) son ayuda en Tape; **no** sustituyen la doctrina completa en `docs/doctrine/`.

| # | Punto ciego | Estado |
|---|-------------|--------|
| 01 | Régimen chop ADX<20 | implemented |
| 02 | Hedge vs direccional | implemented |
| 03 | Dark pool lag | partial |
| 04 | Calendario macro | implemented |
| 05 | Cluster prints | implemented |
| 06 | VWAP del print | implemented |
| 07 | Golden sweep | implemented |
| 08 | Ventanas 9:30–11 / 2:30–4 | implemented |
| 09 | BURST vs STEADY | implemented |
| 10 | Absorción silenciosa | partial |
| 11 | GEX flip | pending (UW premium) |
| 12 | Vanna drift | pending |
| 13 | OPEX / charm | partial |
| 14 | Correlación multi-mercado | pending |
| 15 | Strike día siguiente | partial |
| 16 | Pre-market tape | partial |
| 17 | Futuros puente | pending |
| 18 | Earnings DTE | implemented |
| 19 | IVR → módulo prima | partial (futuro) |
| 20 | Position sizing | n/a (trader) |

API: `GET /api/blind-spots` — tabla de estado.

---

## Decisiones cerradas (ingeniería)

1. **Unidad = contrato OCC** — $250K acum + ≥2 hits.
2. **LIVERMORE (95+)** exige `is_accelerating`.
3. **Watchlist precios** — `/stock/{ticker}/ohlc/1d` → DB (no screener top-50).
4. **ICC gráfico** — `/stock/{ticker}/ohlc/1h` y `4h` → `ICCDetector`; veto si 4H contradice flujo. Validar: `python scripts/validate_flash_screener.py`.
4. **Producto 24/7** — scanner no aborta fuera de RTH; histórico = DB propia.
5. **`/api/alerts?date=YYYY-MM-DD`** — histórico por fecha NY.
6. **Render:** `ENABLE_LIVERMORE_SCANNER=true`, `MAX_SCAN_TICKERS=12`.
7. **UI web** — sistema visual Hallmark (`design.md`): terminal workbench 3 columnas, nav flotante, tema oscuro + oro Livermore; assets en `web/static/`.

---

## Anti-patrones

- No LangGraph / ejecución autónoma Alpaca en Livermore.
- No `core/fetcher.py` (Polygon/Tradier) para diagnóstico UW.
- No histórico UW por fecha en API — solo DB capturada.
- No fijar precios antes de validar beneficios y pipeline en vivo.
- No mezclar Forge Sanchez con Livermore en la misma tarea.
- Claude = ideas; Cursor = código.

---

## Mapa de archivos

| Pieza | Archivo |
|-------|---------|
| Web + API | `main.py` |
| UI Hallmark (tokens, páginas) | `web/`, `design.md`, `/static/*` |
| Scanner | `core/scanner.py` |
| UW API | `core/uw_fetcher.py` |
| GBDS + blind spots | `core/scorer.py`, `core/blind_spots.py` |
| Discord + tiers | `bot/discord_bot.py`, `bot/uw_private.py`, `bot/tier_access.py` |
| Worker 24/7 | `worker.py` |
| Beta log | `docs/BETA_ALERTS.md` |

---

## Render (variables críticas)

| Variable | Valor |
|----------|-------|
| `ENABLE_LIVERMORE_SCANNER` | `true` |
| `MAX_SCAN_TICKERS` | `12` |
| `SCAN_TICKER_DELAY_SECONDS` | `5` |
| `DISCORD_ROLE_TIER2_ID` | rol Tier 2 |
| `DISCORD_ROLE_VIP_ID` | rol VIP |
| `DISCORD_LIVE_CHANNEL` | canal live Jorge |
| `WHOP_WEBHOOK_SECRET` | (cuando Whop esté activo) |

---

## Roadmap

| Fase | Objetivo |
|------|----------|
| 0 | Validar producción: flow>0, cron, OOM — ver `docs/PRODUCTION_VALIDATION.md` |
| 1 | UI histórico, watchlist DB-only, cron extendido |
| 2 | Roles Discord + gates /uw + Whop webhook stub |
| 3 | Completar puntos ciegos pendientes, SPX/INDEX |
| 4 | Whop precios TBD, beta 30 alertas, `/daytrading`, advisor VIP |

---

## Whop / monetización

**Pendiente** hasta cerrar beta. Stub: `POST /api/whop/webhook` asigna roles Discord cuando `WHOP_WEBHOOK_SECRET` esté configurado.

---

## Migrar decisiones de Claude

1. Copiar solo el párrafo de decisión → issue o mensaje a Cursor.
2. Cursor actualiza este doc + código + commit.
3. No mantener copias paralelas del repo como verdad.
