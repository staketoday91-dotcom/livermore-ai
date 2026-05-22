# Proyectos separados (memoria del programa)

Jorge define **dos productos distintos**. No mezclar alcance, deploy, ni branding en una sola tarea.

---

## 1. Livermore AI

| | |
|--|--|
| **Qué es** | Terminal web de tape reading para **suscriptores de pago** |
| **Código en este repo** | `main.py`, `core/*`, `worker.py`, `bot/*` |
| **Producción** | https://livermore-ai.onrender.com |
| **Chat producto** | Livermore Advisor (`/advisor`) |
| **Discord** | Bot Livermore, canales por tier (servidor del negocio, no confundir con Antigravity) |

Documentación: `docs/LIVERMORE_BRAIN.md`, `PROJECT_CHECKPOINT.md`

---

## 2. Antigravity

| | |
|--|--|
| **Qué es** | Sistema **local** de agentes + dashboard Streamlit (mesa interna) |
| **Nombre del proyecto** | **Antigravity** (el sistema/agentes; no renombrar el proyecto a Forge Sanchez) |
| **Código en este repo (por ahora)** | `app.py`, `antigravity/*`, scripts `1_*.py`…`7_*.py` |
| **Chat / mentora** | **Aetheris** — también se llama **Forge Sanchez** (marca del asistente en Streamlit) |
| **Producción** | Local / futuro repo propio — **no** es Livermore en Render |

**Forge Sanchez** = nombre de marca del chat (Aetheris). **Antigravity** = nombre del proyecto de software.

Documentación futura: `docs/ANTIGRAVITY_BRAIN.md` (cuando exista; separado del brain de Livermore).

---

## Doctrina compartida (solo concepto)

Ambos pueden compartir **ideas** de tape reading (nominal USD, contrato, tiers).  
Eso **no** significa un solo producto ni un solo deploy.

- Código compartido hoy: `core/institutional_rules.py` (conveniencia en un mono-repo).
- Cambios en Livermore **no** deben romper Antigravity sin decisión explícita, y viceversa.

---

## Regla para Cursor

- Tarea “Livermore” → solo archivos Livermore + Render + Discord bot Livermore.
- Tarea “Antigravity” → solo `app.py`, `antigravity/`, DB local, Streamlit.
- **Nunca** renombrar el proyecto Antigravity a Forge Sanchez; sí usar **Forge Sanchez** como nombre del chat junto con Aetheris.
