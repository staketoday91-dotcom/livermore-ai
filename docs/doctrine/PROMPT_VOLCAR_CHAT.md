# Prompt — volcar chat a doctrina Livermore

Copia **todo el bloque** de abajo y pégalo al final de un chat antiguo (Claude, Cursor, etc.).  
Luego lleva la respuesta a este repo (tú o Cursor en `livermore-ai-v2`).

---

## Prompt (copiar desde aquí)

```
Eres un archivista de doctrina para Livermore AI (tape reading de Jorge Sanchez, tipo C).

CONTEXTO DEL REPO (no inventes rutas ni producto distinto):
- Cerebro: docs/JORGE_DOCTRINE.md
- Doctrina viva: docs/doctrine/
  - 01-flash-tape-auto.md → fase Flash y Auto
  - 02-icc.md → ICC (Indication, Correction, Continuation) y alineación con gráfico
  - 03-escoger-contratos.md → cómo elegir contratos OCC a seguir
  - 04-fuentes.md → tabla de fuentes
  - sesiones/ → copia cruda de esta sesión (opcional)
- Pipeline objetivo: Flash → Tape → reglas Jorge → Auto (NO GBDS genérico como única verdad)
- Unidad: contrato OCC + nominal USD; feed UW global (cualquier ticker), no scan fijo de tickers

TAREA:
1. Lee TODO este hilo de conversación de arriba a abajo.
2. Extrae SOLO lo que Jorge enseñó o acordó explícitamente sobre tape, flujo UW, ICC, contratos, alertas, filtros, descartes, niveles, macro, OI, delta, escalera, dark pool, Flash/Tape/Auto.
3. NO inventes reglas que no aparezcan en el chat. Si algo es ambiguo, ponlo en "PENDIENTE — aclarar con Jorge".
4. NO mezcles Forge Sanchez / Forge Chuki con Livermore.
5. Ignora código, deploy, UI, Hallmark, Render salvo que Jorge haya ligado una regla de tape a ello.

FORMATO DE RESPUESTA (obligatorio, en español, markdown):

---

## META
- Título de la sesión: [inferir del chat]
- Fecha del chat (si aparece): [o "desconocida"]
- Temas: [ICC | contratos | Flash/Tape/Auto | UW | otro]

---

## PARA docs/doctrine/04-fuentes.md (una fila de tabla)
| Título | Resumen 1 línea | Archivo chat |
|--------|-----------------|--------------|

---

## PARA docs/doctrine/02-icc.md (solo si este chat habla de ICC)
### Reglas nuevas o aclaraciones
- [ ] checklist numerada

### Descartes / nunca
-

### PENDIENTE
-

---

## PARA docs/doctrine/03-escoger-contratos.md (solo si habla de elegir contratos)
### Reglas nuevas
-

### Umbrales (premium, delta, DTE, OI, ask %, etc.)
-

### Descartes explícitos
-

### PENDIENTE
-

---

## PARA docs/doctrine/01-flash-tape-auto.md (solo si habla de filtro rápido o publicar)
### Flash (filtro 5 segundos)
-

### Auto (cuándo publicar alerta)
-

### PENDIENTE
-

---

## PARA docs/doctrine/sesiones/ARCHIVO.md (resumen completo de la sesión)
Usa la plantilla: resumen 5–15 líneas, reglas accionables, descartes, impacto código sugerido.

---

## CHANGELOG (una línea para docs/JORGE_DOCTRINE.md)
| Fecha | Cambio |
|-------|--------|
| YYYY-MM-DD | Volcado desde chat: [título] |

---

## CONFLICTOS con reglas típicas de código (solo listar, no resolver)
Si el chat contradice algo como "solo CONTINUATION" o "scan 12 tickers", cítalo aquí para que Jorge decida.

---

Al terminar, di: "Listo para pegar en livermore-ai-v2/docs/doctrine/. Siguiente paso: commit o pedir a Cursor que fusione sin inventar."
```

---

## Después de pegar el prompt

1. Copia la respuesta del chat.
2. En Cursor (`livermore-ai-v2`), di:

```
Fusiona este volcado en docs/doctrine/ sin inventar ni borrar reglas viejas.
Marca OBSOLETO si hay contradicción. Actualiza changelog en JORGE_DOCTRINE.md.

[Pega aquí la respuesta completa]
```

3. Revisa tú los ítems `PENDIENTE`.
4. `git commit` cuando estés conforme.

---

## Versión corta (si el chat es enorme)

```
Archivista Livermore: lee todo el hilo. Extrae solo reglas de tape/ICC/contratos que Jorge enseñó (no inventes). Salida en markdown para docs/doctrine/02-icc.md, 03-escoger-contratos.md, 01-flash-tape-auto.md, 04-fuentes.md y changelog. Secciones vacías = omitir. PENDIENTE si falta claridad.
```
