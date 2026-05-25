# Sesión 2026-05-25 — ICC Escuela Entera (14 capítulos)

## Resumen

Jorge volcó la enseñanza completa de **ICC** (Indication → Correction → Continuation) desde los textos de la escuela (capítulos 1–14). La doctrina vive en [`../02-icc.md`](../02-icc.md). Livermore debe alinear alertas **solo en CONTINUATION**, con 4H > 1H > 15m, y rechazar flujo contra gráfico.

## Reglas accionables (top)

1. No operar/alertar indicación ni corrección — solo continuación.  
2. Marcar swings en 1H (1–3 sesiones); NTZ hasta ruptura.  
3. 4H gana sobre 1H; 15m solo para fin de corrección y entrada.  
4. Confluencia 6/6 para máxima confianza humana; Auto mínimo 1H+CONTINUATION+flujo alineado.  
5. Seguir precio; fakeout vs reversión = estructura sostenida + HL/LH tras ruptura.  

## Impacto código sugerido

| Prioridad | Tarea |
|-----------|--------|
| P0 | Sustituir proxy `net_premium_continuation` por velas 1H + `ICCDetector` o detector swing-MTF |
| P1 | Añadir capa 4H trend + veto `icc_mtf_conflict` en pipeline |
| P2 | Session filter (NY/London) en Auto |
| P3 | Documentar en UI fase ICC y razón de rechazo |

## Fuente

`C:\Users\mcgre\Downloads\ICC ESCUELA ENTERA\files (1)\Capitulo_*.txt` — ver [`../04-fuentes.md`](../04-fuentes.md).
