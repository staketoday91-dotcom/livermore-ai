# Memoria permanente — cómo recuperar chats y no volver a perder nada

**Regla de oro:** Lo que no está en **Git** (`docs/doctrine/`) no existe para Cursor mañana.

Los chats (Claude, Cursor, Gemini) son **borradores**. El repo es el **cerebro**.

---

## Las tres capas (usa las tres)

| Capa | Qué es | Qué olvida |
|------|--------|------------|
| **1. Repo `docs/doctrine/`** | Verdad de Jorge: ICC, contratos, Flash/Tape/Auto | Nada si haces commit |
| **2. Reglas Cursor** (`.cursor/rules/`) | Obliga a leer doctrina antes de codificar | Solo apunta al repo; no sustituye escribir doctrina |
| **3. Tu ritual al cerrar sesión** | “Volca esto en doctrine” | Si saltas el ritual, se pierde |

**Cursor Memories / memoria del IDE:** útil como recordatorio tuyo, **no** sustituye archivos en el repo. Pueden contradecirse entre sí. La fuente legal es siempre `docs/doctrine/`.

---

## Cómo recuperar lo aprendido en chats anteriores

### A) Chats de **Claude** (donde estaban los artículos e ICC)

1. En [claude.ai](https://claude.ai) abre cada conversación importante (ICC, contratos, tape).
2. **Exporta o copia** el hilo (Claude → menú del chat → compartir/exportar si está disponible; si no, seleccionar todo y copiar).
3. Pega en Cursor con:

```
Lee este chat exportado. Extrae SOLO reglas accionables (checklist).
Volca en docs/doctrine/03-escoger-contratos.md y 02-icc.md.
Añade fila en docs/doctrine/04-fuentes.md. Changelog en JORGE_DOCTRINE.md.
No inventes nada que no esté en el texto.
```

4. Opcional: guarda el `.md` crudo en `docs/doctrine/sources/claude-YYYY-MM-DD-tema.md`.

### B) Chats de **Cursor** (este proyecto)

Hay transcripts locales en:

`%USERPROFILE%\.cursor\projects\c-Users-mcgre-Downloads-livermore-ai-v2\agent-transcripts\`

Cada carpeta UUID tiene un `.jsonl`. Sirven sobre todo para **decisiones de código** de las últimas semanas, no para artículos largos de Claude.

Pedido útil (una vez):

```
Recorre agent-transcripts de este proyecto. Busca enseñanzas de Jorge sobre ICC, contratos, tape, Flash.
Resume en docs/doctrine/ solo lo que sea regla explícita. Marca el resto PENDIENTE.
```

### C) Lo que **ya** quedó destilado sin los chats

| Lugar | Qué recuperar |
|-------|----------------|
| `core/institutional_rules.py` | Principios tape (nominal, delta, OI, escalera…) |
| `core/icc_engine.py` | Lógica ICC en código |
| `core/blind_spots.py` | 20 puntos ciegos |
| `docs/LIVERMORE_BRAIN.md` | Producto, tiers |
| `4_whale_catcher.py` | Filtros Flash-like UW |
| Commits viejos `git log` | Qué se implementó y cuándo |

Pedido:

```
Compara institutional_rules.py + icc_engine.py con docs/doctrine/.
Lista qué reglas ya están en código pero NO en doctrine (gaps).
Propón texto para doctrine sin cambiar código aún.
```

### D) PDFs / artículos originales

Copia a `docs/doctrine/sources/` y enlaza en `04-fuentes.md`.  
Resumen obligatorio en `03-escoger-contratos.md` (5–15 bullets por artículo).

---

## Ritual para que solo aprenda más (nunca sustituir)

Al **final de cada sesión** donde enseñes algo:

1. Rellenar [`doctrine/_plantilla-sesion.md`](doctrine/_plantilla-sesion.md) (copiar → nuevo archivo `doctrine/sesiones/YYYY-MM-DD-icc.md` si quieres historial).
2. Fusionar reglas nuevas en el `.md` “vivo” (`02-icc.md`, `03-escoger-contratos.md`, etc.).
3. Una línea en **Changelog** de [`JORGE_DOCTRINE.md`](JORGE_DOCTRINE.md).
4. `git commit` con mensaje: `docs: doctrina ICC — sesión Jorge` (cuando pidas commit).

**Prohibido en doctrina:** borrar reglas viejas sin marcar `OBSOLETO (fecha): …`. Solo **añadir** o **aclarar**.

---

## Frases que debes usar (copiar/pegar)

**Abrir cualquier sesión Cursor en Livermore:**

```
Lee docs/JORGE_DOCTRINE.md, docs/MEMORIA_PERMANENTE.md y docs/doctrine/.
Tipo C. No inventes reglas de tape.
```

**Después de enseñar (ICC, artículos, un trade ejemplo):**

```
Cierra sesión: volca TODO lo que acabo de enseñar en docs/doctrine/.
Usa _plantilla-sesion.md. Actualiza changelog. Lista PENDIENTE si falta detalle.
```

**Recuperación masiva Claude:**

Pega en cada chat antiguo el prompt completo de [`doctrine/PROMPT_VOLCAR_CHAT.md`](doctrine/PROMPT_VOLCAR_CHAT.md), luego fusiona en Cursor.

```
Tengo N volcados de chats. Fusiona en docs/doctrine/ sin inventar. Actualiza changelog.
[Pega respuestas]
```

---

## Qué NO hace falta

- Reescribir el producto entero cada mes.
- Confiar en “el agente ya lo sabe” sin archivo en repo.
- Mezclar Forge Sanchez y Livermore en la misma nota de doctrina (ver `docs/PROJECTS.md`).

---

## Orden sugerido de recuperación (una tarde)

1. Exportar **3–5 chats Claude** más importantes (ICC + contratos + Flash).
2. Volcar con Cursor a `docs/doctrine/`.
3. Pasada de código → doctrine (gaps).
4. Enseñar ICC en vivo en Cursor y volcar al momento en `02-icc.md`.
5. Commit → GitHub = memoria que no se pierde aunque cambies de PC.

Cuando `doctrine/` esté razonablemente lleno, el siguiente paso de ingeniería es `core/jorge_pipeline.py` (tipo C en código), leyendo **solo** esos archivos.
