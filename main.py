import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy import create_engine, Column, Integer, Float, String, Boolean, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import pytz

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("livermore")

DATABASE_URL = os.getenv("DATABASE_URL", "").replace("postgresql://", "postgresql+psycopg2://")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Alert(Base):
    __tablename__ = "alerts"
    id           = Column(Integer, primary_key=True, index=True)
    ticker       = Column(String(10), nullable=False)
    score_total  = Column(Integer)
    entry_price  = Column(Float)
    stop_loss    = Column(Float)
    target1      = Column(Float)
    target2      = Column(Float)
    contract     = Column(String(100))
    signal_summary = Column(Text)
    status       = Column(String(20), default="pending")
    pnl_pct      = Column(Float)
    pnl_dollar   = Column(Float)
    created_at   = Column(DateTime, default=datetime.utcnow)

class WatchlistItem(Base):
    __tablename__ = "watchlist"
    id       = Column(Integer, primary_key=True)
    ticker   = Column(String(10), nullable=False)
    notes    = Column(Text)
    active   = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    logger.info("Livermore AI started — DB ready")
    yield

app = FastAPI(title="Livermore AI", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return """<html><body style="background:#0a0a0a;color:#c9a84c;font-family:monospace;padding:40px;text-align:center">
    <h1 style="font-size:48px">Livermore AI</h1>
    <p style="color:#888">Sistema activo. Base de datos conectada.</p>
    <p><a href="/api/stats" style="color:#c9a84c">Estadisticas</a> &nbsp;|&nbsp; 
    <a href="/api/alerts" style="color:#c9a84c">Alertas</a> &nbsp;|&nbsp;
    <a href="/docs" style="color:#c9a84c">API Docs</a></p>
    </body></html>"""

@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    total  = db.query(Alert).count()
    wins   = db.query(Alert).filter(Alert.status == "win").count()
    losses = db.query(Alert).filter(Alert.status == "loss").count()
    closed = wins + losses
    return {
        "total": total, "wins": wins, "losses": losses,
        "open": db.query(Alert).filter(Alert.status == "open").count(),
        "win_rate": round(wins/closed*100,1) if closed > 0 else 0,
    }

@app.get("/api/alerts")
async def get_alerts(
    status: Optional[str] = Query(None),
    limit: int = Query(50),
    db: Session = Depends(get_db)
):
    q = db.query(Alert).order_by(Alert.created_at.desc())
    if status:
        q = q.filter(Alert.status == status)
    return [{"id":a.id,"ticker":a.ticker,"score":a.score_total,
             "entry":a.entry_price,"sl":a.stop_loss,"tp1":a.target1,"tp2":a.target2,
             "contract":a.contract,"signal":a.signal_summary,
             "status":a.status,"pnl":a.pnl_pct,
             "date":a.created_at.isoformat() if a.created_at else None}
            for a in q.limit(limit).all()]

@app.post("/api/alerts")
async def create_alert(
    ticker: str, score: int, entry: float,
    sl: float, tp1: float, tp2: float,
    contract: str = "", signal: str = "",
    db: Session = Depends(get_db)
):
    a = Alert(ticker=ticker.upper(), score_total=score,
              entry_price=entry, stop_loss=sl, target1=tp1, target2=tp2,
              contract=contract, signal_summary=signal)
    db.add(a); db.commit()
    return {"ok": True, "id": a.id}

@app.patch("/api/alerts/{alert_id}")
async def update_alert(
    alert_id: int,
    status: Optional[str] = None,
    pnl_pct: Optional[float] = None,
    db: Session = Depends(get_db)
):
    a = db.query(Alert).filter(Alert.id == alert_id).first()
    if not a: raise HTTPException(404, "Not found")
    if status: a.status = status
    if pnl_pct is not None: a.pnl_pct = pnl_pct
    db.commit()
    return {"ok": True}

@app.get("/api/watchlist")
async def get_watchlist(db: Session = Depends(get_db)):
    items = db.query(WatchlistItem).filter(WatchlistItem.active == True).all()
    return [{"id":i.id,"ticker":i.ticker,"notes":i.notes} for i in items]

@app.post("/api/watchlist")
async def add_watchlist(ticker: str, notes: str = "", db: Session = Depends(get_db)):
    i = WatchlistItem(ticker=ticker.upper(), notes=notes)
    db.add(i); db.commit()
    return {"ok": True, "id": i.id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
