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


async def _seed_watchlist_if_empty():
    db = None
    try:
        db = SessionLocal()
        count = db.query(WatchlistItem).count()
        if count == 0:
            from core.uw_fetcher import UWFetcher
            uw = UWFetcher()
            tickers = await uw.get_active_tickers()
            for ticker in tickers[:15]:
                item = WatchlistItem(ticker=ticker.upper(), active=True)
                db.add(item)
            db.commit()
            logger.info(f"Watchlist seeded with {min(len(tickers), 15)} UW tickers")
    except Exception as e:
        logger.warning(f"Watchlist seed error: {e}")
    finally:
        if db:
            db.close()


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
        needs_drop = (
            "score_macro" not in cols
            or "current_price" not in cols
            or "updated_at" not in cols
        )
        if needs_drop:
            with engine.connect() as conn:
                if engine.dialect.name == "postgresql":
                    conn.execute(text("DROP TABLE IF EXISTS alerts CASCADE"))
                else:
                    conn.execute(text("DROP TABLE IF EXISTS alerts"))
                conn.commit()
            logger.warning("alerts table dropped — esquema viejo detectado, recreando")
            return

        missing_columns = {
            "oi_growing": "BOOLEAN DEFAULT FALSE",
            "oi_change_pct": "FLOAT DEFAULT 0",
            "oi_days_growing": "INTEGER DEFAULT 0",
            "oi_today": "INTEGER",
            "oi_yesterday": "INTEGER",
        }
        with engine.connect() as conn:
            for col, col_type in missing_columns.items():
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE alerts ADD COLUMN {col} {col_type}"))
                    logger.info(f"alerts.{col} agregado para OI conviction tracking")
            conn.commit()
    except Exception as e:
        logger.warning(f"_ensure_schema fallo (no fatal): {e}")


# ─── Lifespan — arranca bot + scanner ─────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        _ensure_schema()
        Base.metadata.create_all(bind=engine)
        # Auto-backfill y seed watchlist si DB vacía
        try:
            from core.models import Alert, WatchlistItem, SessionLocal as SL
            _db = SL()
            backtest_count = _db.query(Alert).filter(Alert.status == "backtest").count()
            watchlist_count = _db.query(WatchlistItem).count()
            _db.close()
            
            if backtest_count == 0:
                logger.info("DB vacía — iniciando backfill automático...")
                from core.backfill import run_backfill
                asyncio.create_task(run_backfill())
            
            if watchlist_count == 0:
                logger.info("Watchlist vacía — seeding automático...")
                async def _seed():
                    from core.uw_fetcher import UWFetcher
                    uw = UWFetcher()
                    tickers = await uw.get_active_tickers()
                    _db2 = SL()
                    for ticker in tickers[:15]:
                        _db2.add(WatchlistItem(ticker=ticker, active=True))
                    _db2.commit()
                    _db2.close()
                asyncio.create_task(_seed())
        except Exception as e:
            logger.warning(f"Auto-init error: {e}")
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
                <a class="nav-btn" href="/alerts">🔔 ALERTAS</a>
                <a class="nav-btn" href="/watchlist">👁 WATCHLIST</a>
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
            const m = String(raw || "").match(/^([A-Z]+)(\\d{6})([CP])(\\d{8})$/);
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


def _replace_root_dashboard_route():
    app.router.routes = [
        route for route in app.router.routes
        if not (
            getattr(route, "path", None) == "/"
            and "GET" in getattr(route, "methods", set())
        )
    ]


_replace_root_dashboard_route()


