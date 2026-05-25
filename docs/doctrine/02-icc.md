# ICC — Indication · Correction · Continuation

**Fuente:** ICC Escuela Entera (14 capítulos, Jorge). Archivos originales en `04-fuentes.md`.  
**Propósito en Livermore:** alinear **gráfico + fase ICC** antes de publicar una alerta (tipo C). El flujo UW **no sustituye** la estructura de precio.

---

## Definición (Jorge / ICC Escuela)

ICC no es una estrategia nueva ni “break & retest” simplificado. Es **price action y estructura de mercado** en tres fases:

| Fase | Qué es | Rol del trader |
|------|--------|----------------|
| **Indication** | Ruptura de un **swing high/low** (nuevo HH o nuevo LL). Inicio o cambio de impulso. | **Información.** No operar aquí. |
| **Correction** | Retiro tras el nuevo high/low; el mercado **toma liquidez** (FOMO del breakout). | **Observar.** Monitorear fin de corrección (15m). |
| **Continuation** | El precio retoma la dirección original **después** de la corrección, con estructura confirmada. | **Entrada / alerta.** Aquí publica Livermore (Auto). |

**Ciclo:** Indication → Correction → Continuation → (nueva) Indication → …

**Regla de oro:** No tradear la indicación. Esperar continuación = mejor entrada, menos fakeouts, mejor R:R.

---

## Estructura de mercado (base)

### Tendencias

- **Uptrend:** Higher Highs (HH) + Higher Lows (HL).
- **Downtrend:** Lower Highs (LH) + Lower Lows (LL).
- **Consolidación:** highs/lows planos, sin dirección clara → **no tradear / no alertar**.

El precio respeta la secuencia mientras el trend sea válido. Si se rompe la secuencia obligatoria en el TF que operas → trend en peligro o reversión.

### Swings

- **Swing high:** máximo donde el precio rechaza y gira.
- **Swing low:** mínimo donde el precio rechaza y gira.
- Marcar con **cierre de cuerpo**, no wicks aislados (el cierre = decisión; el wick = intento fallido).

### No Trade Zone (NTZ)

Entre el swing high y swing low recientes **sin ruptura** = equilibrio, sin dirección.

- **Termina NTZ** cuando el precio rompe **arriba del high** (potencial bullish) o **debajo del low** (potencial bearish).
- Esa ruptura = **indicación** (aún no es entrada).

### Poder en niveles

- **Arriba de un swing low** → potencial **bullish** (compradores mantuvieron).
- **Debajo de un swing high** → potencial **bearish** (vendedores mantuvieron).
- Tras barrer vendedores (romper high), el viejo high suele actuar como **soporte** (y viceversa).

### Break & retest vs ICC

| Break & retest (clásico) | ICC (Jorge) |
|--------------------------|-------------|
| Rompe → retestea el mismo nivel → sigue | Rompe (indicación) → corrección (liquidez) → **segunda** ruptura/confirmación (continuación) |
| Entrada en retest = riesgo de liquidación | Entrada en **continuación** con HL/LH confirmando |

---

## Timeframes (jerarquía)

| TF | Uso |
|----|-----|
| **4H** | Tendencia / contexto. **Gana** sobre 1H si hay conflicto. |
| **1H** | TF base: marcar swings, indicación, plan del trade. |
| **15m** | Solo durante **corrección** (¿terminó?) y **continuación** (entrada fina). |
| **5m** | Opcional: precisión / scaling; debe alinear con 15m y 1H. |
| **Daily / Weekly** | Contexto largo; no para entradas intradía salvo swing largo. |

**Regla:** Si 4H bearish y 1H bullish → la subida en 1H puede ser rally temporal; **confiar en 4H**, no alertar long hasta alineación.

**Cambiar de TF solo en:** (1) monitorear corrección, (2) buscar entrada en continuación. No saltar TFs para “buscar” setups.

### Confluencia (checklist 6/6 antes de entrada humana)

1. 4H: indicación clara o trend alineado  
2. 4H: corrección en curso o completada según caso  
3. 1H: alineada con 4H (misma dirección)  
4. 15m: ICC visible (estructura HH/HL o LH/LL en dirección del trade)  
5. Volumen en sesión (ver abajo)  
6. Todos apuntan a la misma dirección  

**Livermore Auto:** exigir al menos **1H + dirección del flujo**; ideal **4H + 1H + fase CONTINUATION**. Si conflicto MTF → `rejection_reason: icc_mtf_conflict`.

