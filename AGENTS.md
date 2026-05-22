# Agentes en este repositorio

## Livermore AI (producto principal)

| Agente | Rol |
|--------|-----|
| **Cursor** | Único implementador: features, fixes, deploy, docs |
| **Usuario (Jorge)** | Prioridades, negocio, Render env vars, Discord |
| **Claude / otros** | Opcional: ideas y tape reading; **no** editan este repo |

Contexto obligatorio para Cursor:

- `docs/LIVERMORE_BRAIN.md` — decisiones y mapa del sistema
- `docs/CURSOR_WORKFLOW.md` — cómo trabajar sin doble agente
- `core/institutional_rules.py` — reglas en código

## Antigravity (laboratorio local, opcional)

Streamlit + agentes en `antigravity/` y `app.py`. No es el servicio de pago en Render.
