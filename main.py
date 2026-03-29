"""
Livermore AI — FastAPI Backend
REST API for the dashboard + scheduler for the scanner
"""
import os
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, date
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from sqlalchemy.orm import Session
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from core.models import init_db, get_db, Alert, WatchlistItem, SystemLog
from core.scanner import LivermoreScanner
from bot.discord_bot import create_bot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("livermore.app")

NY_TZ = pytz.timezone("America/New_York")

# ─── GLOBAL INSTANCES ────────────────────────────────────
scanner    = None
discord_bot = None
scheduler  = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scanner, discord_bot, scheduler

    logger.info("Starting Livermore AI...")

    # Init database
    init_db()

    # Create scanner
    discord_bot = create_bot()
    scanner = LivermoreScanner(discord_bot=discord_bot)
    discord_bot.scanner = scanner

    # Start Discord bot in background
    discord_token = os.getenv("DISCORD_BOT_TOKEN", "")
    if discord_token:
        asyncio.create_task(discord_bot.start(discord_token))
        logger.info("Discord bot starting...")

    # Start scheduler
    scheduler = AsyncIOScheduler(timezone=NY_TZ)

    # Scan every 5 minutes during market hours (8am-8pm ET, Mon-Fri)
    scheduler.add_job(
        scanner.run_scan,
        CronTrigger(day_of_week="mon-fri", hour="8-20", minute="*/5", timezone=NY_TZ),
        id="main_scan",
        max_instances=1,
    )

    scheduler.start()
    logger.info("✓ Livermore AI fully started")

    yield

    scheduler.shutdown()
    if discord_bot:
        await discord_bot.close()
    logger.info("Livermore AI shutdown")


# ─── APP ─────────────────────────────────────────────────
app = FastAPI(
    title="Livermore AI",
    description="Institutional options flow scanner with ICC detection",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── HEALTH ──────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat(), "version": "1.0.0"}


# ─── DASHBOARD ───────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the main dashboard"""
    if os.path.exists("static/index.html"):
        with open("static/index.html") as f:
            return f.read()
    return "<h1>Livermore AI — Dashboard loading...</h1>"


# ─── ALERTS API ──────────────────────────────────────────
@app.get("/api/alerts")
async def get_alerts(
    status: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    limit:  int = Query(50, le=200),
    db: Session = Depends(get_db)
):
    query = db.query(Alert).order_by(Alert.created_at.desc())
    if status:
        query = query.filter(Alert.status == status)
    if ticker:
        query = query.filter(Alert.ticker == ticker.upper())
    alerts = query.limit(limit).all()

    return [{
        "id":           a.id,
        "ticker":       a.ticker,
        "asset_type":   a.asset_type,
        "mode":         a.mode,
        "score":        a.score_total,
        "score_icc":    a.score_icc,
        "score_dp":     a.score_darkpool,
        "score_flow":   a.score_flow,
        "entry":        a.entry_price,
        "stop_loss":    a.stop_loss,
        "target1":      a.target1,
        "target2":      a.target2,
        "current":      a.current_price,
        "contract":     a.contract,
        "strike":       a.strike,
        "expiration":   a.expiration,
        "delta":        a.delta,
        "premium":      a.premium,
        "signal":       a.signal_summary,
        "icc_signal":   a.icc_signal,
        "regime":       a.regime,
        "session":      a.market_session,
        "status":       a.status,
        "pnl_pct":      a.pnl_pct,
        "pnl_dollar":   a.pnl_dollar,
        "created_at":   a.created_at.isoformat() if a.created_at else None,
    } for a in alerts]


@app.patch("/api/alerts/{alert_id}")
async def update_alert(
    alert_id: int,
    status:     Optional[str]  = None,
    pnl_pct:    Optional[float]= None,
    pnl_dollar: Optional[float]= None,
    current:    Optional[float]= None,
    db: Session = Depends(get_db)
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if status:     alert.status = status
    if pnl_pct is not None:    alert.pnl_pct = pnl_pct
    if pnl_dollar is not None: alert.pnl_dollar = pnl_dollar
    if current is not None:    alert.current_price = current
    if status in ("win", "loss"):
        alert.closed_at = datetime.utcnow()

    db.commit()

    # Post victory to Discord if win
    if status == "win" and discord_bot and alert.pnl_pct:
        await discord_bot.announce_victory(
            ticker=alert.ticker,
            pnl_pct=alert.pnl_pct,
            pnl_dollar=alert.pnl_dollar or 0,
            contract=alert.contract or alert.ticker,
        )

    return {"ok": True}


# ─── STATS API ───────────────────────────────────────────
@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    total   = db.query(Alert).count()
    wins    = db.query(Alert).filter(Alert.status == "win").count()
    losses  = db.query(Alert).filter(Alert.status == "loss").count()
    open_   = db.query(Alert).filter(Alert.status == "open").count()
    pending = db.query(Alert).filter(Alert.status == "pending").count()

    closed = wins + losses
    win_rate = round(wins / closed * 100, 1) if closed > 0 else 0

    # Average P&L
    pnl_alerts = db.query(Alert).filter(Alert.pnl_pct.isnot(None)).all()
    avg_pnl = round(sum(a.pnl_pct for a in pnl_alerts) / len(pnl_alerts), 1) if pnl_alerts else 0

    # Average score
    scored = db.query(Alert).filter(Alert.score_total.isnot(None)).all()
    avg_score = round(sum(a.score_total for a in scored) / len(scored)) if scored else 0

    # Best trade
    best = db.query(Alert).filter(Alert.status == "win").order_by(Alert.pnl_pct.desc()).first()

    return {
        "total":      total,
        "wins":       wins,
        "losses":     losses,
        "open":       open_,
        "pending":    pending,
        "win_rate":   win_rate,
        "avg_pnl":    avg_pnl,
        "avg_score":  avg_score,
        "best_pnl":   best.pnl_pct if best else None,
        "best_ticker":best.ticker if best else None,
    }


# ─── WATCHLIST API ───────────────────────────────────────
@app.get("/api/watchlist")
async def get_watchlist(db: Session = Depends(get_db)):
    items = db.query(WatchlistItem).filter(WatchlistItem.active == True).all()
    return [{"id": i.id, "ticker": i.ticker, "notes": i.notes} for i in items]


@app.post("/api/watchlist")
async def add_to_watchlist(ticker: str, notes: str = "", db: Session = Depends(get_db)):
    existing = db.query(WatchlistItem).filter(WatchlistItem.ticker == ticker.upper()).first()
    if existing:
        existing.active = True
        db.commit()
        return {"ok": True, "id": existing.id}

    item = WatchlistItem(ticker=ticker.upper(), notes=notes)
    db.add(item)
    db.commit()
    return {"ok": True, "id": item.id}


@app.delete("/api/watchlist/{item_id}")
async def remove_from_watchlist(item_id: int, db: Session = Depends(get_db)):
    item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
    if item:
        item.active = False
        db.commit()
    return {"ok": True}


# ─── MANUAL SCAN ─────────────────────────────────────────
@app.post("/api/scan")
async def trigger_scan():
    if scanner:
        asyncio.create_task(scanner.run_scan())
        return {"ok": True, "message": "Scan iniciado"}
    return {"ok": False, "message": "Scanner not ready"}


# ─── ENTRY POINT ─────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