### Sesión y volumen

- Operar / alertar con preferencia: **NY open 9:30–10:30 ET**, mediodía 12–14, cierre 15–16.  
- Evitar: pre-market ilíquido, últimos 30–60 min erráticos, madrugada “fake volume”.  
- Instrumentos con movimiento: **SPY, QQQ/NASDAQ, US30, Gold, BTC** — no pares FX muertos.  
- **London session** (8–12 GMT): indicaciones fuertes; confirmar rupturas importantes en **NY** cuando aplique.

---

## Fases en detalle

### 1 — Indication

- Ocurre **solo** al romper un swing high (bullish) o swing low (bearish).
- Responde: ¿cuál es el trend? ¿hacia dónde va el precio?
- Tras la ruptura, el mercado **siempre** intenta tomar liquidez → viene corrección.
- **Livermore:** registrar `icc_phase=INDICATION` en watchlist; **no** `fire_alert`.

### 2 — Correction

- Ocurre **después** de un nuevo high o nuevo low.
- Profundidad variable (no hace falta 50%); basta liquidar stops del FOMO.
- En 1H se ven 1–2 velas; en **15m** se ve la estructura del retroceso.
- **No entrar** en corrección; es información (dónde está la liquidez).
- Fin típico: precio vuelve hacia el nivel donde empezó la indicación **o** falla hacer nuevos extremos en la dirección contraria y retoma impulso.
- **Livermore:** `icc_phase=CORRECTION`; observación / tape, sin Auto.

### 3 — Continuation

- Segunda oportunidad: liquidez ya tomada, estructura confirmada.
- **Uptrend:** HH → corrección → HL → ruptura arriba / HH nuevo.  
- **Downtrend:** LL → corrección → LH → ruptura abajo / LL nuevo.
- Entrada preferida: ruptura **1H**; refinamiento en **15m** (HH/HL bullish o LH/LL bearish + vuelta bajo/encima del nivel 1H).
- **Stop loss:** debajo del último HL (long) o encima del último LH (short) — donde la **idea** se invalida, no un pip arbitrario.
- **TP inicial:** nivel de la indicación (swing roto); si trend válido, buscar extensiones (soft TP: parciales 33/33/33).
- **Livermore:** **solo** `icc_phase=CONTINUATION` + confluencia para **Auto** (coincide con `scanner.py` línea ~343).

### Entrada perfecta (6 elementos — checklist humano)

1. Indicación clara (nuevo HH o LL)  
2. Corrección visible  
3. Confirmación en TF bajo (15m/5m) de giro a favor  
4. SL en estructura 1H  
5. TP objetivo en nivel 1H  
6. Trend confirmado (HH+HL o LH+LL)  

Si falta alguno → esperar.

---

## Reversiones de trend

**Advertencia (no entrada):**

- Downtrend: aparece **higher low** (rompe secuencia LL).  
- Uptrend: aparece **lower high** (rompe secuencia HH).  

**Confirmación de reversión:**

- Movimiento opuesto sostenido: nuevo HH en ex-downtrend o nuevo LL en ex-uptrend.  
- ICC completo en la **nueva** dirección + volumen en sesión.  
- Entrar en **continuación**, no en la primera ruptura.  

**Fakeout vs reversión:**

- Fakeout: rompe, toma liquidez, vuelve al trend anterior.  
- Reversión real: rompe estructura y **sigue** con HH/HL (o LH/LL) en la nueva dirección; tras ruptura alcista, **higher low** confirma (y viceversa).

**ATH / liquidez extrema:** ser escéptico — R:R malo, liquidaciones impredecibles; preferir pullback con confluencia.

**Rechazos repetidos en un nivel** (2–3 toques sin romper): debilidad en esa dirección; preparar cambio o no alertar a favor.

---

## Psicología y decisión (aplica a filtrar alertas)

- **Seguir el precio**, no predecir. Si el flujo dice call pero 1H rompe soporte → no forzar long.  
- **Paciencia:** 6–7 trades/mes bien ejecutados > 30 trades ruido.  
- **Calidad > cantidad** en Auto.  
- **Posicionamiento:** entrada en confluencia = opciones (scale out, aguantar); entrada en indicación = liquidación probable.  
- **4H siempre gana** sobre 1H en conflicto.  
- Sin “nuevo incentivo” (nuevo HH/LL en la dirección del trade) → probabilidad baja; esperar.

---

## Cómo marcar gráficos (resumen operativo)

