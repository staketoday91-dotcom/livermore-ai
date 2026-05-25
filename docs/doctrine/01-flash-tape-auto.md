# Flash → Tape → Auto (tipo C)

## Flash — filtro rápido

**Fuente (poll global, no ticker-a-ticker):** UW `GET /screener/option-contracts` — preset Jorge.

| Parámetro | Valor |
|-----------|--------|
| `min_premium` | $250,000 |
| `min_ask_perc` | 0.7 |
| `min_volume` | 500 |
| `vol_greater_oi` | true |
| `max_multileg_volume_ratio` | 0.1 |
| `exclude_itm` | true |
| `max_dte` | 183 |
| `issue_types` | Common Stock, ADR |
| `limit` | 150 |
| `watchlist_name` (opcional) | `500K OTM Call Buyer Stock Only` — env `UW_SCREENER_WATCHLIST` |

**Regla direccional (Jorge):** si el mismo ticker tiene **calls y puts** inusuales el mismo día → **descartar** (no hay convicción direccional).

**Código:** `core/uw_fetcher.get_jorge_option_screener()`, `core/flash_feed.py`, scanner `LIVERMORE_FEED_FIRST=true` (default).

- [x] Premium mínimo $250K (screener API)
- [x] vol > OI
- [x] ask ≥ 70%
- [x] multi-leg ratio ≤ 0.1
- [x] OTM / exclude ITM
- [ ] ETF / INDEX en preset aparte (hoy solo Stock + ADR en screener)

---

## Tape — lectura de cinta (contrato)

*Ver también [`03-escoger-contratos.md`](03-escoger-contratos.md) e [`02-icc.md`](02-icc.md).*

- [ ] PENDIENTE: reglas de Jorge (artículos)
- Código parcial: `institutional_rules.py`, `blind_spots.py`, ladder/OI en `uw_fetcher.py`
- **ICC en Tape:** fase en 1H (ideal 4H contexto) — ver checklist en [`02-icc.md`](02-icc.md)

---

## Auto — publicar alerta

Criterio mínimo **tras doctrina ICC (2026-05-25)**:

- [x] **Solo** `icc_phase == CONTINUATION` (no indicación ni corrección)
- [x] Dirección del flujo UW **alineada** con dirección ICC (no long si gráfico bearish continuation)
- [ ] 4H sin conflicto con 1H (`icc_mtf_conflict` — PENDIENTE en código)
- [ ] Sesión con volumen (NY/London) — PENDIENTE filtro horario
- [ ] Flash + Tape completos (umbrales Jorge en 03-*)
- [ ] Tiers 75/85/95 vs “operable Jorge” — PENDIENTE negocio

Salida deseada: Discord + DB con contrato OCC, niveles, **fase ICC**, MTF, `rejection_reasons` en lenguaje Jorge.

**Código hoy:** `scanner.py` ya veto si no CONTINUATION; ICC aún simulado con net premium — sustituir por velas 1H + doctrina swing.
