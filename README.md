# Livermore AI

Terminal de tape reading basado en Unusual Whales como fuente unica.

## Arquitectura Oficial

El proyecto corre en dos procesos separados:

- **Web/API**: `main.py`
  - Dashboard, paginas `/backtesting`, `/alerts`, `/watchlist`
  - Endpoints `/api/*`
  - No conecta Discord ni scheduler por defecto
- **Worker**: `worker.py`
  - Unico proceso oficial para Discord bot
  - Scanner cada 5 minutos en market hours
  - Publica alertas a Discord

Esto evita bots duplicados y scans repetidos entre local, Railway u otros hosts.

## Produccion (oficial)

**URL:** https://livermore-ai.onrender.com

Un solo servicio web en Render (o Railway con `python railway_entry.py`):

- Dashboard + API + Discord + scanner
- En cloud se activan solos (`RENDER` / `RAILWAY_*` detectados en `core/runtime.py`)
- Variables: `UNUSUAL_WHALES_TOKEN`, `DISCORD_BOT_TOKEN`, canales `DISCORD_*`, `DATABASE_URL`

**No correr Livermore en local** salvo depuracion puntual:

```bash
LIVERMORE_ALLOW_LOCAL=true RUN_WORKER_IN_WEB=true py -3.11 main.py
```

Detener cualquier proceso local olvidado:

```powershell
.\scripts\stop_local_livermore.ps1
```

## Railway (opcional)

- Servicio unico: start `python railway_entry.py`, `LIVERMORE_SERVICE=web` (default)
- Servicio worker legacy: `LIVERMORE_SERVICE=worker` — desaconsejado si el web ya lleva Discord

Variables requeridas:

- `UNUSUAL_WHALES_TOKEN`
- `DISCORD_BOT_TOKEN` en el servicio web (cloud)
- `DISCORD_GUILD_ID`
- `DISCORD_FREE_CHANNEL`
- `DISCORD_TIER1_CHANNEL`
- `DISCORD_TIER2_CHANNEL`
- `DISCORD_TIER3_CHANNEL`
- `DISCORD_VIP_CHANNEL`
- `DISCORD_VICTORIES_CHANNEL`
- `DISCORD_MOTIVACION_CHANNEL`
- `DATABASE_URL`
- `MAX_SCAN_TICKERS` default `20`
- `SCAN_TICKER_DELAY_SECONDS` default `4.0`

## Seguridad

No subas `.env`, tokens ni URLs con passwords. Si un token se pegó en chats,
screenshots o commits, rótalo desde el proveedor.

## Tape Reading Implementado

- Valor nominal en dolares por contrato
- Thresholds separados para `STOCK`, `ETF`, `INDEX`
- OI day-over-day como multiplicador de conviccion
- Single-leg vs multi-leg
- Delta 0.30-0.70 como zona de conviccion
- Escalera de option chain y gaps en puts
- Flujo repetido acumulado por contrato
- Rollover tracking
- Macro calendar para FOMC/CPI/NFP/OPEX
- P&L real de opciones para backtesting
