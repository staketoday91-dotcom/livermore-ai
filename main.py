import os
import logging
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
import pytz

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
    return """<html><body style="background:#0a0a0a;color:#c9a84c;font-family:monospace;padding:40px;text-align:center">
    <h1 style="font-size:48px">Livermore AI</h1>
    <p style="color:#888">Sistema activo. Scanner corriendo.</p>
    <p><a href="/api/stats"     style="color:#c9a84c">Stats</a> &nbsp;|&nbsp;
       <a href="/api/alerts"    style="color:#c9a84c">Alertas</a> &nbsp;|&nbsp;
       <a href="/api/watchlist" style="color:#c9a84c">Watchlist</a> &nbsp;|&nbsp;
       <a href="/docs"          style="color:#c9a84c">API Docs</a></p>
    </body></html>"""


@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    try:
        total  = db.query(Alert).count()
        wins   = db.query(Alert).filter(Alert.status == "win").count()
        losses = db.query(Alert).filter(Alert.status == "loss").count()
        closed = wins + losses
        today  = datetime.utcnow().date()
        today_alerts = db.query(Alert).filter(
            Alert.created_at >= datetime(today.year, today.month, today.day)
        ).count()
        return {
            "total":    total,
            "today":    today_alerts,
            "wins":     wins,
            "losses":   losses,
            "open":     db.query(Alert).filter(Alert.status == "pending").count(),
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
        q = db.query(Alert).order_by(Alert.created_at.desc())
        if status:
            q = q.filter(Alert.status == status)
        if tier:
            try:
                q = q.filter(Alert.tier == int(tier))
            except ValueError:
                pass
        return [{
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
            "pnl":       a.pnl_pct,
            "score_breakdown": {
                "icc":       a.score_icc,
                "dark_pool": a.score_darkpool,
                "flow":      a.score_flow,
                "macro":     getattr(a, "score_macro", None) or a.score_regime,
            },
            "date": a.created_at.isoformat() if a.created_at else None,
        } for a in q.limit(limit).all()]
    except Exception as e:
        logger.exception("get_alerts error")
        raise HTTPException(500, f"alerts_error: {type(e).__name__}: {e}")


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
