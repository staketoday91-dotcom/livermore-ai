# Livermore AI Checkpoint

## Objetivo

Construir un terminal de tape reading con Unusual Whales como fuente unica:
dashboard web, backtesting, scanner, Discord alerts y un worker 24/7.

## Estado Actual

- Web/API en `main.py`.
- Worker oficial en `worker.py`.
- Dashboard principal con watchlist, market tide, alertas y scan manual.
- Paginas separadas: `/backtesting`, `/alerts`, `/watchlist`.
- Discord bot en `bot/discord_bot.py`.
- Scanner en `core/scanner.py`.
- UW fetcher en `core/uw_fetcher.py`.
- Scorer GBDS en `core/scorer.py`.

## Reglas De Arquitectura

- El web service no debe ser el proceso oficial del bot.
- Solo un worker debe tener `DISCORD_BOT_TOKEN` real en produccion.
- No correr `python main.py` local con token real si Railway worker esta activo.
- Si se usa un solo proceso temporalmente, activar `RUN_WORKER_IN_WEB=true` sabiendo que puede duplicar Discord/scanner.

## Cerebro De Tape Reading

- El volumen de contratos no manda; manda el valor nominal en dolares.
- Separar siempre `STOCK`, `ETF` e `INDEX`.
- SPX/SPXW/NDX/RUT/VIX son otro producto y no deben mezclarse con stocks.
- ETFs pueden ser hedge; requieren threshold mas alto que stocks.
- Single-leg es la senal direccional mas limpia.
- Multi-leg reduce la claridad direccional.
- Delta 0.30-0.70 es zona de conviccion.
- OTM extremo no se descarta automaticamente si hay escalera, flujo repetido, OI y net premium validando.
- OI day-over-day confirma que la posicion fue abierta y sostenida.
- Flujo repetido en el mismo contrato puede convertir prints de 100K en una senal institucional acumulada.
- Escalera de strikes puede mostrar el camino esperado del movimiento.
- Rollover tracking intenta seguir a la ballena hacia el siguiente destino.
- Macro events como FOMC/CPI/NFP/OPEX reducen o silencian confianza.

## Riesgos Pendientes

- Rotar tokens expuestos en chats o screenshots.
- Configurar Railway con dos servicios antes del siguiente deploy: web y worker.
- Revisar endpoints exactos de UW para `INDEX` y SPX antes de crear modulo SPX.
- Crear `/daytrading` solo despues de definir el modelo de contratos monitoreados en tiempo real.
- Considerar Postgres administrado para produccion; SQLite en Railway puede perder estado entre deploys.