@app.get("/", response_class=HTMLResponse)
async def professional_dashboard():
    return """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>LIVERMORE AI | Professional Trading Terminal</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg:#0a0a0a; --panel:#101010; --panel2:#171717; --line:rgba(201,168,76,.22);
            --gold:#c9a84c; --amber:#E8921A; --red-brand:#c0392b; --text:#f2f2f2;
            --muted:#9a9a9a; --muted2:#656565; --green:#27d17f; --red:#ff5c5c; --shadow:rgba(0,0,0,.45);
        }
        body.light {
            --bg:#f5f0e8; --panel:#fffaf1; --panel2:#f0e6d5; --line:rgba(91,70,23,.22);
            --text:#18140d; --muted:#6d604d; --muted2:#8d806b; --shadow:rgba(72,52,16,.14);
        }
        * { box-sizing:border-box; }
        body {
            margin:0; min-height:100vh; color:var(--text); font-family:"Inter",system-ui,sans-serif;
            background:radial-gradient(circle at 12% -8%,rgba(201,168,76,.18),transparent 30%),
                       radial-gradient(circle at 95% 0%,rgba(232,146,26,.10),transparent 24%), var(--bg);
            letter-spacing:-.01em;
        }
        .terminal { min-height:100vh; display:grid; grid-template-rows:auto 1fr auto; gap:14px; padding:16px; }
        header {
            display:grid; grid-template-columns:auto 1fr auto; gap:20px; align-items:center;
            border:1px solid var(--line); border-radius:16px; padding:16px 18px;
            background:linear-gradient(135deg,var(--panel),rgba(10,10,10,.92)); box-shadow:0 20px 70px var(--shadow);
        }
        body.light header { background:linear-gradient(135deg,var(--panel),#f5f0e8); }
        .brand { display:flex; align-items:center; gap:16px; }
        .mark {
            width:46px; height:46px; display:grid; place-items:center; border:1px solid rgba(201,168,76,.72);
            border-radius:14px; color:var(--gold); background:rgba(201,168,76,.12); font-weight:800; letter-spacing:.08em;
        }
        h1 { margin:0; color:var(--gold); font-size:clamp(24px,2.4vw,36px); line-height:1; font-weight:800; }
        .subtitle { margin-top:6px; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.18em; }
        nav, .header-actions { display:flex; align-items:center; gap:10px; }
        nav { justify-content:center; }
        .nav-btn, .theme-toggle {
            border:1px solid var(--line); border-radius:999px; background:rgba(201,168,76,.08); color:var(--gold);
            cursor:pointer; font-size:12px; font-weight:800; letter-spacing:.1em; padding:10px 13px; text-decoration:none; text-transform:uppercase;
        }
        .status {
            display:flex; align-items:center; gap:9px; padding:10px 14px; border:1px solid rgba(39,209,127,.28);
            border-radius:999px; background:rgba(39,209,127,.09); color:var(--green); font-size:12px; font-weight:800; text-transform:uppercase;
        }
        .pulse { width:10px; height:10px; border-radius:50%; background:var(--green); box-shadow:0 0 0 0 rgba(39,209,127,.8); animation:pulse 1.8s infinite; }
        @keyframes pulse { 70% { box-shadow:0 0 0 12px rgba(39,209,127,0); } 100% { box-shadow:0 0 0 0 rgba(39,209,127,0); } }
        main { display:grid; grid-template-columns:minmax(260px,.86fr) minmax(460px,1.58fr) minmax(290px,.96fr); gap:14px; min-height:0; }
        .panel {
            min-height:0; border:1px solid var(--line); border-radius:16px; overflow:hidden;
            background:linear-gradient(180deg,var(--panel),rgba(12,12,12,.98)); box-shadow:0 18px 50px var(--shadow);
        }
        body.light .panel { background:linear-gradient(180deg,var(--panel),#f5f0e8); }
        .panel-head { display:flex; justify-content:space-between; align-items:center; gap:12px; padding:15px 16px; border-bottom:1px solid var(--line); background:rgba(201,168,76,.06); }
        .panel-title { margin:0; color:var(--gold); font-size:13px; font-weight:800; text-transform:uppercase; letter-spacing:.16em; }
        .panel-meta { color:var(--muted); font-size:12px; font-weight:700; white-space:nowrap; }
        .watchlist, .alerts, .stats { padding:16px; }
        .watchlist, .alerts { max-height:calc(100vh - 192px); overflow:auto; }
        .watch-item, .alert-card, .stat-card, .market-card {
            border:1px solid rgba(255,255,255,.07); border-radius:14px; background:rgba(255,255,255,.028);
        }
        body.light .watch-item, body.light .alert-card, body.light .stat-card, body.light .market-card { border-color:rgba(91,70,23,.14); background:rgba(255,255,255,.52); }
        .watch-item { display:grid; gap:10px; margin-bottom:10px; padding:12px; cursor:pointer; transition:.15s ease; }
        .watch-item:hover, .watch-item.active { border-color:rgba(201,168,76,.5); background:rgba(201,168,76,.08); transform:translateY(-1px); }
        .watch-top, .watch-price-row, .alert-top, .contract-row, .footer-row { display:flex; align-items:center; justify-content:space-between; gap:10px; }
        .ticker { color:var(--text); font-size:19px; font-weight:800; letter-spacing:.02em; }
        .price { color:var(--text); font-size:16px; font-weight:800; font-variant-numeric:tabular-nums; }
        .change, .direction { font-size:12px; font-weight:800; text-transform:uppercase; }
        .positive, .bullish { color:var(--green); } .negative, .bearish { color:var(--red); } .neutral { color:var(--gold); }
        .phase, .tier {
            display:inline-flex; align-items:center; border:1px solid var(--line); border-radius:999px; padding:5px 8px;
            font-size:10px; font-weight:800; letter-spacing:.08em; text-transform:uppercase;
        }
        .phase.indication { color:#f1c40f; background:rgba(241,196,15,.12); border-color:rgba(241,196,15,.3); }
        .phase.correction { color:var(--amber); background:rgba(232,146,26,.14); border-color:rgba(232,146,26,.36); }
        .phase.continuation { color:var(--green); background:rgba(39,209,127,.11); border-color:rgba(39,209,127,.32); }
        .phase.oi-soft { color:#f1c40f; background:rgba(241,196,15,.12); border-color:rgba(241,196,15,.3); }
        .phase.oi-strong { color:var(--green); background:rgba(39,209,127,.11); border-color:rgba(39,209,127,.32); }
        .tier.alert { color:var(--green); background:rgba(39,209,127,.11); border-color:rgba(39,209,127,.32); }
        .tier.premium { color:var(--amber); background:rgba(232,146,26,.14); border-color:rgba(232,146,26,.36); }
        .tier.livermore { color:var(--gold); background:rgba(201,168,76,.14); border-color:rgba(201,168,76,.42); }
        .score-line { display:grid; grid-template-columns:1fr auto; gap:10px; align-items:center; }
        .score-label { color:var(--muted); font-size:11px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
        .score-num { color:var(--gold); font-size:13px; font-weight:800; font-variant-numeric:tabular-nums; }
        .progress, .bar { height:7px; border-radius:999px; background:rgba(255,255,255,.08); overflow:hidden; }
        body.light .progress, body.light .bar { background:rgba(91,70,23,.12); }
        .progress-fill, .bar-fill { height:100%; width:0%; border-radius:inherit; background:linear-gradient(90deg,var(--red-brand),var(--amber),var(--gold)); }
        .alert-filter {
            display:none; align-items:center; justify-content:space-between; gap:10px; margin-bottom:14px; border:1px solid rgba(201,168,76,.22);
            border-radius:12px; background:rgba(201,168,76,.07); color:var(--muted); padding:10px 12px; font-size:12px; font-weight:700;
        }
        .alert-filter.show { display:flex; }
        .clear-filter { border:0; background:transparent; color:var(--gold); cursor:pointer; font-weight:800; }
        .alert-card { margin-bottom:14px; padding:16px; position:relative; overflow:hidden; }
        .alert-card::before { content:""; position:absolute; inset:0 auto 0 0; width:3px; background:var(--gold); }
        .alert-title { display:flex; flex-wrap:wrap; align-items:center; gap:9px; }
        .score-big { color:var(--gold); font-size:32px; font-weight:800; line-height:1; text-align:right; font-variant-numeric:tabular-nums; }
        .score-big span { color:var(--muted); font-size:12px; }
        .direction-line { margin:12px 0; display:flex; align-items:center; gap:10px; font-size:14px; font-weight:800; letter-spacing:.08em; text-transform:uppercase; }
        .direction-arrow { font-size:24px; line-height:1; }
        .contract-row { border:1px solid rgba(201,168,76,.16); border-radius:12px; background:rgba(201,168,76,.055); padding:10px 11px; margin-bottom:12px; }
        .contract { color:var(--text); font-size:13px; font-weight:800; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
        .copy-btn { border:1px solid rgba(201,168,76,.32); border-radius:8px; background:rgba(201,168,76,.1); color:var(--gold); cursor:pointer; font-size:12px; font-weight:800; padding:5px 8px; }
        .levels { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px; margin-bottom:13px; }
        .level { border:1px solid rgba(255,255,255,.06); border-radius:12px; background:rgba(255,255,255,.025); padding:10px; }
        .level-label { color:var(--muted); font-size:10px; font-weight:800; letter-spacing:.1em; text-transform:uppercase; }
        .level-value { margin-top:4px; color:var(--text); font-size:16px; font-weight:800; font-variant-numeric:tabular-nums; }
        .breakdown { display:grid; gap:9px; margin-bottom:12px; }
        .break-label { display:flex; justify-content:space-between; color:var(--muted); font-size:11px; font-weight:800; text-transform:uppercase; margin-bottom:5px; }
        .signals { color:var(--muted); font-size:12px; line-height:1.45; margin-bottom:10px; }
        .timestamp { color:var(--muted2); font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; }
        .stats-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:11px; margin-bottom:14px; }
        .stat-card { padding:13px; }
        .stat-label { color:var(--muted); font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:.08em; }
        .stat-value { margin-top:7px; color:var(--text); font-size:28px; font-weight:800; font-variant-numeric:tabular-nums; }
        .market-card { padding:16px; margin-bottom:14px; }
        .tide-head { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; }
        .tide-arrow { font-size:48px; line-height:1; }
        .tide-value { font-size:24px; font-weight:800; text-transform:uppercase; }
        .context-row { display:flex; justify-content:space-between; gap:10px; padding:9px 0; border-top:1px solid rgba(255,255,255,.06); color:var(--muted); font-size:12px; }
        .context-row strong { color:var(--text); font-weight:800; text-align:right; }
        .empty { padding:28px 18px; color:var(--muted); text-align:center; border:1px dashed rgba(201,168,76,.25); border-radius:14px; background:rgba(201,168,76,.04); }
        footer { display:flex; justify-content:space-between; align-items:center; gap:16px; color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.12em; padding:0 4px; }
        footer strong { color:var(--gold); }
        @media (max-width:1180px) {
            main { grid-template-columns:1fr; } header { grid-template-columns:1fr; align-items:flex-start; }
            nav, .header-actions { justify-content:flex-start; flex-wrap:wrap; } .watchlist, .alerts { max-height:none; }
        }
        @media (max-width:640px) {
            .terminal { padding:10px; } .stats-grid, .levels { grid-template-columns:1fr; }
            footer, .panel-head, .alert-top, .watch-price-row { align-items:flex-start; flex-direction:column; }
        }
    </style>
</head>
<body>
    <div class="terminal">
        <header>
            <div class="brand">
                <div class="mark">LA</div>
                <div><h1>LIVERMORE AI</h1><div class="subtitle">Institutional flow intelligence terminal</div></div>
            </div>
            <nav>
                <a class="nav-btn" href="/backtesting">BACKTESTING</a>
                <a class="nav-btn" href="/alerts">ALERTAS</a>
                <a class="nav-btn" href="/watchlist">WATCHLIST</a>
            </nav>
            <div class="header-actions">
                <button class="theme-toggle" id="themeToggle" type="button">Modo día</button>
                <div class="status"><span class="pulse"></span> Sistema LIVE</div>
            </div>
        </header>

        <main>
            <section class="panel">
                <div class="panel-head"><h2 class="panel-title">Watchlist</h2><span class="panel-meta" id="watchCount">0 activos</span></div>
                <div class="watchlist" id="watchlist"></div>
            </section>

            <section class="panel">
                <div class="panel-head"><h2 class="panel-title">Feed de Alertas</h2><span class="panel-meta"><strong id="todayCount">0</strong> hoy · Auto-refresh 30s</span></div>
                <div class="alerts">
                    <div class="alert-filter" id="alertFilter"><span>Filtrando por <strong id="filterTicker"></strong></span><button class="clear-filter" type="button" id="clearFilter">LIMPIAR</button></div>
                    <div id="alerts"></div>
                </div>
            </section>

            <section class="panel">
                <div class="panel-head"><h2 class="panel-title">Stats + Market Context</h2><span class="panel-meta" id="lastUpdate">Sin datos</span></div>
                <div class="stats"><div id="marketContext"></div><div class="stats-grid" id="stats"></div></div>
            </section>
        </main>

        <footer>
            <span><strong>LIVERMORE AI TRADING TERMINAL</strong></span>
            <span>Último scan: <strong id="lastScan">--</strong> · Hora ET: <strong id="etClock">--:--:--</strong></span>
        </footer>
    </div>

    <script>
        const els = {
            alerts: document.getElementById("alerts"), alertFilter: document.getElementById("alertFilter"),
            clearFilter: document.getElementById("clearFilter"), filterTicker: document.getElementById("filterTicker"),
            marketContext: document.getElementById("marketContext"), stats: document.getElementById("stats"),
            themeToggle: document.getElementById("themeToggle"), todayCount: document.getElementById("todayCount"),
            watchlist: document.getElementById("watchlist"), watchCount: document.getElementById("watchCount"),
            lastUpdate: document.getElementById("lastUpdate"), lastScan: document.getElementById("lastScan"), etClock: document.getElementById("etClock")
        };
        let latestAlerts = [], latestWatchlist = [], currentFilter = null, lastScanDate = null;
        function escapeHtml(value) { return String(value ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;"); }
        function fmt(value, fallback = "--") { return value === null || value === undefined || value === "" ? fallback : value; }
        function money(value) { const n = Number(value); return Number.isFinite(n) && n > 0 ? "$" + n.toFixed(2) : "--"; }
        function compactMoney(value) {
            const n = Number(value);
            if (!Number.isFinite(n) || n <= 0) return "--";
            if (n >= 1_000_000) return "$" + (n / 1_000_000).toFixed(1).replace(/\\.0$/, "") + "M";
            if (n >= 1_000) return "$" + (n / 1_000).toFixed(0) + "K";
            return "$" + n.toFixed(0);
        }
        function pct(value) { const n = Number(value); return Number.isFinite(n) ? `${n >= 0 ? "+" : ""}${n.toFixed(2)}%` : "--"; }
        function scoreValue(value) { const score = Number(value ?? 0); return Number.isFinite(score) ? Math.max(0, Math.min(100, score)) : 0; }
        function tierLabel(tier) { const value = Number(tier ?? 1); if (value >= 3) return "LIVERMORE"; if (value === 2) return "PREMIUM"; return "ALERT"; }
        function tierClass(tier) { return tierLabel(tier).toLowerCase(); }
        function phaseLabel(phase) { const p = String(phase || "INDICATION").toUpperCase(); if (p.includes("CORRECTION")) return "CORRECTION"; if (p.includes("CONTINUATION")) return "CONTINUATION"; return "INDICATION"; }
        function directionLabel(alert) {
            const d = String(alert.direction || "").toUpperCase();
            if (d.includes("BEAR")) return "BEARISH"; if (d.includes("BULL")) return "BULLISH";
            const entry = Number(alert.entry), tp1 = Number(alert.tp1);
            return Number.isFinite(entry) && Number.isFinite(tp1) && tp1 < entry ? "BEARISH" : "BULLISH";
        }
        function oiBadge(alert) {
            const days = Number(alert.oi_days_growing || alert.oi?.days_growing || 0);
            const growing = Boolean(alert.oi_growing || alert.oi?.oi_growing);
            if (!growing || days < 1) return "";
            const cls = days >= 3 ? "oi-strong" : "oi-soft";
            const label = days >= 3 ? `OI ↑ ${days} días` : "OI ↑";
            return `<span class="phase ${cls}">${label}</span>`;
        }
        function toIBKR(raw) { const m = String(raw || "").match(/^([A-Z]+)(\\d{6})([CP])(\\d{8})$/); if (!m) return raw || ""; return m[1] + " " + m[2] + m[3] + " " + (parseInt(m[4]) / 1000).toString(); }
        async function copyIBKR(button) { const text = button.dataset.contract || ""; if (!text) return; await navigator.clipboard.writeText(text); button.textContent = "COPIADO"; setTimeout(() => { button.textContent = "COPIAR"; }, 1000); }
        async function getJson(url) { const response = await fetch(url, { cache:"no-store" }); if (!response.ok) throw new Error(`${response.status} ${response.statusText}`); return response.json(); }
        function minutesAgo(value) {
            if (!value) return "sin timestamp"; const date = new Date(value); if (Number.isNaN(date.getTime())) return "sin timestamp";
            const mins = Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
            if (mins < 1) return "hace segundos"; if (mins < 60) return `hace ${mins} minutos`;
            const hours = Math.round(mins / 60); if (hours < 24) return `hace ${hours} horas`; return `hace ${Math.round(hours / 24)} días`;
        }
        function institutionalWindow() {
            const parts = new Intl.DateTimeFormat("en-US", { timeZone:"America/New_York", hour:"numeric", minute:"numeric", hour12:false }).formatToParts(new Date());
            const total = Number(parts.find((p) => p.type === "hour")?.value || 0) * 60 + Number(parts.find((p) => p.type === "minute")?.value || 0);
            if (total < 570) return "PRE-MARKET"; if (total < 660) return "ACCUMULATION-MORNING"; if (total < 840) return "QUIET";
            if (total < 960) return "ACCUMULATION-AFTERNOON"; return "POST-MARKET";
        }
        function renderAlerts() {
            const list = currentFilter ? latestAlerts.filter((a) => String(a.ticker || "").toUpperCase() === currentFilter) : latestAlerts;
            els.alertFilter.classList.toggle("show", Boolean(currentFilter)); els.filterTicker.textContent = currentFilter || "";
            if (!list.length) {
                els.alerts.innerHTML = `<div class="empty">"No es el pensar lo que hace dinero, sino el sentarse." Jesse Livermore<br><br>Sin alertas activas por ahora. El tape está respirando.</div>`;
                return;
            }
            els.alerts.innerHTML = list.map((alert) => {
                const b = alert.score_breakdown || {};
                const parts = [["ICC", b.icc], ["Dark Pool", b.dark_pool], ["Flow", b.flow], ["Macro", b.macro]];
                const score = scoreValue(alert.score), contract = alert.contract || [alert.strike, alert.expiration].filter(Boolean).join(" ");
                const ibkr = contract ? toIBKR(contract) : "N/A", direction = directionLabel(alert), dirClass = direction === "BEARISH" ? "bearish" : "bullish";
                const signals = [alert.icc_phase ? `ICC ${alert.icc_phase}` : null, alert.regime, alert.session, alert.signal].filter(Boolean).join(" · ");
                return `<article class="alert-card">
                    <div class="alert-top"><div class="alert-title"><span class="ticker">${escapeHtml(alert.ticker)}</span><span class="tier ${tierClass(alert.tier)}">${tierLabel(alert.tier)}</span>${oiBadge(alert)}</div><div class="score-big">${score}<span>/100</span></div></div>
                    <div class="direction-line ${dirClass}"><span class="direction-arrow">${direction === "BEARISH" ? "↓" : "↑"}</span><span>${direction}</span></div>
                    <div class="contract-row"><span class="contract">${escapeHtml(fmt(ibkr,"N/A"))}</span><span class="score-num">${compactMoney(alert.nominal_value ?? alert.premium)}</span>${contract ? `<button class="copy-btn" data-contract="${escapeHtml(ibkr)}" onclick="copyIBKR(this)">COPIAR</button>` : ""}</div>
                    <div class="levels"><div class="level"><div class="level-label">Entry</div><div class="level-value">${money(alert.entry)}</div></div><div class="level"><div class="level-label">SL</div><div class="level-value">${money(alert.sl)}</div></div><div class="level"><div class="level-label">TP1</div><div class="level-value">${money(alert.tp1)}</div></div><div class="level"><div class="level-label">TP2</div><div class="level-value">${money(alert.tp2)}</div></div></div>
                    <div class="breakdown">${parts.map(([label, value]) => { const s = scoreValue(value); return `<div><div class="break-label"><span>${label}</span><span>${s}</span></div><div class="bar"><div class="bar-fill" style="width:${s}%"></div></div></div>`; }).join("")}</div>
                    <div class="signals">${escapeHtml(signals || "Sin señales activas registradas.")}</div><div class="timestamp">${minutesAgo(alert.date)}</div>
                </article>`;
            }).join("");
        }
        function renderStats(stats) {
            const cards = [["Total alertas", stats.total], ["Hoy", stats.today], ["Win Rate", `${fmt(stats.win_rate, 0)}%`], ["Abiertas", stats.open], ["Wins", stats.wins], ["Losses", stats.losses]];
            els.stats.innerHTML = cards.map(([label, value]) => `<div class="stat-card"><div class="stat-label">${label}</div><div class="stat-value">${escapeHtml(fmt(value,0))}</div></div>`).join("");
        }
        function renderMarketContext(tide, stats) {
            const direction = String(tide?.market_direction || "NEUTRAL").toUpperCase(), cls = direction === "BULLISH" ? "bullish" : direction === "BEARISH" ? "bearish" : "neutral";
            const arrow = direction === "BULLISH" ? "↑" : direction === "BEARISH" ? "↓" : "→";
            els.marketContext.innerHTML = `<div class="market-card"><div class="tide-head"><div><div class="stat-label">Market Tide</div><div class="tide-value ${cls}">${direction}</div></div><div class="tide-arrow ${cls}">${arrow}</div></div>
                <div class="context-row"><span>Score promedio del día</span><strong>${fmt(stats.avg_score_today, 0)}/100</strong></div>
                <div class="context-row"><span>Ventana institucional</span><strong>${institutionalWindow()}</strong></div>
                <div class="context-row"><span>Net call premium</span><strong>${money(tide?.net_call_premium)}</strong></div>
                <div class="context-row"><span>Net put premium</span><strong>${money(tide?.net_put_premium)}</strong></div></div>`;
        }
        function renderWatchlist(items) {
            const scores = new Map(), phases = new Map();
            latestAlerts.forEach((a) => { const t = String(a.ticker || "").toUpperCase(); if (t && !scores.has(t)) scores.set(t, scoreValue(a.score)); if (t && !phases.has(t)) phases.set(t, phaseLabel(a.icc_phase)); });
            let list = Array.isArray(items) ? items : [];
            if (!list.length && latestAlerts.length) list = latestAlerts.map((a) => ({ ticker:a.ticker, current_price:a.entry, day_change_pct:0, icc_phase:a.icc_phase, score:a.score }));
            els.watchCount.textContent = `${list.length} activos`;
            if (!list.length) { els.watchlist.innerHTML = `<div class="empty">Watchlist vacía. Agrega tickers desde la API para monitorearlos aquí.</div>`; return; }
            els.watchlist.innerHTML = list.map((item) => {
                const ticker = String(item.ticker || "N/A").toUpperCase(), score = scoreValue(item.score ?? scores.get(ticker) ?? 0), phase = phaseLabel(item.icc_phase ?? phases.get(ticker));
                const change = Number(item.day_change_pct ?? 0), changeClass = change > 0 ? "positive" : change < 0 ? "negative" : "neutral";
                return `<div class="watch-item ${currentFilter === ticker ? "active" : ""}" onclick="filterTicker('${escapeHtml(ticker)}')"><div class="watch-top"><span class="ticker">${escapeHtml(ticker)}</span><span class="phase ${phase.toLowerCase()}">${phase}</span></div>
                    <div class="watch-price-row"><span class="price">${money(item.current_price)}</span><span class="change ${changeClass}">${pct(change)}</span></div>
                    <div class="score-line"><span class="score-label">Score Livermore</span><span class="score-num">${score}/100</span></div><div class="progress"><div class="progress-fill" style="width:${score}%"></div></div></div>`;
            }).join("");
        }
        function filterTicker(ticker) { currentFilter = ticker; renderAlerts(); renderWatchlist(latestWatchlist); }
        els.clearFilter.addEventListener("click", () => { currentFilter = null; renderAlerts(); renderWatchlist(latestWatchlist); });
        els.themeToggle.addEventListener("click", () => {
            document.body.classList.toggle("light"); const light = document.body.classList.contains("light");
            els.themeToggle.textContent = light ? "Modo noche" : "Modo día"; localStorage.setItem("livermore-theme", light ? "light" : "dark");
        });
        if (localStorage.getItem("livermore-theme") === "light") { document.body.classList.add("light"); els.themeToggle.textContent = "Modo noche"; }
        async function refreshDashboard() {
            try {
                const [alerts, stats, watchlist, marketTide] = await Promise.all([getJson("/api/alerts?limit=200"), getJson("/api/stats"), getJson("/api/watchlist"), getJson("/api/market-tide")]);
                latestAlerts = Array.isArray(alerts) ? alerts : []; latestWatchlist = Array.isArray(watchlist) ? watchlist : [];
                renderAlerts(); renderStats(stats); renderMarketContext(marketTide, stats); renderWatchlist(latestWatchlist);
                els.todayCount.textContent = stats.today ?? 0; lastScanDate = stats.last_scan ? new Date(stats.last_scan) : (latestAlerts[0]?.date ? new Date(latestAlerts[0].date) : null);
                els.lastUpdate.textContent = "Actualizado"; updateLastScan();
            } catch (error) { els.alerts.innerHTML = `<div class="empty">Error cargando datos: ${escapeHtml(error.message)}</div>`; els.lastUpdate.textContent = "Error"; }
        }
        function updateClock() { els.etClock.textContent = new Intl.DateTimeFormat("es-US", { timeZone:"America/New_York", hour:"2-digit", minute:"2-digit", second:"2-digit", hour12:false }).format(new Date()); }
        function updateLastScan() { els.lastScan.textContent = lastScanDate ? minutesAgo(lastScanDate.toISOString()) : "--"; }
        updateClock(); refreshDashboard(); setInterval(updateClock, 1000); setInterval(updateLastScan, 1000); setInterval(refreshDashboard, 30000);
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


def _infer_direction(a: Alert) -> str:
    regime = (a.regime or "").upper()
    if "DOWN" in regime or "BEAR" in regime:
        return "BEARISH"
    if a.entry_price is not None and a.target1 is not None and a.target1 < a.entry_price:
        return "BEARISH"
    return "BULLISH"


def _format_oi_trend(a: Alert) -> str:
    days = a.oi_days_growing or 0
    if not a.oi_growing or days < 1:
        return "--"
    suffix = f" ({round(a.oi_change_pct, 2)}%)" if a.oi_change_pct is not None else ""
    return f"OI ↑ {days}d{suffix}"


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
                <a class="ibkr-contract" data-raw="{escape(a.contract or '', quote=True)}" data-ticker="{escape(a.ticker or '', quote=True)}" href="#" target="_blank" rel="noopener">{escape(a.contract or "--")}</a>
                <button class="copy-btn" data-contract="" onclick="copyIBKR(this)" title="Copiar contrato IBKR">📋</button>
            </td>
            <td>${round((a.premium or 0) / 1_000_000, 1)}M</td>
            <td>{escape(_format_oi_trend(a))}</td>
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
        .ibkr-contract { color:var(--blue); font-weight:800; text-decoration:none; }
        .ibkr-contract:hover { text-decoration:underline; }
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
                    <th>Fecha Entrada</th><th>Ticker</th><th>Contrato</th><th>Nominal</th><th>OI Trend</th><th>Score</th><th>Dirección</th><th>P&L%</th><th>Status</th>
                </tr>
            </thead>
            <tbody>""" + (rows or '<tr><td colspan="9">No hay backtests cargados.</td></tr>') + """</tbody>
        </table>
    </section>
    <script>
        function toIBKR(raw) {
            const m = String(raw || "").match(/^([A-Z]+)(\\d{6})([CP])(\\d{8})$/);
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
            const ticker = el.dataset.ticker || "";
            el.textContent = ibkr || "--";
            el.href = ticker
                ? `https://www.interactivebrokers.com/en/trading/contract-search.php?symbol=${encodeURIComponent(ticker)}`
                : "#";
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
        "direction": _infer_direction(a),
        "icc_phase": a.icc_phase,
        "entry":     a.entry_price,
        "sl":        a.stop_loss,
        "tp1":       a.target1,
        "tp2":       a.target2,
        "contract":  a.contract,
        "strike":    a.strike,
        "expiration":a.expiration,
        "delta":     a.delta,
        "premium":   a.premium,
        "nominal_value": a.premium,
        "oi_growing": bool(a.oi_growing),
        "oi_change_pct": a.oi_change_pct or 0,
        "oi_days_growing": a.oi_days_growing or 0,
        "oi_today": a.oi_today,
        "oi_yesterday": a.oi_yesterday,
        "oi": {
            "oi_growing": bool(a.oi_growing),
            "oi_change_pct": a.oi_change_pct or 0,
            "days_growing": a.oi_days_growing or 0,
            "today_oi": a.oi_today,
            "yesterday_oi": a.oi_yesterday,
        },
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


@app.get("/alerts", response_class=HTMLResponse)
async def alerts_page():
    return """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>LIVERMORE AI — ALERTAS</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root { --bg:#0a0a0a; --panel:#111; --line:rgba(201,168,76,.24); --gold:#c9a84c; --text:#f2f2f2; --muted:#8f8f8f; --green:#27d17f; --red:#ff5c5c; --blue:#93c5fd; }
        * { box-sizing:border-box; }
        body { margin:0; min-height:100vh; color:var(--text); font-family:"Inter",system-ui,sans-serif; background:radial-gradient(circle at 15% 0%,rgba(201,168,76,.16),transparent 32%),var(--bg); padding:22px; }
        header { display:flex; justify-content:space-between; align-items:center; gap:16px; border:1px solid var(--line); border-radius:18px; padding:18px 22px; background:linear-gradient(135deg,rgba(17,17,17,.98),rgba(10,10,10,.96)); box-shadow:0 24px 80px rgba(0,0,0,.45); }
        h1 { margin:0; color:var(--gold); font-size:clamp(28px,3vw,40px); font-weight:800; }
        .back { color:var(--gold); text-decoration:none; font-weight:800; border:1px solid rgba(201,168,76,.28); border-radius:999px; padding:10px 14px; background:rgba(201,168,76,.1); }
        .panel { margin-top:18px; border:1px solid var(--line); border-radius:18px; overflow:hidden; background:rgba(17,17,17,.96); }
        .panel-head { padding:16px 18px; color:var(--gold); background:rgba(201,168,76,.08); border-bottom:1px solid var(--line); font-weight:800; text-transform:uppercase; letter-spacing:.12em; }
        table { width:100%; border-collapse:collapse; }
        th,td { padding:13px 14px; border-bottom:1px solid rgba(255,255,255,.06); text-align:left; font-size:13px; white-space:nowrap; }
        th { color:var(--muted); text-transform:uppercase; letter-spacing:.1em; font-size:11px; }
        .ticker { color:#fff; font-weight:800; }
        .tier { color:var(--gold); font-weight:800; }
        .empty { padding:28px; color:var(--muted); text-align:center; }
        .copy-btn { margin-left:8px; border:1px solid rgba(201,168,76,.28); border-radius:8px; background:rgba(201,168,76,.1); color:var(--gold); cursor:pointer; font-size:13px; padding:4px 7px; }
        .ibkr-contract { color:var(--blue); font-weight:800; text-decoration:none; }
        .ibkr-contract:hover { text-decoration:underline; }
        @media (max-width:1100px) { header { flex-direction:column; align-items:flex-start; } .panel { overflow:auto; } table { min-width:1100px; } }
    </style>
</head>
<body>
    <header>
        <div>
            <h1>LIVERMORE AI — ALERTAS</h1>
            <div style="color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.16em">Alertas activas en tiempo real</div>
        </div>
        <a class="back" href="/">← Dashboard</a>
    </header>
    <section class="panel">
        <div class="panel-head">Feed activo — auto-refresh 30s</div>
        <table>
            <thead>
                <tr><th>Fecha</th><th>Ticker</th><th>Score</th><th>Tier</th><th>Dirección</th><th>Contrato</th><th>Nominal</th><th>Entry</th><th>SL</th><th>TP1</th><th>TP2</th><th>Status</th></tr>
            </thead>
            <tbody id="alertsBody"><tr><td colspan="12" class="empty">Cargando alertas...</td></tr></tbody>
        </table>
    </section>
    <script>
        function escapeHtml(value) {
            return String(value ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;");
        }
        function toIBKR(raw) {
            const m = String(raw || "").match(/^([A-Z]+)(\\d{6})([CP])(\\d{8})$/);
            if (!m) return raw || "";
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
        function tierLabel(tier) {
            const value = Number(tier ?? 1);
            if (value >= 3) return "LIVERMORE";
            if (value === 2) return "PREMIUM";
            return "ALERT";
        }
        function fmtMoney(value) {
            const n = Number(value);
            return Number.isFinite(n) && n > 0 ? "$" + n.toFixed(2) : "--";
        }
        function fmtNominal(value) {
            const n = Number(value);
            if (!Number.isFinite(n) || n <= 0) return "--";
            if (n >= 1_000_000) return "$" + (n / 1_000_000).toFixed(1).replace(/\\.0$/, "") + "M";
            if (n >= 1_000) return "$" + (n / 1_000).toFixed(0) + "K";
            return "$" + n.toFixed(0);
        }
        function fmtDate(value) {
            if (!value) return "--";
            return new Intl.DateTimeFormat("es-US", { timeZone:"America/New_York", month:"short", day:"numeric", hour:"numeric", minute:"2-digit" }).format(new Date(value));
        }
        async function loadAlerts() {
            const body = document.getElementById("alertsBody");
            try {
                const alerts = await fetch("/api/alerts?limit=200", { cache:"no-store" }).then(r => r.json());
                if (!alerts.length) {
                    body.innerHTML = `<tr><td colspan="12" class="empty">No hay alertas activas.</td></tr>`;
                    return;
                }
                body.innerHTML = alerts.map((a) => {
                    const raw = a.contract || "";
                    const ibkr = toIBKR(raw);
                    const contract = ibkr ? `<a class="ibkr-contract" href="https://www.interactivebrokers.com/en/trading/contract-search.php?symbol=${encodeURIComponent(a.ticker || "")}" target="_blank" rel="noopener">${escapeHtml(ibkr)}</a><button class="copy-btn" data-contract="${escapeHtml(ibkr)}" onclick="copyIBKR(this)">📋</button>` : "--";
                    return `<tr>
                        <td>${fmtDate(a.date)}</td><td class="ticker">${escapeHtml(a.ticker)}</td><td>${a.score ?? 0}/100</td><td class="tier">${tierLabel(a.tier)}</td>
                        <td>${escapeHtml(a.direction || "--")}</td><td>${contract}</td><td>${fmtNominal(a.nominal_value ?? a.premium)}</td><td>${fmtMoney(a.entry)}</td><td>${fmtMoney(a.sl)}</td><td>${fmtMoney(a.tp1)}</td><td>${fmtMoney(a.tp2)}</td><td>${escapeHtml(a.status || "--")}</td>
                    </tr>`;
                }).join("");
            } catch (error) {
                body.innerHTML = `<tr><td colspan="12" class="empty">Error cargando alertas: ${escapeHtml(error.message)}</td></tr>`;
            }
        }
        loadAlerts();
        setInterval(loadAlerts, 30000);
    </script>
</body>
</html>
"""


@app.get("/watchlist", response_class=HTMLResponse)
async def watchlist_page():
    return """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>LIVERMORE AI — WATCHLIST</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root { --bg:#0a0a0a; --panel:#111; --line:rgba(201,168,76,.24); --gold:#c9a84c; --text:#f2f2f2; --muted:#8f8f8f; --green:#27d17f; --red:#ff5c5c; }
        * { box-sizing:border-box; }
        body { margin:0; min-height:100vh; color:var(--text); font-family:"Inter",system-ui,sans-serif; background:radial-gradient(circle at 15% 0%,rgba(201,168,76,.16),transparent 32%),var(--bg); padding:22px; }
        header { display:flex; justify-content:space-between; align-items:center; gap:16px; border:1px solid var(--line); border-radius:18px; padding:18px 22px; background:linear-gradient(135deg,rgba(17,17,17,.98),rgba(10,10,10,.96)); box-shadow:0 24px 80px rgba(0,0,0,.45); }
        h1 { margin:0; color:var(--gold); font-size:clamp(28px,3vw,40px); font-weight:800; }
        .back { color:var(--gold); text-decoration:none; font-weight:800; border:1px solid rgba(201,168,76,.28); border-radius:999px; padding:10px 14px; background:rgba(201,168,76,.1); }
        .panel { margin-top:18px; border:1px solid var(--line); border-radius:18px; overflow:hidden; background:rgba(17,17,17,.96); }
        .panel-head { padding:16px 18px; color:var(--gold); background:rgba(201,168,76,.08); border-bottom:1px solid var(--line); font-weight:800; text-transform:uppercase; letter-spacing:.12em; }
        form { display:flex; gap:10px; padding:16px; border-bottom:1px solid rgba(255,255,255,.06); }
        input { flex:1; border:1px solid var(--line); border-radius:12px; background:#0a0a0a; color:var(--text); padding:12px 14px; font-weight:800; text-transform:uppercase; }
        button { border:1px solid rgba(201,168,76,.32); border-radius:12px; background:rgba(201,168,76,.12); color:var(--gold); cursor:pointer; font-weight:800; padding:10px 14px; }
        .danger { border-color:rgba(255,92,92,.32); color:var(--red); background:rgba(255,92,92,.1); }
        .item { display:flex; justify-content:space-between; align-items:center; gap:14px; padding:14px 16px; border-bottom:1px solid rgba(255,255,255,.06); }
        .ticker { color:#fff; font-size:18px; font-weight:800; }
        .notes { margin-top:4px; color:var(--muted); font-size:13px; }
        .empty { padding:28px; color:var(--muted); text-align:center; }
        @media (max-width:700px) { header, form, .item { flex-direction:column; align-items:stretch; } }
    </style>
</head>
<body>
    <header>
        <div>
            <h1>LIVERMORE AI — WATCHLIST</h1>
            <div style="color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.16em">Tickers activos que monitorea el scanner</div>
        </div>
        <a class="back" href="/">← Dashboard</a>
    </header>
    <section class="panel">
        <div class="panel-head">Gestión de watchlist</div>
        <form id="addForm">
            <input id="tickerInput" placeholder="Ticker, ej: NVDA" maxlength="10" required />
            <input id="notesInput" placeholder="Notas opcionales" />
            <button type="submit">AGREGAR</button>
        </form>
        <div id="watchlistItems"><div class="empty">Cargando watchlist...</div></div>
    </section>
    <script>
        function escapeHtml(value) {
            return String(value ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;");
        }
        async function loadWatchlist() {
            const target = document.getElementById("watchlistItems");
            try {
                const items = await fetch("/api/watchlist", { cache:"no-store" }).then(r => r.json());
                if (!items.length) {
                    target.innerHTML = `<div class="empty">Watchlist vacía. Agrega un ticker para empezar.</div>`;
                    return;
                }
                target.innerHTML = items.map((item) => `
                    <div class="item">
                        <div><div class="ticker">${escapeHtml(item.ticker)}</div><div class="notes">${escapeHtml(item.notes || "sin notas")}</div></div>
                        <button class="danger" onclick="removeTicker(${item.id})">ELIMINAR</button>
                    </div>
                `).join("");
            } catch (error) {
                target.innerHTML = `<div class="empty">Error cargando watchlist: ${escapeHtml(error.message)}</div>`;
            }
        }
        async function removeTicker(id) {
            await fetch(`/api/watchlist/${id}`, { method:"DELETE" });
            loadWatchlist();
        }
        document.getElementById("addForm").addEventListener("submit", async (event) => {
            event.preventDefault();
            const ticker = document.getElementById("tickerInput").value.trim().toUpperCase();
            const notes = document.getElementById("notesInput").value.trim();
            if (!ticker) return;
            await fetch(`/api/watchlist?ticker=${encodeURIComponent(ticker)}&notes=${encodeURIComponent(notes)}`, { method:"POST" });
            event.target.reset();
            loadWatchlist();
        });
        loadWatchlist();
    </script>
</body>
</html>
"""


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
        ).all()
        today_count = len(today_alerts)
        score_values = [a.score_total for a in today_alerts if a.score_total is not None]
        latest = active.order_by(Alert.created_at.desc()).first()
        return {
            "total":    total,
            "today":    today_count,
            "wins":     wins,
            "losses":   losses,
            "open":     active.filter(Alert.status == "pending").count(),
            "win_rate": round(wins / closed * 100, 1) if closed > 0 else 0,
            "avg_score_today": round(sum(score_values) / len(score_values), 1) if score_values else 0,
            "last_scan": latest.created_at.isoformat() if latest and latest.created_at else None,
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


@app.get("/api/market-tide")
async def get_market_tide():
    try:
        from core.uw_fetcher import UWFetcher
        tide = await UWFetcher().get_market_tide()
        return tide or {
            "net_call_premium": 0,
            "net_put_premium": 0,
            "net_volume": 0,
            "market_direction": "NEUTRAL",
            "call_improving": False,
            "bullish": False,
        }
    except Exception as e:
        logger.exception("get_market_tide error")
        raise HTTPException(500, f"market_tide_error: {type(e).__name__}: {e}")


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
    screener_by_ticker = {}
    try:
        from core.uw_fetcher import UWFetcher
        uw = UWFetcher()
        screener = await uw.get_screener(limit=50)
        screener_by_ticker = {
            str(row.get("ticker", "")).upper(): row
            for row in screener
            if row.get("ticker")
        }
    except Exception as e:
        logger.warning(f"watchlist screener hydrate error: {e}")

    def as_float(value, default=0):
        try:
            if value is None or value == "":
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def day_change_pct(row):
        for key in ("change_percent", "change_pct", "day_change_percent", "price_change_percent", "pct_change"):
            if key in row:
                return round(as_float(row.get(key)), 2)
        price = as_float(row.get("price") or row.get("last_price") or row.get("close"))
        prev_close = as_float(row.get("prev_close"))
        if price and prev_close:
            return round(((price - prev_close) / prev_close) * 100, 2)
        return 0

    result = []
    for i in items:
        ticker = i.ticker.upper()
        screener_row = screener_by_ticker.get(ticker, {})
        latest = (
            db.query(Alert)
            .filter(Alert.ticker == ticker)
            .filter(Alert.mode != "BACKTEST")
            .order_by(Alert.created_at.desc())
            .first()
        )
        current_price = as_float(screener_row.get("prev_close"), None)
        change_pct = day_change_pct(screener_row)
        if latest:
            current_price = latest.current_price or latest.entry_price or current_price
            if latest.entry_price and current_price:
                change_pct = round(((current_price - latest.entry_price) / latest.entry_price) * 100, 2)
        result.append({
            "id": i.id,
            "ticker": ticker,
            "notes": i.notes,
            "current_price": current_price,
            "day_change_pct": change_pct,
            "icc_phase": latest.icc_phase if latest else "INDICATION",
            "score": latest.score_total if latest else 0,
        })
    return result


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
