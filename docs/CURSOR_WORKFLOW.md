# Cómo trabajar solo con Cursor en Livermore AI

## Roles

| Rol | Quién | Qué hace |
|-----|--------|----------|
| **Estrategia / tape reading** | Tú (+ Claude si quieres leer ideas) | Define reglas, prioridades, copy Discord |
| **Ingeniería** | **Cursor** (este repo) | Código, tests, commit, push, diagnóstico Render |
| **Producción** | Render | Host de https://livermore-ai.onrender.com |

Claude **no** sustituye a Cursor para editar archivos. Si Claude sugiere un cambio, la instrucción que funciona es:

> “Implementa en `livermore-ai-v2` lo que dice [resumen]. Commit y push a `main`.”

---

## Un solo proyecto

- **Abre siempre:** `C:\Users\mcgre\Downloads\livermore-ai-v2`
- **Git remoto:** `staketoday91-dotcom/livermore-ai`, rama `main`
- **Documento maestro:** `docs/LIVERMORE_BRAIN.md`

No mantengas copias paralelas (`Nueva carpeta`, otro clone viejo) como “verdad”. Si existe, solo es backup tuyo.

---

## Flujo por tarea (5 pasos)

1. **Describe el objetivo** en una frase (ej. “alertas con flow > 0 en producción”).
2. Cursor implementa **en este repo** (no “pega 4 archivos externos”).
3. `git commit` + `git push origin main`.
4. **Manual Deploy** en Render (si aplica).
5. Verificar 3 URLs: `/api/stats`, `/api/watchlist`, `/api/alerts`.

---

## Qué pedirle a Cursor (plantillas)

**Feature:**

```
Implementa [X] en Livermore. Toca solo [archivos]. Commit: "feat: ...". Push main.
```

**Bug producción:**

```
En Render [síntoma]. Diagnostica con código y curl. Fix mínimo. Commit push.
```

**Sincronizar después de Claude:**

```
Lee docs/LIVERMORE_BRAIN.md. [Pega decisión nueva de Claude]. Implementa y actualiza el brain doc. Push main.
```

---

## Qué NO hacer (evita el retraso de antes)

- No reemplazar archivos sueltos desde carpetas de descargas sin revisar el resto del repo.
- No dar a Claude “control” del código — solo ideas.
- No asumir que Render tiene el último commit sin deploy.
- No mezclar Forge Sanchez / XAMPP con bugs de la web de pago en la misma tarea.

---

## Dos proyectos separados (memoria fija)

- **Livermore AI** — web de pago, Render, `main.py` + `core/*`.
- **Forge Sanchez** — proyecto local, agentes, Streamlit; IA **Forge Chuki**.

Detalle: [PROJECTS.md](PROJECTS.md). No mezclar una tarea de ambos.

Forge Sanchez en este repo (`app.py`, `antigravity/`) no bloquea Livermore en Render; trabajar uno u otro por sesión.

---

## Control total de Cursor

Cursor tiene control cuando:

1. Este repo es la única copia activa de Livermore web.
2. Cada cambio termina en **GitHub `main`**.
3. Las decisiones viven en `docs/LIVERMORE_BRAIN.md` + `core/institutional_rules.py`.
4. Tú no vuelves a un segundo agente para “aplicar” el mismo parche.

Para empezar una sesión nueva en Cursor, escribe:

```
Lee docs/LIVERMORE_BRAIN.md y PROJECT_CHECKPOINT.md. Soy Jorge; Livermore es producto de pago en Render. ¿Cuál es el siguiente paso según el brain?
```
