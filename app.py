from datetime import datetime, timedelta

import pandas as pd
import streamlit as streamlit_app

from antigravity.db import (
    AgentRun,
    BacktestContract,
    ContractMonitor,
    MarketRegime,
    OptionFlowSignal,
    RawUwEvent,
    SectorRotation,
    TradePlan,
    init_db,
    session_scope,
)


streamlit_app.set_page_config(page_title="Antigravity Intelligence", layout="wide")
init_db()


def rows(model, limit=10, order_by=None, filters=None):
    with session_scope() as session:
        query = session.query(model)
        if filters:
            for condition in filters:
                query = query.filter(condition)
        if order_by is not None:
            query = query.order_by(order_by)
        return [to_dict(row) for row in query.limit(limit).all()]


def latest(model, order_by):
    data = rows(model, limit=1, order_by=order_by)
    return data[0] if data else None


def count(model, filters=None):
    with session_scope() as session:
        query = session.query(model)
        if filters:
            for condition in filters:
                query = query.filter(condition)
        return query.count()


def to_dict(row):
    return {col.name: getattr(row, col.name) for col in row.__table__.columns}


def money(value):
    value = value or 0
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:,.0f}"


def percent(value):
    if value is None:
        return "N/A"
    return f"{value * 100:.0f}%"


