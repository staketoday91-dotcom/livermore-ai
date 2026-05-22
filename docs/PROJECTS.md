# Proyectos separados (memoria del programa)

Jorge define **dos productos distintos**. No mezclar alcance, deploy, ni branding en una sola tarea.

---

## 1. Livermore AI

| | |
|--|--|
| **Qué es** | Terminal web de tape reading para **suscriptores de pago** |
| **Código en este repo** | `main.py`, `core/*`, `worker.py`, `bot/*` |
| **Producción** | https://livermore-ai.onrender.com |
| **IA / chat** | **Livermore Advisor** |
| **Discord** | Bot Livermore (canales por tier) |

Documentación: `docs/LIVERMORE_BRAIN.md`, `PROJECT_CHECKPOINT.md`

---

## 2. Forge Sanchez

| | |
|--|--|
| **Nombre del proyecto** | **Forge Sanchez** |
| **Qué es** | Sistema **local** de agentes + dashboard Streamlit (mesa interna) |
| **IA / mentora** | **Forge Chuki** (antes “Aetheris” en código legado) |
| **Código en este repo (por ahora)** | `app.py`, carpeta `antigravity/*`, scripts `1_*.py`…`7_*.py` |
| **Producción** | Local / futuro repo propio — **no** es Livermore en Render |

> La carpeta Python `antigravity/` es nombre técnico histórico; el producto se llama **Forge Sanchez**.

Documentación futura: `docs/FORGE_SANCHEZ_BRAIN.md` (separado del brain de Livermore).

---

## Doctrina compartida (solo concepto)

Ambos pueden compartir **ideas** de tape reading (nominal USD, contrato, tiers).  
Eso **no** significa un solo producto ni un solo deploy.

- Código compartido hoy: `core/institutional_rules.py` (conveniencia en un mono-repo).
- Cambios en Livermore **no** deben romper Forge Sanchez sin decisión explícita, y viceversa.

---

## Regla para Cursor

- Tarea **Livermore** → `main.py`, `core/*`, Render, Discord bot Livermore.
- Tarea **Forge Sanchez** → `app.py`, `antigravity/`, DB local, Streamlit; IA = **Forge Chuki**.
- **No** mezclar Livermore AI con Forge Sanchez / Forge Chuki en la misma tarea salvo petición explícita.