1. Gráfico **limpio** — sin 50 indicadores.  
2. Solo **1–3 sesiones** recientes (días), no meses de historia.  
3. Marcar **3–5 swings principales** (cajas/líneas en 1H).  
4. Determinar: uptrend / downtrend / consolidación / NTZ.  
5. Esperar ruptura (indicación) → corrección → bajar a 15m → entrar/alertar en continuación.  
6. Actualizar marcas **en tiempo real** mientras el día avanza.  
7. Alerts en niveles clave (TradingView); analizar cuando disparan, no mirar pantalla 8h.

---

## Livermore: ICC + flujo UW (tipo C)

| Capa | ICC / gráfico | Flujo UW |
|------|----------------|----------|
| **Flash** | Opcional: ticker en NTZ vs ya con indicación | Premium, vol/OI, sweep, single-leg |
| **Tape** | Fase ICC + swings 1H; 4H contexto; 15m para continuación | Contrato OCC, OI, delta, DP, macro |
| **Auto** | **Solo CONTINUATION** + MTF alineado + sesión/volumen | Dirección del flujo **alineada** con ICC (no contra 4H) |

### Reglas de publicación (Auto)

- [x] **No alertar** en INDICATION ni CORRECTION (doctrina + código actual).  
- [x] **Alertar** solo si `icc_phase == CONTINUATION`.  
- [ ] **Obligatorio:** velas 1H reales (UW/Polygon) vía `ICCDetector` — hoy scanner usa **proxy** net premium (`icc_signal: net_premium_continuation`). **PENDIENTE** sustituir por detección swing+MTF.  
- [ ] **4H:** clasificar trend antes de 1H; veto si conflicto.  
- [ ] **Consolidación / CHOP:** `RegimeDetector` ADX — no ICC en chop (`is_valid_for_icc`).  
- [ ] **Regime:** correlacionar con `blind_spots` y macro.  

### Dirección del flujo vs gráfico

| Flujo UW | Gráfico 1H/4H | Acción Auto |
|----------|---------------|-------------|
| Bullish (calls) | Bullish continuation | Permitir alerta long/calls |
| Bearish (puts) | Bearish continuation | Permitir alerta short/puts |
| Bullish | Bearish continuation | **Rechazar** (`flow_chart_mismatch`) |
| Bearish | Bullish continuation | **Rechazar** |
| Cualquiera | INDICATION / CORRECTION | **Rechazar** (`icc_not_continuation`) |
| Cualquiera | Consolidación / NTZ | **Rechazar** (`icc_no_trend`) |

---

## Señales de velas (`icc_engine.py` — Trades by Sci)

El motor en código usa **velas 1H** (cuerpo >60%, volumen, false harami, engulfing, shooting star en AOI). Es **complemento** a la doctrina swing/MTF de la escuela:

| Doctrina escuela | Código actual |
|------------------|---------------|
| Swing break = indicación | Impulse candle + break de highs/lows recientes |
| Corrección a AOI | Retroceso ≤70% del cuerpo de indicación |
| Continuación en AOI | Patrones de vela en zona AOI |

**Prioridad producto:** para alertas tipo C, la **verdad operativa** es esta doctrina (swings + MTF + solo continuación). Alinear `ICCDetector` o capa nueva `icc_structure.py` con swings 1H/4H; mantener patrones de vela como confirmación extra (+score).

---

## Descartes explícitos (nunca Auto)

- Entrada en **breakout solo** (indicación).  
- **Consolidación** / equal highs & lows sin ruptura.  
- **Conflicto 4H vs 1H** sin resolución.  
- Flujo fuerte **contra** continuación ICC.  
- Fuera de sesión con volumen falso (salvo índices 24h con reglas especiales).  
- ATH / noticias caóticas sin estructura clara.  
- Operar “retest” inmediato sin ciclo corrección → continuación.  

---

## Glosario rápido

| Término | Significado |
|---------|-------------|
| HH / HL | Higher high / higher low |
| LH / LL | Lower high / lower low |
| NTZ | No trade zone entre swing high y low |
| AOI | Zona de interés (retroceso post-indicación) |
| Soft TP | Parciales; no TP fijo único en el swing |
| Previous push | Impulso anterior al swing; romperlo = pérdida de momentum |

---

## Changelog

| Fecha | Cambio |
|-------|--------|
| 2026-05-25 | Volcado completo ICC Escuela Entera cap. 1–14 → doctrina operativa Livermore |
