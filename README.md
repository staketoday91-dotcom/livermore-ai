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

## Comandos Locales

Instalar dependencias:

```bash
py -3.11 -m pip install -r requirements.txt
```

Web/API:

```bash
py -3.11 main.py
```

Worker Discord + scanner:

```bash
py -3.11 worker.py
```

Si necesitas correr todo en un solo proceso solo para desarrollo:

```bash
RUN_WORKER_IN_WEB=true py -3.11 main.py
```

## Railway

Configura dos servicios apuntando al mismo repo:

- Web start command: `python main.py`
- Worker start command: `python worker.py`

Variables requeridas:

- `UNUSUAL_WHALES_TOKEN`
- `DISCORD_BOT_TOKEN` solo en el worker
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
