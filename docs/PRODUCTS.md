# Dos productos, una doctrina

## Livermore AI (web / pago)

- Código: `main.py`, `core/*`, `worker.py`
- URL: Render → https://livermore-ai.onrender.com
- Rol: escanear Unusual Whales, puntuar oportunidades, alertar suscriptores en internet
- Chat: **Livermore Advisor** → `/advisor` y `POST /api/chat` (API UW, no el chat de la web UW)

## Antigravity / Aetheris (local / empresa)

- Código: `app.py`, `antigravity/*`
- Rol: agentes internos especializados (macro, sector, ballenas, comité, etc.)
- Chat: **Aetheris** en Streamlit — lee la base unificada de agentes

## Reglas compartidas

Archivo único: `core/institutional_rules.py`

- Tape reading (nominal en USD, STOCK/ETF/INDEX, single-leg, delta, OI, macro…)
- Tiers fijos: ALERT 75+, PREMIUM 85+, LIVERMORE 95+
- Única flexión permitida: `LIVERMORE_PREMIUM_RELAX` (default 0.85) en **pisos mínimos de premium**

## Render recomendado

1. **livermore-ai** (web): `python main.py` o uvicorn
2. Variables: `DATABASE_URL`, `UNUSUAL_WHALES_TOKEN`, `ENABLE_LIVERMORE_SCANNER=true` (o servicio worker aparte)
3. **livermore-worker** (opcional): start `python worker.py` + `DISCORD_BOT_TOKEN`
