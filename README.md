# Livermore AI — Deployment Guide

## Stack
- **Backend**: FastAPI + Python (Render Web Service)
- **Database**: PostgreSQL (Render — ya creada: ForgeBot)
- **Discord**: Bot con alertas y mensajes automáticos
- **Data**: Polygon.io + Tradier + Unusual Whales

---

## Paso 1 — Subir código a GitHub

1. Crea un repo en github.com llamado `livermore-ai`
2. Sube todos estos archivos al repo
3. En Render → conecta el repo de GitHub

---

## Paso 2 — API Keys necesarias

### Polygon.io (precio del subyacente)
1. Ve a polygon.io/dashboard
2. Crea cuenta gratuita o paga ($29/mes)
3. Copia el API key

### Tradier (opciones y Greeks)
1. Ve a tradier.com
2. Crea cuenta de brokerage (gratis)
3. En Developer → API Access → copia el token

### Unusual Whales (flujo institucional)
1. Entra a unusualwhales.com con tu cuenta basis
2. Ve a Settings → API
3. Copia el bearer token

### Discord Bot
1. Ve a discord.com/developers/applications
2. Crea "New Application" → llámala "Livermore AI"
3. Ve a Bot → "Add Bot" → copia el token
4. En OAuth2 → URL Generator:
   - Scopes: bot, applications.commands
   - Permissions: Send Messages, Embed Links, Manage Roles
5. Usa la URL generada para invitar el bot a tu servidor

---

## Paso 3 — IDs de Discord

En tu servidor Discord (modo desarrollador activado):
- Click derecho al servidor → "Copy Server ID" = GUILD_ID
- Click derecho a cada canal → "Copy Channel ID"
- Click derecho a cada rol → "Copy Role ID"

Canales a crear en Discord:
- #alertas-free (público)
- #alertas-tier1 (rol Tier1)
- #alertas-tier2 (rol Tier2)
- #alertas-vip (rol Tier3)
- #sala-de-victorias (público)
- #motivacion-livermore (público)

---

## Paso 4 — Variables en Render

En Render → tu Web Service → Environment:
Agrega cada variable del archivo .env.example con sus valores reales.

---

## Paso 5 — Deploy

1. En Render → New → Web Service
2. Conecta tu repo de GitHub
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `python main.py`
5. Agrega todas las environment variables
6. Click Deploy

El sistema arranca, crea las tablas en la DB, conecta el bot de Discord,
y empieza a escanear automáticamente cada 5 minutos durante market hours.

---

## URLs después del deploy

- Dashboard: https://livermore-ai.onrender.com
- API docs: https://livermore-ai.onrender.com/docs
- Health: https://livermore-ai.onrender.com/health
- Stats: https://livermore-ai.onrender.com/api/stats
- Alerts: https://livermore-ai.onrender.com/api/alerts

---

## Estructura de archivos

```
livermore/
├── main.py              # FastAPI app + scheduler
├── requirements.txt     # Dependencies
├── render.yaml          # Render config
├── .env.example         # Variables template
├── core/
│   ├── models.py        # Database tables
│   ├── icc_engine.py    # ICC pattern detection
│   ├── scorer.py        # Livermore scoring engine
│   ├── fetcher.py       # Polygon + Tradier + UW data
│   └── scanner.py       # Main scan loop
├── bot/
│   └── discord_bot.py   # Discord bot + alerts
└── static/
    └── index.html       # Dashboard (próximo paso)
```
