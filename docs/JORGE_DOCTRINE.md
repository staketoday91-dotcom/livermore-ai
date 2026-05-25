# Doctrina Jorge — memoria permanente (tipo C)

**Este archivo es la fuente de verdad del tape reading de Jorge.**  
Los chats de Claude/Cursor **no** guardan memoria entre sesiones. **Este repo sí.**

Cursor y cualquier agente deben leer esto **antes** de cambiar `scanner.py`, reglas o alertas.

**Recuperar chats viejos y ritual “solo aprender más”:** [`MEMORIA_PERMANENTE.md`](MEMORIA_PERMANENTE.md).  
**Prompt para volcar un chat antiguo:** [`doctrine/PROMPT_VOLCAR_CHAT.md`](doctrine/PROMPT_VOLCAR_CHAT.md).

---

## Jerarquía de documentos (orden de lectura)

| Prioridad | Archivo | Contenido |
|-----------|---------|-----------|
| 1 | **Este archivo** (`JORGE_DOCTRINE.md`) | Índice + pipeline tipo C |
| 2 | [`doctrine/`](doctrine/) | ICC, Flash/Tape/Auto, escoger contratos, artículos |
| 3 | [`LIVERMORE_BRAIN.md`](LIVERMORE_BRAIN.md) | Producto, tiers suscripción, Render, roadmap |
| 4 | [`PROJECT_CHECKPOINT.md`](../PROJECT_CHECKPOINT.md) | Estado técnico del repo |
| 5 | Código | `core/icc_engine.py`, `institutional_rules.py`, `blind_spots.py` |

**Regla:** Si algo contradice `doctrine/` → gana **doctrine/** (Jorge lo actualiza). Si falta en doctrine → no inventar; marcar `PENDIENTE` y preguntar.

---

## Norte del producto (cerrado por Jorge)

- **Tipo C:** réplica automatizada de **cómo Jorge lee tape** (Flash → Tape → reglas), **no** GBDS genérico como única verdad.
- **Entrada:** poll global UW **option-contract screener** (preset $250K OTM, ask 70%, vol>OI) → filtro direccional (sin calls+puts mismo día) → Tape/ICC. No scan ticker-a-ticker como fuente principal (`LIVERMORE_FEED_FIRST=true`).
- **Unidad:** contrato **OCC** + nominal USD + repetición en el mismo contrato.
- **Alineación gráfico:** **ICC** (Indication → Correction → Continuation) — doctrina completa en [`doctrine/02-icc.md`](doctrine/02-icc.md). **Auto solo en CONTINUATION**; 4H > 1H > 15m; no alertar en indicación/corrección ni contra el gráfico.
- **Salida:** alerta solo si Flash + Tape + Auto (Jorge) dicen publicable.

GBDS (`core/scorer.py`) puede quedar como **ranking secundario** hasta que la doctrina esté completa en código.

---

## Pipeline Flash → Tape → Auto

| Fase | Pregunta | Dónde documentar | Estado código |
|------|----------|------------------|---------------|
| **Flash** | ¿Merece atención en 5 segundos? (premium, vol/OI, ask, sweep, single-leg) | [`doctrine/01-flash-tape-auto.md`](doctrine/01-flash-tape-auto.md) | Parcial (`4_whale_catcher`, Forge `WhaleScannerAgent`) |
| **Tape** | ¿Contrato + OI + escalera + DP + delta + macro + ICC en gráfico? | [`doctrine/03-escoger-contratos.md`](doctrine/03-escoger-contratos.md) | Parcial (`institutional_rules`, `blind_spots`, `icc_engine`) |
| **Auto** | ¿Lo publicaría mañana? (tier, niveles, copy) | [`doctrine/01-flash-tape-auto.md`](doctrine/01-flash-tape-auto.md) | Parcial (`_fire_alert`, Discord) |

Implementación objetivo: `core/jorge_pipeline.py` (por crear) con `rejection_reasons` / `accepted_reasons` explícitos, como Forge.

---

## Cómo guardar lo que enseñas (artículos, ICC, vídeos)

1. **Resumen en español** (10–30 líneas) en el `.md` correspondiente bajo `docs/doctrine/`.
2. **Reglas numeradas** en formato checklist (sí/no, umbrales).
3. Opcional: PDF/HTML en `docs/doctrine/sources/` + enlace en [`doctrine/04-fuentes.md`](doctrine/04-fuentes.md).
4. Decir a Cursor: *"Actualiza `docs/doctrine/02-icc.md` con esto"* — no solo pegar en el chat.

Plantilla para cada sesión de enseñanza: [`doctrine/_plantilla-sesion.md`](doctrine/_plantilla-sesion.md).

---

## Mapa código ↔ doctrina

| Doctrina | Código actual | Notas |
|----------|---------------|-------|
| ICC 1H + MTF | `core/icc_engine.py` + [`doctrine/02-icc.md`](doctrine/02-icc.md) | Doctrina = swings/sesiones/continuación; motor = velas AOI; scanner **simula** ICC con net premium (**sustituir**) |
| Reglas nominal / categoría | `core/institutional_rules.py` | Verdad en código hasta sync con doctrine |
| 20 puntos ciegos | `core/blind_spots.py` | Tape parcial |
| Flash global UW | `get_jorge_option_screener` + `core/flash_feed.py` | `/screener/option-contracts`; direccional; feed-first en scanner |
| Flow alerts (aux) | `core/uw_fetcher.get_flow_alerts` | Rollovers / legacy |
| Scanner | `core/scanner.py` | **Ticker-first** — reemplazar por feed-first tipo C |

---

## Changelog doctrina

| Fecha | Cambio |
|-------|--------|
| 2026-05-25 | Creada estructura memoria; tipo C = Flash→reglas; feed global > scan tickers |
| 2026-05-25 | ICC Escuela Entera (14 cap.) volcada en `doctrine/02-icc.md`; Auto = solo CONTINUATION + MTF |
| 2026-05-25 | Flash = poll global screener UW (preset Jorge) + descarte calls+puts mismo día |

*Jorge o Cursor: añadir fila al enseñar ICC o artículos.*