def format_dt(value):
    if value is None or pd.isna(value):
        return "N/A"
    try:
        ts = pd.to_datetime(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M:%S ET")
    except (TypeError, ValueError):
        return str(value)


def live_flows(hours: int = 8, limit: int = 40):
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    with session_scope() as session:
        rows_q = (
            session.query(OptionFlowSignal)
            .filter(OptionFlowSignal.tape_time >= cutoff)
            .order_by(OptionFlowSignal.tape_time.desc())
            .limit(limit)
            .all()
        )
        return [to_dict(row) for row in rows_q]


def latest_whale_run():
    with session_scope() as session:
        run = (
            session.query(AgentRun)
            .filter(AgentRun.agent_name == "whale_scanner_agent")
            .order_by(AgentRun.id.desc())
            .first()
        )
        return to_dict(run) if run else None


def find_ticker_in_prompt(prompt: str):
    words = [word.strip(" ,.?¿!¡:;()[]{}").upper() for word in prompt.split()]
    ignore = {
        "POR",
        "QUE",
        "QUÉ",
        "FUE",
        "NO",
        "APROBADO",
        "DAME",
        "LOS",
        "MEJORES",
        "CANDIDATOS",
        "PLAN",
        "MACRO",
        "FLUJO",
        "CALIFICADO",
        "PUT",
        "CALL",
    }
    for word in words:
        if 1 <= len(word) <= 6 and word.isalnum() and word not in ignore:
            return word
    return None


def find_contract_context(prompt: str):
    q = prompt.lower()
    contract_type = "PUT" if "put" in q else "CALL" if "call" in q else None
    strike = None
    for raw in prompt.replace(",", " ").split():
        try:
            value = float(raw.strip(" ,.?¿!¡:;()[]{}"))
            if value > 0:
                strike = value
                break
        except ValueError:
            continue
    return contract_type, strike


def latest_plan_for_ticker(ticker: str):
    with session_scope() as session:
        plan = (
            session.query(TradePlan)
            .filter(TradePlan.ticker == ticker.upper())
            .order_by(TradePlan.id.desc())
            .first()
        )
        return to_dict(plan) if plan else None


def latest_flow_for_prompt(prompt: str):
    ticker = find_ticker_in_prompt(prompt)
    contract_type, strike = find_contract_context(prompt)
    if not ticker:
        return None

    with session_scope() as session:
        query = session.query(OptionFlowSignal).filter(OptionFlowSignal.ticker == ticker)
        if contract_type:
            query = query.filter(OptionFlowSignal.contract_type == contract_type)
        if strike:
            query = query.filter(OptionFlowSignal.strike.between(strike * 0.995, strike * 1.005))
        flow = query.order_by(OptionFlowSignal.score.desc(), OptionFlowSignal.premium.desc(), OptionFlowSignal.id.desc()).first()
        return to_dict(flow) if flow else None


def top_watchlist(limit=5):
    return rows(TradePlan, limit=limit, order_by=TradePlan.conviction_score.desc(), filters=[TradePlan.execution_status == "WATCHLIST"])


def top_pending_plans(limit=5):
    """Un ticker = un plan activo; el más reciente gana."""
    with session_scope() as session:
        plans = (
            session.query(TradePlan)
            .filter(TradePlan.execution_status == "PENDING")
            .order_by(TradePlan.updated_at.desc(), TradePlan.conviction_score.desc(), TradePlan.id.desc())
            .all()
        )
        seen: set[str] = set()
        unique = []
        for plan in plans:
            if plan.ticker in seen:
                continue
            seen.add(plan.ticker)
            unique.append(to_dict(plan))
            if len(unique) >= limit:
                break
        return unique


def latest_agent_runs_by_name():
    with session_scope() as session:
        latest_ids = {}
        for run in session.query(AgentRun).order_by(AgentRun.id.desc()).all():
            latest_ids.setdefault(run.agent_name, run.id)
        if not latest_ids:
            return []
        runs = session.query(AgentRun).filter(AgentRun.id.in_(latest_ids.values())).order_by(AgentRun.agent_name.asc()).all()
        return [to_dict(run) for run in runs]


def flow_priority(flow):
    if flow.get("score", 0) >= 100 and (flow.get("premium") or 0) >= 1_000_000 and (flow.get("volume_oi_ratio") or 0) >= 5:
        return "SI O SI REVISAR", "#f59e0b"
    if flow.get("score", 0) >= 90 or (flow.get("premium") or 0) >= 1_000_000:
        return "MERECE ATENCION", "#22c55e"
    return "OBSERVAR", "#64748b"


def side_color(side):
    return "#16a34a" if side == "ASK" else "#dc2626" if side == "BID" else "#64748b"


def direction_from_flow(flow):
    if flow.get("contract_type") == "PUT":
        return "SHORT"
    if flow.get("contract_type") == "CALL":
        return "LONG"
    return "UNKNOWN"


def enqueue_contract(model, flow, status, reason_field=None):
    with session_scope() as session:
        existing = (
            session.query(model)
            .filter(
                model.ticker == flow["ticker"],
                model.contract_type == flow.get("contract_type"),
                model.strike == flow.get("strike"),
                model.expiry == flow.get("expiry"),
                model.status == status,
            )
            .first()
        )
        if existing:
            return False

        payload = {
            "ticker": flow["ticker"],
            "contract_symbol": flow.get("contract_symbol"),
            "contract_type": flow.get("contract_type"),
            "strike": flow.get("strike"),
            "expiry": flow.get("expiry"),
            "direction": direction_from_flow(flow),
            "source_signal_id": flow.get("id"),
            "alert_tape_time": flow.get("tape_time"),
            "alert_underlying_price": flow.get("underlying_price"),
            "alert_premium": flow.get("premium"),
            "status": status,
        }
        if reason_field:
            payload[reason_field] = "Añadido desde Radar De Tape Institucional"
        session.add(model(**payload))
        return True


def enqueue_manual_contract(model, ticker, contract_type, strike, expiry, direction, underlying_price, premium, status, reason_field=None):
    payload = {
        "ticker": ticker.upper(),
        "contract_type": contract_type,
        "strike": strike,
        "expiry": expiry,
        "direction": direction,
        "alert_tape_time": pd.Timestamp.utcnow().to_pydatetime().replace(tzinfo=None),
        "alert_underlying_price": underlying_price,
        "alert_premium": premium,
        "status": status,
    }
    if reason_field:
        payload[reason_field] = "Añadido manualmente desde Centro Operativo"
    with session_scope() as session:
        session.add(model(**payload))


def render_flow_card(flow, key_prefix: str = "flow"):
    label, border = flow_priority(flow)
    side = flow.get("side") or "N/A"
    side_bg = side_color(side)
    decision = latest_plan_for_ticker(flow["ticker"])
    decision_status = decision["execution_status"] if decision else "SIN DECISION"
    decision_text = decision.get("target_zone") if decision else "Aun no paso por comite"
    accepted = (flow.get("accepted_reason") or "").replace("SCREENER:", "").strip()
    rejection = flow.get("rejection_reason") or ""
    reason = accepted if flow.get("status") in {"QUALIFIED", "PLANNED"} else rejection
    reason = reason[:220] + "..." if len(reason) > 220 else reason
    alert_rule = ""
    raw = flow.get("raw") or {}
    if isinstance(raw, dict) and raw.get("alert_rule"):
        alert_rule = f" | Regla UW: {raw['alert_rule']}"

    streamlit_app.markdown(
        f"""
        <div style="border: 2px solid {border}; border-radius: 14px; padding: 16px; margin-bottom: 8px; background: #111827; color:#f8fafc; box-shadow: 0 0 0 1px rgba(255,255,255,.06);">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <h4 style="margin:0; color:#f8fafc;">{flow['ticker']} {flow.get('contract_type') or ''} {flow.get('strike') or ''}</h4>
                <span style="background:{border}; color:#111827; padding:4px 10px; border-radius:999px; font-weight:700;">{label}</span>
            </div>
            <div style="margin-top:10px; color:#e5e7eb;">
                <span style="background:{side_bg}; color:white; padding:3px 8px; border-radius:8px;">{side}</span>
                <span style="margin-left:8px;">Premium: <b>{money(flow.get('premium'))}</b></span>
                <span style="margin-left:8px;">Vol/OI: <b>{(flow.get('volume_oi_ratio') or 0):.2f}x</b></span>
                <span style="margin-left:8px;">ASK: <b>{percent(flow.get('ask_side_pct'))}</b></span>
                <span style="margin-left:8px;">Subyacente: <b>{(flow.get('underlying_price') or 0):.2f}</b></span>
            </div>
            <div style="margin-top:8px; color:#facc15;">Hora UW alerta: <b>{format_dt(flow.get('tape_time'))}</b> | Guardado sistema: <b>{format_dt(flow.get('created_at'))}</b>{alert_rule}</div>
            <div style="margin-top:8px; color:#e5e7eb;">Decision: <b>{decision_status}</b> | {decision_text}</div>
            <div style="margin-top:6px; color:#ffffff;">{reason or 'Sin razon registrada'}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    actions = streamlit_app.columns([1, 1, 5])
    if actions[0].button("Monitorear", key=f"{key_prefix}-monitor-{flow['id']}"):
        created = enqueue_contract(ContractMonitor, flow, "ACTIVE", reason_field="watch_reason")
        actions[0].success("Activo" if created else "Ya estaba")
    if actions[1].button("Backtest", key=f"{key_prefix}-backtest-{flow['id']}"):
        created = enqueue_contract(BacktestContract, flow, "QUEUED")
        actions[1].success("En cola" if created else "Ya estaba")


def render_plan_card(plan, expanded=False):
    status = plan["execution_status"]
    updated = format_dt(plan.get("updated_at") or plan.get("created_at"))
    title = f"{plan['ticker']} | {plan['direction']} | {status} | Grade {plan.get('setup_grade') or '-'} | Score {plan['conviction_score']}"
    with streamlit_app.expander(title, expanded=expanded, key=f"plan-{plan['id']}"):
        c1, c2, c3 = streamlit_app.columns(3)
        c1.markdown(f"**Entrada**\n\n`{plan['entry_zone']}`")
        stop_text = f"{plan['stop_loss']:.2f}" if plan.get("stop_loss") else "N/A"
        c2.markdown(f"**Stop estructural**\n\n`{stop_text}`")
        c3.markdown(f"**Target / Bloqueo**\n\n`{plan['target_zone']}`")
        streamlit_app.markdown(f"**Lectura institucional:** {plan.get('approval_reason') or 'Sin tesis registrada'}")
        streamlit_app.markdown(f"**Qué falta / riesgo:** {plan.get('risk_notes') or 'Confirmación pendiente'}")
        streamlit_app.caption(f"Actualizado: {updated} | Invalidación: {plan['invalidation']}")


def prepare_flow_dataframe(data):
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df["premium_display"] = df["premium"].apply(money)
    df["ask_display"] = df["ask_side_pct"].apply(percent)
    return df


def aetheris_reply(prompt: str) -> str:
    q = prompt.lower()
    macro = latest(MarketRegime, MarketRegime.id.desc())
    plans = top_pending_plans(limit=10)
    watchlist = rows(TradePlan, limit=10, order_by=TradePlan.id.desc(), filters=[TradePlan.execution_status == "WATCHLIST"])
    flows_total = count(OptionFlowSignal)
    flows_qualified = count(OptionFlowSignal, [OptionFlowSignal.status.in_(["QUALIFIED", "PLANNED"])])
    flows_rejected = count(OptionFlowSignal, [OptionFlowSignal.status == "OBSERVED_REJECTED"])
    last_rejected = latest(OptionFlowSignal, OptionFlowSignal.id.desc())
    last_error = latest(AgentRun, AgentRun.id.desc())
    uw_429 = rows(RawUwEvent, limit=1, order_by=RawUwEvent.id.desc(), filters=[RawUwEvent.status_code == 429])

    if "ayuda" in q or "puedes" in q or "qué haces" in q or "que haces" in q:
        from core.institutional_rules import PRODUCT_ROLES, principles_block

        return (
            f"Aetheris: {PRODUCT_ROLES['aetheris']}\n\n"
            "Puedo explicarte el sesgo macro, listar los mejores candidatos, revisar por qué un ticker no fue aprobado, "
            "analizar un contrato concreto como 'ORCL put 175', resumir el flujo calificado, detectar errores de agentes "
            "y decirte qué falta para pasar de watchlist a trade.\n\n"
            f"Doctrina compartida con Livermore web:\n{principles_block()}"
        )

    requested_ticker = find_ticker_in_prompt(prompt)
    if requested_ticker and ("por qué" in q or "por que" in q or "porque" in q or "aprob" in q or "rechaz" in q or "watch" in q or "no?" in q):
        flow = latest_flow_for_prompt(prompt)
        plan = latest_plan_for_ticker(requested_ticker)
        flow_context = ""
        if flow:
            flow_context = (
                f" Flujo visto: {flow['contract_type']} strike {flow['strike']}, premium {money(flow['premium'])}, "
                f"ASK {percent(flow['ask_side_pct'])}, Vol/OI {(flow['volume_oi_ratio'] or 0):.2f}x, estado {flow['status']}."
            )
        if plan:
            if plan["execution_status"] == "PENDING":
                return f"Aetheris: {requested_ticker} está aprobado.{flow_context} Razón: {plan.get('approval_reason')}. Riesgo: {plan.get('risk_notes')}. Invalidación: {plan.get('invalidation')}."
            return f"Aetheris: {requested_ticker} no está aprobado; está en estado {plan['execution_status']}.{flow_context} Bloqueo principal: {plan.get('target_zone')}. Lectura positiva: {plan.get('approval_reason')}. Riesgo: {plan.get('risk_notes')}."
        if flow:
            return f"Aetheris: {requested_ticker} aparece en el radar pero no tiene decisión reciente del comité.{flow_context} Necesita pasar por microestructura/comité o no alcanzó los filtros de plan."
        return f"Aetheris: No encuentro una decisión ni flujo reciente para {requested_ticker}."

    if "top" in q or "mejor" in q or "candidato" in q:
        watch = top_watchlist(5)
        if watch:
            summary = "; ".join(f"{item['ticker']} {item['direction']} score {item['conviction_score']}" for item in watch)
            return f"Aetheris: Los mejores candidatos en observación son: {summary}. Ninguno es ejecución automática hasta que resuelva su bloqueo principal."
        return "Aetheris: No hay candidatos en watchlist ahora mismo."

    if "plan" in q or "operar" in q or "comprar" in q:
        if plans:
            tickers = ", ".join(plan["ticker"] for plan in plans)
            return f"Aetheris: El Comité tiene planes pendientes en {tickers}. Revisa stop, target e invalidación antes de ejecutar."
        if watchlist:
            tickers = ", ".join(plan["ticker"] for plan in watchlist[:5])
            return f"Aetheris: No hay trades aprobados, pero hay candidatos en observación: {tickers}. Están esperando que se resuelva su bloqueo principal antes de pasar a ejecución."
        return "Aetheris: No hay planes aprobados. El sistema está protegiendo capital porque aún no existe alineación completa o no han entrado señales válidas."

    if "macro" in q or "clima" in q or "mercado" in q or "risk on" in q or "risk_off" in q or "risk off" in q or "risk_on" in q:
        if macro:
            meaning = "viento a favor para riesgo y compras selectivas" if macro["market_bias"] == "RISK_ON" else "defensa, coberturas y menor agresividad" if macro["market_bias"] == "RISK_OFF" else "zona mixta, operar solo setups muy confirmados"
            return f"Aetheris: Sesgo actual {macro['market_bias']} significa {meaning}. Liquidez {macro['liquidity_index']}, DXY {macro['dxy_trend']} y VIX {macro['vix_level']:.2f}."
        return "Aetheris: No hay lectura macro todavía. Ejecuta el worker o corre `python -m antigravity.worker --once --agent macro`."

    if "ballena" in q or "flujo" in q or "whale" in q:
        if uw_429:
            return "Aetheris: Unusual Whales devolvió rate limit 429 recientemente. El radar está vivo, pero la fuente premium bloqueó nuevas consultas hasta el reset."
        detail = ""
        if last_rejected and last_rejected.get("status") == "OBSERVED_REJECTED":
            detail = f" Último descarte: {last_rejected['ticker']} porque {last_rejected.get('rejection_reason') or 'no cumplió filtros'}."
        return f"Aetheris: El radar observó {flows_total} flujos, calificó {flows_qualified} y descartó {flows_rejected}.{detail}"

    if "error" in q or "estado" in q or "agente" in q:
        if last_error:
            return f"Aetheris: Última ejecución registrada: {last_error['agent_name']} terminó en estado {last_error['status']}. Mensaje: {last_error.get('message') or last_error.get('error') or 'sin detalle'}."
        return "Aetheris: No hay ejecuciones registradas todavía."

    return "Aetheris: Estoy conectado a la base unificada. Pregúntame por macro, planes, ballenas, errores o estado de agentes."


streamlit_app.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; }
    div[data-testid="stMetric"] {
        background: #111827;
        border: 1px solid #263244;
        border-radius: 14px;
        padding: 14px;
    }
    div[data-testid="stMetric"] label { color: #9ca3af; }
    .section-card {
        border: 1px solid #263244;
        border-radius: 16px;
        padding: 16px;
        background: #0f172a;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

streamlit_app.title("ANTIGRAVITY QUANTITATIVE FUND")
streamlit_app.subheader("Institutional Market Intelligence Terminal")

with streamlit_app.sidebar:
    streamlit_app.markdown("### Datos del terminal")
    streamlit_app.caption("La vista lee la base local. No consulta Unusual Whales hasta que pulses Actualizar (o corras el worker).")
    if streamlit_app.button("🔄 Actualizar vista", type="primary", use_container_width=True):
        streamlit_app.rerun()
    streamlit_app.divider()
    streamlit_app.markdown("## Aetheris AI")
    streamlit_app.caption("Mentor operativo conectado a la base unificada.")
    if "messages" not in streamlit_app.session_state:
        streamlit_app.session_state.messages = [
            {"role": "assistant", "content": "Director, estoy conectado al motor Antigravity. Pregúntame por macro, planes, ballenas o estado de agentes."}
        ]

    for msg in streamlit_app.session_state.messages:
        streamlit_app.chat_message(msg["role"]).write(msg["content"])

    user_input = streamlit_app.chat_input("Consulta a Aetheris...")
    if user_input:
        streamlit_app.session_state.messages.append({"role": "user", "content": user_input})
        reply = aetheris_reply(user_input)
        streamlit_app.session_state.messages.append({"role": "assistant", "content": reply})
        streamlit_app.chat_message("user").write(user_input)
        streamlit_app.chat_message("assistant").write(reply)


macro = latest(MarketRegime, MarketRegime.id.desc())
last_uw = latest(RawUwEvent, RawUwEvent.id.desc())
last_run = latest(AgentRun, AgentRun.id.desc())

flow_total = count(OptionFlowSignal)
flow_qualified = count(OptionFlowSignal, [OptionFlowSignal.status.in_(["QUALIFIED", "PLANNED"])])
flow_rejected = count(OptionFlowSignal, [OptionFlowSignal.status == "OBSERVED_REJECTED"])
pending_plans = count(TradePlan, [TradePlan.execution_status == "PENDING"])
watchlist_plans = count(TradePlan, [TradePlan.execution_status == "WATCHLIST"])

metric_cols = streamlit_app.columns(6)
metric_cols[0].metric("Macro", macro["market_bias"] if macro else "SIN DATOS")
metric_cols[1].metric("Flujos Observados", flow_total)
metric_cols[2].metric("Calificados", flow_qualified)
metric_cols[3].metric("Descartados", flow_rejected)
metric_cols[4].metric("Planes / Watchlist", f"{pending_plans} / {watchlist_plans}")
metric_cols[5].metric("Último UW", last_uw["status_code"] if last_uw else "SIN REQUEST")

if last_uw and last_uw["status_code"] == 429:
    streamlit_app.error("Unusual Whales reportó rate limit 429. El dashboard no lo oculta: el motor esperará el reset o backoff configurado.")

streamlit_app.divider()

left, right = streamlit_app.columns([1, 2])

with left:
    streamlit_app.markdown("### Clima Macro")
    if macro:
        streamlit_app.write(f"Sesgo: **{macro['market_bias']}**")
        streamlit_app.write(f"Liquidez: **{macro['liquidity_index']}**")
        streamlit_app.write(f"DXY: `{macro['dxy_trend']}` | VIX: `{macro['vix_level']:.2f}`")
    else:
        streamlit_app.warning("Sin lectura macro. Ejecuta `python -m antigravity.worker --once --agent macro`.")

    streamlit_app.markdown("### Estado De Agentes")
    runs = latest_agent_runs_by_name()
    if runs:
        df_runs = pd.DataFrame(runs)[["agent_name", "status", "records_processed", "started_at", "error"]]
        streamlit_app.dataframe(df_runs, use_container_width=True)
    else:
        streamlit_app.info("Aún no hay ejecuciones auditadas.")

with right:
    streamlit_app.markdown("### Rotación De Capital")
    sectors = rows(SectorRotation, limit=8, order_by=SectorRotation.capital_flow_rank.asc())
    if sectors:
        streamlit_app.dataframe(pd.DataFrame(sectors)[["sector_ticker", "capital_flow_rank", "performance_20d", "status"]], use_container_width=True)
    else:
        streamlit_app.warning("Sin rotación sectorial. Ejecuta `python -m antigravity.worker --once --agent sector`.")

    streamlit_app.markdown("### Últimas Respuestas Unusual Whales")
    uw_events = rows(RawUwEvent, limit=6, order_by=RawUwEvent.id.desc())
    if uw_events:
        streamlit_app.dataframe(pd.DataFrame(uw_events)[["endpoint", "symbol", "status_code", "fetched_at"]], use_container_width=True)
    else:
        streamlit_app.info("Aún no hay requests registrados contra Unusual Whales.")

streamlit_app.divider()
streamlit_app.markdown("## Mesa De Decisión")
plans = top_pending_plans(limit=5)
streamlit_app.caption("Top trades = un plan activo por ticker, ordenado por última actualización del comité.")
watchlist_rows = rows(TradePlan, limit=15, order_by=TradePlan.conviction_score.desc(), filters=[TradePlan.execution_status == "WATCHLIST"])
rejected_rows = rows(TradePlan, limit=15, order_by=TradePlan.id.desc(), filters=[TradePlan.execution_status == "INVALIDATED"])

decision_tabs = streamlit_app.tabs(["Top Trades Aprobados", "Watchlist Institucional", "Rechazos"])

with decision_tabs[0]:
    if plans:
        for plan in plans:
            render_plan_card(plan, expanded=True)
    else:
        streamlit_app.info("Capital protegido: no hay Top Trades aprobados por el comité endurecido.")

with decision_tabs[1]:
    if watchlist_rows:
        for plan in watchlist_rows[:10]:
            render_plan_card(plan)
    else:
        streamlit_app.info("Sin candidatos en watchlist.")

with decision_tabs[2]:
    if rejected_rows:
        for plan in rejected_rows[:10]:
            render_plan_card(plan)
    else:
        streamlit_app.info("Sin rechazos registrados por la lógica nueva.")

streamlit_app.divider()
streamlit_app.markdown("## Centro Operativo De Contratos")
streamlit_app.caption("Aquí decides qué contratos se quedan bajo vigilancia y cuáles entran a backtesting.")

with streamlit_app.form("manual_contract_form"):
    manual_cols = streamlit_app.columns([1, 1, 1, 1, 1, 1])
    ticker_input = manual_cols[0].text_input("Ticker", placeholder="ORCL")
    type_input = manual_cols[1].selectbox("Tipo", ["CALL", "PUT"])
    strike_input = manual_cols[2].number_input("Strike", min_value=0.0, step=0.5)
    expiry_input = manual_cols[3].date_input("Expiración")
    underlying_input = manual_cols[4].number_input("Precio subyacente", min_value=0.0, step=0.01)
    premium_input = manual_cols[5].number_input("Premium alerta", min_value=0.0, step=1000.0)
    destination = streamlit_app.radio("Acción", ["Monitorear en vivo", "Añadir a backtesting", "Ambos"], horizontal=True)
    submitted = streamlit_app.form_submit_button("Añadir contrato")
    if submitted:
        direction = "SHORT" if type_input == "PUT" else "LONG"
        if ticker_input and strike_input:
            if destination in {"Monitorear en vivo", "Ambos"}:
                enqueue_manual_contract(ContractMonitor, ticker_input, type_input, strike_input, expiry_input, direction, underlying_input, premium_input, "ACTIVE", reason_field="watch_reason")
            if destination in {"Añadir a backtesting", "Ambos"}:
                enqueue_manual_contract(BacktestContract, ticker_input, type_input, strike_input, expiry_input, direction, underlying_input, premium_input, "QUEUED")
            streamlit_app.success(f"{ticker_input.upper()} {type_input} {strike_input} añadido a {destination}.")
        else:
            streamlit_app.warning("Necesito ticker y strike como mínimo.")

monitor_rows = rows(ContractMonitor, limit=10, order_by=ContractMonitor.updated_at.desc())
backtest_rows = rows(BacktestContract, limit=10, order_by=BacktestContract.updated_at.desc())
op_cols = streamlit_app.columns(2)
with op_cols[0]:
    streamlit_app.markdown("### Monitoreo En Vivo")
    if monitor_rows:
        streamlit_app.dataframe(
            pd.DataFrame(monitor_rows)[["ticker", "contract_type", "strike", "expiry", "status", "alert_tape_time", "last_seen_at", "last_note"]],
            use_container_width=True,
        )
    else:
        streamlit_app.info("Aún no hay contratos bajo monitoreo.")
with op_cols[1]:
    streamlit_app.markdown("### Cola De Backtesting")
    if backtest_rows:
        streamlit_app.dataframe(
            pd.DataFrame(backtest_rows)[["ticker", "contract_type", "strike", "expiry", "status", "alert_tape_time", "result_summary"]],
            use_container_width=True,
        )
    else:
        streamlit_app.info("Aún no hay contratos en backtesting.")

streamlit_app.divider()
streamlit_app.markdown("## Radar De Tape Institucional")
streamlit_app.caption("Las alertas más recientes de Unusual Whales aparecen primero por hora de tape (ET).")

whale_run = latest_whale_run()
live = live_flows(hours=8, limit=40)
if whale_run:
    streamlit_app.info(
        f"Whale scanner: {whale_run['status']} | +{whale_run['records_processed']} registros | "
        f"última corrida {format_dt(whale_run['started_at'])}"
    )
if live:
    streamlit_app.success(f"Alertas en vivo (últimas 8h): {len(live)} — la más reciente: {live[0]['ticker']} {live[0]['contract_type']} @ {format_dt(live[0]['tape_time'])}")
else:
    streamlit_app.warning("Sin alertas nuevas en las últimas 8 horas. Revisa que el worker esté corriendo.")

qualified = rows(OptionFlowSignal, limit=80, order_by=OptionFlowSignal.tape_time.desc(), filters=[OptionFlowSignal.status.in_(["QUALIFIED", "PLANNED"])])
rejected = rows(OptionFlowSignal, limit=80, order_by=OptionFlowSignal.tape_time.desc(), filters=[OptionFlowSignal.status == "OBSERVED_REJECTED"])

tab_live, tab1, tab2, tab3 = streamlit_app.tabs(["Alertas En Vivo", "Flujo Calificado", "Flujo Descartado", "Cinta Completa"])

with tab_live:
    if live:
        for flow in live[:25]:
            render_flow_card(flow, key_prefix="live")
    else:
        streamlit_app.warning("No hay tape en vivo todavía.")

with tab1:
    if qualified:
        for flow in qualified[:25]:
            render_flow_card(flow, key_prefix="qualified")
    else:
        streamlit_app.warning("No hay flujo calificado todavía.")

with tab2:
    if rejected:
        for flow in rejected[:25]:
            render_flow_card(flow, key_prefix="rejected")
    else:
        streamlit_app.info("Aún no hay flujo descartado guardado.")

with tab3:
    flows = rows(OptionFlowSignal, limit=120, order_by=OptionFlowSignal.tape_time.desc())
    if flows:
        for flow in flows[:30]:
            render_flow_card(flow, key_prefix="tape")
    else:
        streamlit_app.info("Sin cinta normalizada todavía.")

