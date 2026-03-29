import os
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import pytz

from core.models import init_db, get_db, Alert, WatchlistItem

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("livermore.app")

NY_TZ = pytz.timezone("America/New_York")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Livermore AI...")
    init_db()
    logger.info("Livermore AI ready")
    yield
    logger.info("Livermore AI shutdown")

app = FastAPI(title="Livermore AI", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat(), "version": "1.0.0"}

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """
    <html><body style="background:#0a0a0a;color:#c9a84c;font-family:monospace;padding:40px">
    <h1>Livermore AI</h1>
    <p>Sistema activo. Base de datos conectada.</p>
    <p><a href="/api/stats" style="color:#c9a84c">Ver estadisticas</a></p>
    <p><a href="/docs" style="color:#c9a84c">API docs</a></p>
    </body></html>
    """

@app.get("/api/alerts")
async def get_alerts(
    status: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db)
):
    query = db.query(Alert).order_by(Alert.created_at.desc())
    if status:
        query = query.filter(Alert.status == status)
    if ticker:
        query = query.filter(Alert.ticker == ticker.upper())
    alerts = query.limit(limit).all()
    return [{
        "id": a.id, "ticker": a.ticker, "score": a.score_total,
        "entry": a.entry_price, "stop_loss": a.stop_loss,
        "target1": a.target1, "target2": a.target2,
        "contract": a.contract, "signal": a.signal_summary,
        "status": a.status, "pnl_pct": a.pnl_pct,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    } for a in alerts]

@app.patch("/api/alerts/{alert_id}")
async def update_alert(
    alert_id: int,
    status: Optional[str] = None,
    pnl_pct: Optional[float] = None,
    pnl_dollar: Optional[float] = None,
    db: Session = Depends(get_db)
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    if status: alert.status = status
    if pnl_pct is not None: alert.pnl_pct = pnl_pct
    if pnl_dollar is not None: alert.pnl_dollar = pnl_dollar
    db.commit()
    return {"ok": True}

@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    total   = db.query(Alert).count()
    wins    = db.query(Alert).filter(Alert.status == "win").count()
    losses  = db.query(Alert).filter(Alert.status == "loss").count()
    open_   = db.query(Alert).filter(Alert.status == "open").count()
    closed  = wins + losses
    win_rate = round(wins / closed * 100, 1) if closed > 0 else 0
    best = db.query(Alert).filter(Alert.status == "win").order_by(Alert.pnl_pct.desc()).first()
    return {
        "total": total, "wins": wins, "losses": losses,
        "open": open_, "win_rate": win_rate,
        "best_pnl": best.pnl_pct if best else None,
        "best_ticker": best.ticker if best else None,
    }

@app.get("/api/watchlist")
async def get_watchlist(db: Session = Depends(get_db)):
    items = db.query(WatchlistItem).filter(WatchlistItem.active == True).all()
    return [{"id": i.id, "ticker": i.ticker, "notes": i.notes} for i in items]

@app.post("/api/watchlist")
async def add_watchlist(ticker: str, notes: str = "", db: Session = Depends(get_db)):
    item = WatchlistItem(ticker=ticker.upper(), notes=notes)
    db.add(item)
    db.commit()
    return {"ok": True, "id": item.id}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
