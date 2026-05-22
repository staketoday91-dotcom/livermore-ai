# Livermore AI — cerebro del producto (fuente única)

Este documento concentra **decisiones de producto y tape reading** que antes vivían en chats de Claude.  
**Cursor es el único ejecutor de código** en este repo. Claude (u otros) solo aportan ideas si tú las traes aquí como texto o issues.

**Repo:** https://github.com/staketoday91-dotcom/livermore-ai  
**Carpeta local:** `C:\Users\mcgre\Downloads\livermore-ai-v2`  
**Producción:** https://livermore-ai.onrender.com

---

## Qué es Livermore (alcance)

- Terminal de tape reading para **suscriptores de pago**.
- Fuente de datos: **Unusual Whales API** (no el chat de la web UW).
- Entrega: dashboard web + alertas Discord por tier + backtesting.
- **No** ejecuta trades; detecta y puntúa convicción institucional.

**Proyecto distinto de Antigravity** (ver [PROJECTS.md](PROJECTS.md)): Antigravity usa el chat Aetheris / Forge Sanchez; no comparte deploy ni producto con Livermore. En este repo conviven carpetas por historial, pero cada tarea de Cursor debe ser de **un solo proyecto**.

---

## Doctrina (no negociable)

Vive en código: `core/institutional_rules.py`. Resumen:

| Regla | Implementación |
|-------|----------------|
| Nominal en USD, no conteo de contratos | `core/uw_fetcher.py` → `nominal_value`; `core/scorer.py` |
| STOCK / ETF / INDEX separados | `classify_ticker()`, thresholds por categoría |
| Single-leg > multi-leg | `is_single_leg()`, penalización en scorer |
| Delta 0.30–0.70 convicción | `delta_modifier()` |
| OI day-over-day | `get_oi_change()`, multiplicadores |
| Mismo contrato, flujo repetido | `_group_repeated_flow()` |
| Escalera / put gaps | `get_option_chain_map()` |
| Rollover | `detect_rollover()` |
| Macro FOMC/CPI/NFP/OPEX | `get_macro_calendar()` |
| Tiers 75 / 85 / 95 | `TIER_ALERT`, `TIER_PREMIUM`, `TIER_LIVERMORE` |

---

## Decisiones cerradas (sesiones Claude → código)

### 1. Unidad de acumulación = **contrato**, no ticker

- Agrupar por OCC (`ContractFlowSnapshot`, `_group_repeated_flow`).
- No sumar todo el premium de TSLA mezclando strikes distintos.

### 2. Elegibilidad de flow en scanner

- Mínimo **$250K acumulado por contrato** + **≥2 hits** en el mismo contrato.
- Un solo print de $100K no basta; acumulación repetida sí.

### 3. Aceleración entre scans (derivada)

- Tabla `contract_flow_snapshots`: compara acumulado actual vs scan anterior.
- **LIVERMORE (95+)** exige `is_accelerating` cuando hay señal de opciones (timing en vivo).
- Sin aceleración → techo **PREMIUM** aunque el nivel sea alto.

### 4. Watchlist: precios vía scanner → DB

- **No** depender del screener top-50 para precios de *tus* tickers.
- `hydrate_watchlist_prices()` + `get_stock_price()` → `/stock/{ticker}/ohlc/1d`.
- `/api/watchlist` lee `WatchlistItem.current_price` de Postgres.

### 5. Producto 24/7 (mercado cerrado ≠ app vacía)

- El scanner **no** debe abortar todo fuera de RTH.
- Fuera de horario: analizar flujo acumulado de la sesión; hidratar precios siempre.
- Histórico por fecha: `/api/alerts?date=YYYY-MM-DD` (solo días que el scanner guardó).

### 6. Límite real de UW

- `flow-alerts` **no** filtra por fecha arbitraria en la API.
- Histórico profundo = lo que **tu DB** capturó mientras el scanner corría.

---

## Mapa de archivos (Livermore)

| Pieza | Archivo |
|-------|---------|
| Web + API + dashboard | `main.py` |
| Scanner + hidratación | `core/scanner.py` |
| UW API | `core/uw_fetcher.py` |
| GBDS score | `core/scorer.py` |
| Modelos / DB | `core/models.py` |
| Reglas compartidas | `core/institutional_rules.py` |
| Discord | `bot/discord_bot.py`, `bot/uw_private.py` |
| Solo cloud por defecto | `core/runtime.py` |
| Reglas UW (whitelist endpoints) | `antigravity/docs/UNUSUAL_WHALES_API_RULES.md` |

**Ignorar para diagnóstico Livermore:** `core/fetcher.py` (Polygon/Tradier legacy).

---

## Render (producción)

Variables críticas:

| Variable | Valor recomendado |
|----------|-------------------|
| `ENABLE_LIVERMORE_SCANNER` | `true` |
| `MAX_SCAN_TICKERS` | `12` (512MB RAM) |
| `SCAN_TICKER_DELAY_SECONDS` | `5` |
| `UNUSUAL_WHALES_TOKEN` | (secreto) |
| `DATABASE_URL` | Postgres interno Render |
| `DISCORD_BOT_TOKEN` | (secreto) |

Tras cada push: **Manual Deploy** si no hay auto-deploy.

Prueba rápida:

```powershell
Invoke-RestMethod -Method Post -Uri "https://livermore-ai.onrender.com/api/scan/manual"
Invoke-RestMethod -Uri "https://livermore-ai.onrender.com/api/watchlist"
Invoke-RestMethod -Uri "https://livermore-ai.onrender.com/api/stats"
```

---

## Commits recientes (línea de tiempo)

| Commit | Tema |
|--------|------|
| `f254c45` | Scanner 24/7, aceleración en scorer, alertas por fecha |
| `f7cd4d5` | Hidratación precios watchlist |
| `5c82552` | Runtime cloud, Discord UW, Antigravity en repo |
| `c9c381b` | Livermore Advisor + institutional_rules |

---

## Pendiente (prioridad)

1. Validar en Render deploy de `f254c45` y cron cada 5 min en RTH.
2. Confirmar alertas nuevas con `flow > 0` en horario de mercado.
3. Rotar tokens si se pegaron en chats.
4. Plan Free 512MB: vigilar OOM; subir plan o reducir tickers.
5. Módulo SPX/INDEX dedicado (endpoints UW premium).
6. `/daytrading` cuando exista modelo de contratos en tiempo real.

---

## Cómo migrar “lo de Claude” sin perder nada

1. **No** volver a pegar archivos desde `Nueva carpeta (2)\1s\` — ya están en GitHub si Cursor los commiteó.
2. Si Claude tiene un chat largo con decisiones nuevas: copia solo el **párrafo de decisión** y pégalo en un issue o al inicio de un mensaje a Cursor (“añade esto a LIVERMORE_BRAIN”).
3. Toda implementación = commit en `main` desde esta carpeta.
4. Claude puede leer GitHub en modo consultor; **no** es segunda rama de código paralela.
