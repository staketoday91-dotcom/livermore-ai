import os
import logging
import asyncio
from html import escape
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from dotenv import load_dotenv
import pytz

load_dotenv()

from core.models import Alert, WatchlistItem, Base, engine, SessionLocal, get_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("livermore")


def _ensure_schema():
    """
    Self-healing migration: si la tabla 'alerts' existe con un esquema viejo
    (por ejemplo tier INTEGER de una version anterior), la borramos para que
    SQLAlchemy la recree con el esquema actual de core/models.py.
    """
    try:
        inspector = inspect(engine)
        if not inspector.has_table("alerts"):
            return
        cols = {c["name"]: str(c["type"]).upper() for c in inspector.get_columns("alerts")}
        tier_type = cols.get("tier", "")
        needs_drop = (
            tier_type.startswith("INT")
            or "score_macro" not in cols
            or "current_price" not in cols
            or "updated_at" not in cols
        )
        if needs_drop:
            with engine.connect() as conn:
                conn.execute(text("DROP TABLE IF EXISTS alerts CASCADE"))
                conn.commit()
            logger.warning("alerts table dropped — esquema viejo detectado, recreando")
    except Exception as e:
        logger.warning(f"_ensure_schema fallo (no fatal): {e}")


# ─── Lifespan — arranca bot + scanner ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        _ensure_schema()
        Base.metadata.create_all(bind=engine)
        logger.info("Livermore AI started — DB ready")
    except Exception as e:
        logger.error(f"DB init fallo (app sigue arriba para servir /health): {e}")

    discord_bot = None
    try:
        from bot.discord_bot import create_bot, run_bot
        discord_bot = create_bot()
        asyncio.create_task(run_bot(discord_bot))
        logger.info("Discord bot task iniciado")
    except Exception as e:
        logger.warning(f"Discord bot no disponible: {e}")

    try:
        from core.scanner import LivermoreScanner
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scanner   = LivermoreScanner(discord_bot=discord_bot)
        scheduler = AsyncIOScheduler(timezone="America/New_York")
        scheduler.add_job(scanner.run_scan, "cron",
                          day_of_week="mon-fri",
                          hour="8-19", minute="*/5")
        scheduler.start()
        logger.info("Scanner scheduler iniciado — cada 5min en market hours")
    except Exception as e:
        logger.warning(f"Scanner no disponible: {e}")

    yield


# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="Livermore AI", version="1.0.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ─── Endpoints ────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>LIVERMORE AI | Trading Terminal</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0a0a0a;
            --panel: #111111;
            --panel-2: #151515;
            --line: rgba(201, 168, 76, 0.22);
            --gold: #c9a84c;
            --gold-soft: rgba(201, 168, 76, 0.14);
            --text: #f2f2f2;
            --muted: #8f8f8f;
            --green: #27d17f;
            --red: #ff5c5c;
            --blue: #60a5fa;
        }

        * { box-sizing: border-box; }
        body {
            margin: 0;
            min-height: 100vh;
            background:
                radial-gradient(circle at 15% 0%, rgba(201, 168, 76, 0.16), transparent 32%),
                radial-gradient(circle at 85% 10%, rgba(96, 165, 250, 0.08), transparent 26%),
                var(--bg);
            color: var(--text);
            font-family: "Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            letter-spacing: -0.01em;
        }

        .terminal {
            display: grid;
            grid-template-rows: auto 1fr auto;
            min-height: 100vh;
            padding: 22px;
            gap: 18px;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border: 1px solid var(--line);
            background: linear-gradient(135deg, rgba(17, 17, 17, 0.96), rgba(10, 10, 10, 0.92));
            border-radius: 18px;
            padding: 18px 22px;
            box-shadow: 0 24px 80px rgba(0, 0, 0, 0.45);
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .mark {
            width: 46px;
            height: 46px;
            display: grid;
            place-items: center;
            border: 1px solid var(--gold);
            border-radius: 12px;
            color: var(--gold);
            background: var(--gold-soft);
            font-weight: 800;
        }

        h1 {
            margin: 0;
            font-size: clamp(28px, 3vw, 42px);
            font-weight: 800;
            line-height: 1;
            color: var(--gold);
            text-transform: uppercase;
        }

        .subtitle {
            margin-top: 6px;
            color: var(--muted);
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.18em;
        }

        .status {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 14px;
            border: 1px solid rgba(39, 209, 127, 0.28);
            border-radius: 999px;
            background: rgba(39, 209, 127, 0.09);
            color: var(--green);
            font-weight: 800;
            text-transform: uppercase;
        }

        .header-actions {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .nav-btn {
            padding: 10px 14px;
            border: 1px solid rgba(96, 165, 250, 0.38);
            border-radius: 999px;
            color: #bfdbfe;
            background: rgba(96, 165, 250, 0.12);
            font-size: 13px;
            font-weight: 800;
            text-decoration: none;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        .pulse {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--green);
            box-shadow: 0 0 0 0 rgba(39, 209, 127, 0.8);
            animation: pulse 1.8s infinite;
        }

        @keyframes pulse {
            70% { box-shadow: 0 0 0 12px rgba(39, 209, 127, 0); }
            100% { box-shadow: 0 0 0 0 rgba(39, 209, 127, 0); }
        }

        main {
            display: grid;
            grid-template-columns: minmax(240px, 0.8fr) minmax(420px, 1.6fr) minmax(260px, 0.9fr);
            gap: 18px;
        }

        .panel {
            min-height: 0;
            border: 1px solid var(--line);
            border-radius: 18px;
            background: linear-gradient(180deg, rgba(17, 17, 17, 0.98), rgba(12, 12, 12, 0.98));
            overflow: hidden;
            box-shadow: 0 18px 50px rgba(0, 0, 0, 0.35);
        }

        .panel-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 18px;
            border-bottom: 1px solid var(--line);
            background: rgba(201, 168, 76, 0.06);
        }

        .panel-title {
            margin: 0;
            color: var(--gold);
            font-size: 13px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.16em;
        }

        .panel-meta {
            color: var(--muted);
            font-size: 12px;
            font-weight: 600;
        }

        .watchlist, .alerts, .stats {
            padding: 16px;
        }

        .feed-stack {
            display: grid;
            gap: 18px;
        }

        .backtest-panel {
            border-color: rgba(96, 165, 250, 0.28);
            background: linear-gradient(180deg, rgba(8, 18, 38, 0.98), rgba(8, 13, 28, 0.98));
        }

        .backtest-panel .panel-head {
            border-bottom-color: rgba(96, 165, 250, 0.22);
            background: rgba(96, 165, 250, 0.08);
        }

        .backtest-panel .panel-title {
            color: #93c5fd;
        }

        .backtest-copy {
            padding: 14px 16px 0;
            color: #b6c8e7;
            font-size: 13px;
            line-height: 1.5;
        }

        .backtests {
            padding: 16px;
        }

        .backtest-card {
            border-color: rgba(96, 165, 250, 0.18);
            background: rgba(96, 165, 250, 0.045);
        }

        .backtest-card::before {
            background: #64748b;
        }

        .backtest-badge {
            border-color: rgba(148, 163, 184, 0.32);
            color: #cbd5e1;
            background: rgba(100, 116, 139, 0.18);
        }

        .result-win {
            border-color: rgba(39, 209, 127, 0.38);
            color: var(--green);
            background: rgba(39, 209, 127, 0.12);
        }

        .result-loss {
            border-color: rgba(255, 92, 92, 0.38);
            color: var(--red);
            background: rgba(255, 92, 92, 0.12);
        }

        .pnl {
            color: var(--muted);
            font-size: 12px;
            font-weight: 800;
        }

        .pnl.win { color: var(--green); }
        .pnl.loss { color: var(--red); }

        .watch-item, .alert-card, .stat-card {
            border: 1px solid rgba(255, 255, 255, 0.07);
            background: rgba(255, 255, 255, 0.025);
            border-radius: 14px;
        }

        .watch-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            padding: 12px;
        }

        .ticker {
            font-size: 18px;
            font-weight: 800;
            color: #ffffff;
        }

        .watch-note {
            margin-top: 3px;
            color: var(--muted);
            font-size: 12px;
            max-width: 132px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .score-pill {
            min-width: 64px;
            padding: 8px 10px;
            border-radius: 10px;
            background: var(--gold-soft);
            color: var(--gold);
            text-align: center;
            font-weight: 800;
            font-variant-numeric: tabular-nums;
        }

        .alert-card {
            margin-bottom: 14px;
            padding: 16px;
            position: relative;
            overflow: hidden;
        }

        .alert-card::before {
            content: "";
            position: absolute;
            left: 0;
            top: 0;
            bottom: 0;
            width: 3px;
            background: var(--gold);
        }

        .alert-top {
            display: flex;
            justify-content: space-between;
            gap: 14px;
            margin-bottom: 12px;
        }

        .alert-title {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 10px;
        }

        .tier {
            padding: 5px 9px;
            border-radius: 999px;
            border: 1px solid var(--line);
            color: var(--gold);
            background: var(--gold-soft);
            font-size: 11px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        .direction {
            color: var(--blue);
            font-size: 12px;
            font-weight: 800;
            text-transform: uppercase;
        }

        .score-big {
            color: var(--gold);
            font-size: 28px;
            font-weight: 800;
            font-variant-numeric: tabular-nums;
            text-align: right;
        }

        .score-big span {
            color: var(--muted);
            font-size: 13px;
        }

        .contract {
            color: #d7d7d7;
            font-size: 14px;
            font-weight: 700;
            margin-bottom: 10px;
        }

        .copy-btn {
            margin-left: 8px;
            border: 1px solid rgba(201, 168, 76, 0.28);
            border-radius: 8px;
            background: rgba(201, 168, 76, 0.1);
            color: var(--gold);
            cursor: pointer;
            font-size: 13px;
            padding: 4px 7px;
        }

        .signal {
            color: var(--muted);
            font-size: 13px;
            line-height: 1.5;
            margin-bottom: 14px;
        }

        .breakdown {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px;
        }

        .break-item {
            min-width: 0;
        }

        .break-label {
            display: flex;
            justify-content: space-between;
            color: var(--muted);
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            margin-bottom: 6px;
        }

        .bar {
            height: 6px;
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.08);
            overflow: hidden;
        }

        .bar-fill {
            height: 100%;
            width: 0%;
            border-radius: inherit;
            background: linear-gradient(90deg, var(--gold), #f4d878);
        }

        .stats-grid {
            display: grid;
            gap: 12px;
        }

        .stat-card {
            padding: 14px;
        }

        .stat-label {
            color: var(--muted);
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        .stat-value {
            margin-top: 6px;
            color: #ffffff;
            font-size: 30px;
            font-weight: 800;
            font-variant-numeric: tabular-nums;
        }

        .empty {
            padding: 28px 18px;
            color: var(--muted);
            text-align: center;
            border: 1px dashed rgba(201, 168, 76, 0.25);
            border-radius: 14px;
            background: rgba(201, 168, 76, 0.04);
        }

        footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            color: var(--muted);
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.12em;
        }

        footer strong {
            color: var(--gold);
        }

        @media (max-width: 1100px) {
            main { grid-template-columns: 1fr; }
            header { align-items: flex-start; flex-direction: column; gap: 14px; }
            .breakdown { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
    </style>
</head>
<body>
    <div class="terminal">
        <header>
            <div class="brand">
                <div class="mark">LA</div>
                <div>
                    <h1>LIVERMORE AI</h1>
                    <div class="subtitle">Terminal de tape reading y momentum</div>
                </div>
            </div>
            <div class="header-actions">
                <a class="nav-btn" href="/backtesting" target="_blank">📊 BACKTESTING</a>
                <div class="status"><span class="pulse"></span> Sistema LIVE</div>
            </div>
        </header>

        <main>
            <section class="panel">
                <div class="panel-head">
                    <h2 class="panel-title">Watchlist</h2>
                    <span class="panel-meta" id="watchCount">0 activos</span>
                </div>
                <div class="watchlist" id="watchlist"></div>
            </section>

            <section class="panel">
                <div class="panel-head">
                    <h2 class="panel-title">Feed de Alertas</h2>
                    <span class="panel-meta">Auto-refresh 30s</span>
                </div>
                <div class="alerts" id="alerts"></div>
            </section>

            <section class="panel">
                <div class="panel-head">
                    <h2 class="panel-title">Stats del Sistema</h2>
                    <span class="panel-meta" id="lastUpdate">Sin datos</span>
                </div>
                <div class="stats">
                    <div class="stats-grid" id="stats"></div>
                </div>
            </section>
        </main>

        <footer>
            <span>Livermore AI Trading Terminal</span>
            <span>Hora ET: <strong id="etClock">--:--:--</strong></span>
        </footer>
    </div>

    <script>
        const els = {
            alerts: document.getElementById("alerts"),
            stats: document.getElementById("stats"),
            watchlist: document.getElementById("watchlist"),
            watchCount: document.getElementById("watchCount"),
            lastUpdate: document.getElementById("lastUpdate"),
            etClock: document.getElementById("etClock")
        };

        let latestAlerts = [];

        function escapeHtml(value) {
            return String(value ?? "")
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;")
                .replaceAll("'", "&#039;");
        }

        function fmt(value, fallback = "--") {
            return value === null || value === undefined || value === "" ? fallback : value;
        }

        function scoreValue(value) {
            const score = Number(value ?? 0);
            return Number.isFinite(score) ? Math.max(0, Math.min(100, score)) : 0;
        }

        function tierLabel(tier) {
            const value = Number(tier ?? 1);
            if (value >= 3) return "LIVERMORE";
            if (value === 2) return "PREMIUM";
            return "ALERT";
        }

        function toIBKR(raw) {
            const m = String(raw || "").match(/^([A-Z]+)(\d{6})([CP])(\d{8})$/);
            if (!m) return raw;
            const strike = (parseInt(m[4]) / 1000).toString();
            return m[1] + " " + m[2] + m[3] + " " + strike;
        }

        async function copyIBKR(button) {
            const text = button.dataset.contract || "";
            if (!text) return;
            await navigator.clipboard.writeText(text);
            button.textContent = "✅";
            setTimeout(() => { button.textContent = "📋"; }, 1000);
        }

        async function getJson(url) {
            const response = await fetch(url, { cache: "no-store" });
            if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
            return response.json();
        }

        function renderAlertCards(target, alerts, options = {}) {
            const list = Array.isArray(alerts) ? alerts : [];
            if (!list.length) {
                target.innerHTML = `<div class="empty">${escapeHtml(options.empty || "No hay señales para mostrar.")}</div>`;
                return;
            }

            target.innerHTML = list.map((alert) => {
                const breakdown = alert.score_breakdown || {};
                const parts = [
                    ["ICC", breakdown.icc],
                    ["Dark", breakdown.dark_pool],
                    ["Flow", breakdown.flow],
                    ["Macro", breakdown.macro]
                ];
                const score = scoreValue(alert.score);
                const contract = alert.contract || [alert.strike, alert.expiration].filter(Boolean).join(" ");
                const ibkrContract = contract ? toIBKR(contract) : "N/A";
                const copyButton = contract ? `<button class="copy-btn" data-contract="${escapeHtml(ibkrContract)}" onclick="copyIBKR(this)" title="Copiar contrato IBKR">📋</button>` : "";
                const status = String(alert.status || "").toLowerCase();
                const badge = options.backtest ? (status === "win" ? "WIN" : status === "loss" ? "LOSS" : "PENDING") : tierLabel(alert.tier);
                const cardClass = options.backtest ? "alert-card backtest-card" : "alert-card";
                const badgeClass = options.backtest
                    ? `tier backtest-badge ${status === "win" ? "result-win" : status === "loss" ? "result-loss" : ""}`
                    : "tier";
                const pnl = Number(alert.pnl);
                const pnlClass = Number.isFinite(pnl) && pnl > 0 ? "win" : Number.isFinite(pnl) && pnl < 0 ? "loss" : "";
                const pnlText = options.backtest && Number.isFinite(pnl) ? `<span class="pnl ${pnlClass}">${pnl > 0 ? "+" : ""}${pnl.toFixed(2)}%</span>` : "";
                return `
                    <article class="${cardClass}">
                        <div class="alert-top">
                            <div>
                                <div class="alert-title">
                                    <span class="ticker">${escapeHtml(alert.ticker)}</span>
                                    <span class="${badgeClass}">${badge}</span>
                                    <span class="direction">${escapeHtml(fmt(alert.direction, "SIN DIRECCION"))}</span>
                                    ${pnlText}
                                </div>
                            </div>
                            <div class="score-big">${score}<span>/100</span></div>
                        </div>
                        <div class="contract">Contrato: ${escapeHtml(fmt(ibkrContract, "N/A"))}${copyButton}</div>
                        <div class="signal">${escapeHtml(fmt(alert.signal, "Sin tesis registrada."))}</div>
                        <div class="breakdown">
                            ${parts.map(([label, value]) => {
                                const itemScore = scoreValue(value);
                                return `
                                    <div class="break-item">
                                        <div class="break-label"><span>${label}</span><span>${itemScore}</span></div>
                                        <div class="bar"><div class="bar-fill" style="width:${itemScore}%"></div></div>
                                    </div>
                                `;
                            }).join("")}
                        </div>
                    </article>
                `;
            }).join("");
        }

        function renderAlerts(alerts) {
            latestAlerts = Array.isArray(alerts) ? alerts : [];
            renderAlertCards(els.alerts, latestAlerts, {
                empty: "No hay alertas activas todavía. El feed se actualizará automáticamente."
            });
        }

        function renderStats(stats) {
            const cards = [
                ["Total", stats.total],
                ["Hoy", stats.today],
                ["Abiertas", stats.open],
                ["Wins", stats.wins],
                ["Losses", stats.losses],
                ["Win Rate", `${fmt(stats.win_rate, 0)}%`]
            ];

            els.stats.innerHTML = cards.map(([label, value]) => `
                <div class="stat-card">
                    <div class="stat-label">${label}</div>
                    <div class="stat-value">${escapeHtml(fmt(value, 0))}</div>
                </div>
            `).join("");
        }

        function renderWatchlist(items) {
            const scores = new Map();
            latestAlerts.forEach((alert) => {
                if (alert.ticker && !scores.has(alert.ticker)) scores.set(alert.ticker, scoreValue(alert.score));
            });

            let list = Array.isArray(items) ? items : [];
            if (!list.length && latestAlerts.length) {
                list = latestAlerts.map((alert) => ({ ticker: alert.ticker, notes: alert.regime || "alerta activa" }));
            }

            els.watchCount.textContent = `${list.length} activos`;
            if (!list.length) {
                els.watchlist.innerHTML = `<div class="empty">Watchlist vacía. Agrega tickers desde la API para monitorearlos aquí.</div>`;
                return;
            }

            els.watchlist.innerHTML = list.map((item) => {
                const ticker = item.ticker || "N/A";
                const score = scores.get(ticker) ?? 0;
                return `
                    <div class="watch-item">
                        <div>
                            <div class="ticker">${escapeHtml(ticker)}</div>
                            <div class="watch-note">${escapeHtml(fmt(item.notes, "sin notas"))}</div>
                        </div>
                        <div class="score-pill">${score}/100</div>
                    </div>
                `;
            }).join("");
        }

        async function refreshDashboard() {
            try {
                const [alerts, stats, watchlist] = await Promise.all([
                    getJson("/api/alerts?status=pending"),
                    getJson("/api/stats"),
                    getJson("/api/watchlist")
                ]);
                renderAlerts(alerts);
                renderStats(stats);
                renderWatchlist(watchlist);
                els.lastUpdate.textContent = "Actualizado";
            } catch (error) {
                els.alerts.innerHTML = `<div class="empty">Error cargando datos: ${escapeHtml(error.message)}</div>`;
                els.lastUpdate.textContent = "Error";
            }
        }

        function updateClock() {
            els.etClock.textContent = new Intl.DateTimeFormat("es-US", {
                timeZone: "America/New_York",
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
                hour12: false
            }).format(new Date());
        }

        updateClock();
        refreshDashboard();
        setInterval(updateClock, 1000);
        setInterval(refreshDashboard, 30000);
    </script>
</body>
</html>
"""


def _format_et(dt: Optional[datetime]) -> str:
    if not dt:
        return "--"
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    et = dt.astimezone(pytz.timezone("America/New_York"))
    return f"{et.strftime('%b')} {et.day}, {et.year} — {et.strftime('%I:%M %p').lstrip('0')} ET"


@app.get("/backtesting", response_class=HTMLResponse)
async def backtesting_page(db: Session = Depends(get_db)):
    alerts = (
        db.query(Alert)
        .filter(Alert.mode == "BACKTEST")
        .order_by(Alert.created_at.desc())
        .all()
    )
    total = len(alerts)
    wins = sum(1 for a in alerts if a.status == "win")
    losses = sum(1 for a in alerts if a.status == "loss")
    closed = wins + losses
    win_rate = round(wins / closed * 100, 1) if closed else 0
    pnl_values = [a.pnl_pct for a in alerts if a.pnl_pct is not None]
    avg_pnl = round(sum(pnl_values) / len(pnl_values), 2) if pnl_values else 0

    rows = "\n".join(
        f"""
        <tr>
            <td>{escape(_format_et(a.created_at))}</td>
            <td class="ticker">{escape(a.ticker or "--")}</td>
            <td>
                <span class="ibkr-contract" data-raw="{escape(a.contract or '', quote=True)}">{escape(a.contract or "--")}</span>
                <button class="copy-btn" data-contract="" onclick="copyIBKR(this)" title="Copiar contrato IBKR">📋</button>
            </td>
            <td>{a.score_total or 0}/100</td>
            <td>{escape(a.icc_phase or "--")}</td>
            <td class="pnl {'win' if (a.pnl_pct or 0) > 0 else 'loss' if (a.pnl_pct or 0) < 0 else ''}">{'+' if (a.pnl_pct or 0) > 0 else ''}{round(a.pnl_pct, 2) if a.pnl_pct is not None else '--'}{'%' if a.pnl_pct is not None else ''}</td>
            <td><span class="badge {escape(a.status or 'pending')}">{escape((a.status or 'pending').upper())}</span></td>
        </tr>
        """
        for a in alerts
    )

    return """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>LIVERMORE AI — BACKTESTING</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg:#0a0a0a; --panel:#101827; --line:rgba(96,165,250,.25);
            --blue:#93c5fd; --text:#f2f2f2; --muted:#8fa3bf; --green:#27d17f; --red:#ff5c5c; --gold:#c9a84c;
        }
        * { box-sizing:border-box; }
        body {
            margin:0; min-height:100vh; color:var(--text);
            font-family:"Inter",system-ui,sans-serif;
            background:radial-gradient(circle at 15% 0%,rgba(96,165,250,.18),transparent 32%), var(--bg);
            padding:22px;
        }
        header {
            display:flex; justify-content:space-between; align-items:center; gap:16px;
            border:1px solid var(--line); border-radius:18px; padding:18px 22px;
            background:linear-gradient(135deg,rgba(15,23,42,.98),rgba(8,13,28,.98));
            box-shadow:0 24px 80px rgba(0,0,0,.45);
        }
        h1 { margin:0; color:var(--blue); font-size:clamp(28px,3vw,40px); font-weight:800; }
        .back { color:var(--gold); text-decoration:none; font-weight:800; border:1px solid rgba(201,168,76,.28); border-radius:999px; padding:10px 14px; background:rgba(201,168,76,.1); }
        .stats { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; margin:18px 0; }
        .stat { border:1px solid var(--line); border-radius:16px; padding:16px; background:rgba(15,23,42,.88); }
        .label { color:var(--muted); font-size:12px; font-weight:800; text-transform:uppercase; letter-spacing:.12em; }
        .value { margin-top:6px; font-size:30px; font-weight:800; }
        .panel { border:1px solid var(--line); border-radius:18px; overflow:hidden; background:rgba(8,13,28,.96); }
        .panel-head { padding:16px 18px; color:#bfdbfe; background:rgba(96,165,250,.08); border-bottom:1px solid var(--line); font-weight:800; }
        table { width:100%; border-collapse:collapse; }
        th,td { padding:13px 14px; border-bottom:1px solid rgba(255,255,255,.06); text-align:left; font-size:13px; }
        th { color:var(--muted); text-transform:uppercase; letter-spacing:.1em; font-size:11px; }
        .ticker { color:#fff; font-weight:800; }
        .pnl { font-weight:800; color:var(--muted); }
        .pnl.win { color:var(--green); }
        .pnl.loss { color:var(--red); }
        .badge { display:inline-block; padding:5px 9px; border-radius:999px; font-size:11px; font-weight:800; background:rgba(148,163,184,.16); color:#cbd5e1; }
        .badge.win { color:var(--green); background:rgba(39,209,127,.12); }
        .badge.loss { color:var(--red); background:rgba(255,92,92,.12); }
        .copy-btn { margin-left:8px; border:1px solid rgba(96,165,250,.3); border-radius:8px; background:rgba(96,165,250,.12); color:var(--blue); cursor:pointer; font-size:13px; padding:4px 7px; }
        @media (max-width:900px) { .stats { grid-template-columns:1fr; } header { flex-direction:column; align-items:flex-start; } table { min-width:900px; } .panel { overflow:auto; } }
    </style>
</head>
<body>
    <header>
        <div>
            <h1>LIVERMORE AI — BACKTESTING</h1>
            <div class="label">Señales históricas separadas de alertas activas</div>
        </div>
        <a class="back" href="/">← Volver al Dashboard</a>
    </header>
    <section class="stats">
        <div class="stat"><div class="label">Total Backtested</div><div class="value">""" + str(total) + """</div></div>
        <div class="stat"><div class="label">Win Rate</div><div class="value">""" + str(win_rate) + """%</div></div>
        <div class="stat"><div class="label">P&L Promedio</div><div class="value">""" + ("+" if avg_pnl > 0 else "") + str(avg_pnl) + """%</div></div>
    </section>
    <section class="panel">
        <div class="panel-head">Alertas históricas</div>
        <table>
            <thead>
                <tr>
                    <th>Fecha Entrada</th><th>Ticker</th><th>Contrato</th><th>Score</th><th>Dirección</th><th>P&L%</th><th>Status</th>
                </tr>
            </thead>
            <tbody>""" + (rows or '<tr><td colspan="7">No hay backtests cargados.</td></tr>') + """</tbody>
        </table>
    </section>
    <script>
        function toIBKR(raw) {
            const m = String(raw || "").match(/^([A-Z]+)(\d{6})([CP])(\d{8})$/);
            if (!m) return raw;
            const strike = (parseInt(m[4]) / 1000).toString();
            return m[1] + " " + m[2] + m[3] + " " + strike;
        }

        async function copyIBKR(button) {
            const text = button.dataset.contract || "";
            if (!text) return;
            await navigator.clipboard.writeText(text);
            button.textContent = "✅";
            setTimeout(() => { button.textContent = "📋"; }, 1000);
        }

        document.querySelectorAll(".ibkr-contract").forEach((el) => {
            const raw = el.dataset.raw || el.textContent;
            const ibkr = toIBKR(raw);
            el.textContent = ibkr || "--";
            const button = el.parentElement.querySelector(".copy-btn");
            if (button) {
                button.dataset.contract = ibkr;
                if (!ibkr || ibkr === "--") button.style.display = "none";
            }
        });
    </script>
</body>
</html>
"""


def _serialize_alert(a: Alert) -> dict:
    return {
        "id":        a.id,
        "ticker":    a.ticker,
        "tier":      a.tier,
        "score":     a.score_total,
        "direction": a.icc_phase,
        "entry":     a.entry_price,
        "sl":        a.stop_loss,
        "tp1":       a.target1,
        "tp2":       a.target2,
        "contract":  a.contract,
        "strike":    a.strike,
        "expiration":a.expiration,
        "delta":     a.delta,
        "premium":   a.premium,
        "signal":    a.signal_summary,
        "regime":    a.regime,
        "session":   a.market_session,
        "status":    a.status,
        "mode":      a.mode,
        "pnl":       a.pnl_pct,
        "score_breakdown": {
            "icc":       a.score_icc,
            "dark_pool": a.score_darkpool,
            "flow":      a.score_flow,
            "macro":     getattr(a, "score_macro", None) or a.score_regime,
        },
        "date": a.created_at.isoformat() if a.created_at else None,
    }


@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    try:
        active = db.query(Alert).filter(Alert.mode != "BACKTEST")
        total  = active.count()
        wins   = active.filter(Alert.status == "win").count()
        losses = active.filter(Alert.status == "loss").count()
        closed = wins + losses
        today  = datetime.utcnow().date()
        today_alerts = active.filter(
            Alert.created_at >= datetime(today.year, today.month, today.day)
        ).count()
        return {
            "total":    total,
            "today":    today_alerts,
            "wins":     wins,
            "losses":   losses,
            "open":     active.filter(Alert.status == "pending").count(),
            "win_rate": round(wins / closed * 100, 1) if closed > 0 else 0,
        }
    except Exception as e:
        logger.exception("get_stats error")
        raise HTTPException(500, f"stats_error: {type(e).__name__}: {e}")


@app.get("/api/alerts")
async def get_alerts(
    status: Optional[str] = Query(None),
    tier:   Optional[str] = Query(None),
    limit:  int           = Query(50),
    db: Session = Depends(get_db)
):
    try:
        q = (
            db.query(Alert)
            .filter(Alert.status != "backtest")
            .filter(Alert.mode != "BACKTEST")
            .order_by(Alert.created_at.desc())
        )
        if status:
            q = q.filter(Alert.status == status)
        if tier:
            try:
                q = q.filter(Alert.tier == int(tier))
            except ValueError:
                pass
        return [_serialize_alert(a) for a in q.limit(limit).all()]
    except Exception as e:
        logger.exception("get_alerts error")
        raise HTTPException(500, f"alerts_error: {type(e).__name__}: {e}")


@app.get("/api/backtest")
async def get_backtest(limit: int = Query(50), db: Session = Depends(get_db)):
    try:
        q = (
            db.query(Alert)
            .filter(Alert.mode == "BACKTEST")
            .order_by(Alert.created_at.desc())
        )
        return [_serialize_alert(a) for a in q.limit(limit).all()]
    except Exception as e:
        logger.exception("get_backtest error")
        raise HTTPException(500, f"backtest_error: {type(e).__name__}: {e}")


@app.patch("/api/alerts/{alert_id}")
async def update_alert(
    alert_id: int,
    status:   Optional[str]   = None,
    pnl_pct:  Optional[float] = None,
    db: Session = Depends(get_db)
):
    a = db.query(Alert).filter(Alert.id == alert_id).first()
    if not a:
        raise HTTPException(404, "Not found")
    if status:
        a.status = status
    if pnl_pct is not None:
        a.pnl_pct = pnl_pct
    db.commit()
    return {"ok": True}


@app.get("/api/watchlist")
async def get_watchlist(db: Session = Depends(get_db)):
    items = db.query(WatchlistItem).filter(WatchlistItem.active == True).all()
    return [{"id": i.id, "ticker": i.ticker, "notes": i.notes} for i in items]


@app.post("/api/watchlist")
async def add_watchlist(ticker: str, notes: str = "", db: Session = Depends(get_db)):
    i = WatchlistItem(ticker=ticker.upper(), notes=notes)
    db.add(i)
    db.commit()
    return {"ok": True, "id": i.id}


@app.delete("/api/watchlist/{item_id}")
async def remove_watchlist(item_id: int, db: Session = Depends(get_db)):
    i = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
    if not i:
        raise HTTPException(404, "Not found")
    i.active = False
    db.commit()
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
