from sqlalchemy import create_engine, Column, Integer, Float, String, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

DATABASE_URL = os.getenv("DATABASE_URL", "").replace("postgresql://", "postgresql+psycopg2://")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class Alert(Base):
    __tablename__ = "alerts"
    id              = Column(Integer, primary_key=True, index=True)
    ticker          = Column(String(10), nullable=False, index=True)
    asset_type      = Column(String(20))
    mode            = Column(String(20))
    tier            = Column(Integer, default=1)
    score_total     = Column(Integer)
    score_icc       = Column(Integer)
    score_darkpool  = Column(Integer)
    score_flow      = Column(Integer)
    score_regime    = Column(Integer)
    entry_price     = Column(Float)
    current_price   = Column(Float)
    stop_loss       = Column(Float)
    target1         = Column(Float)
    target2         = Column(Float)
    contract        = Column(String(100))
    strike          = Column(Float)
    expiration      = Column(String(20))
    delta           = Column(Float)
    iv_rank         = Column(Float)
    premium         = Column(Float)
    volume          = Column(Integer)
    open_interest   = Column(Integer)
    signal_summary  = Column(Text)
    icc_phase       = Column(String(20))
    icc_signal      = Column(String(100))
    regime          = Column(String(20))
    market_session  = Column(String(20))
    status          = Column(String(20), default="pending")
    pnl_pct         = Column(Float)
    pnl_dollar      = Column(Float)
    closed_at       = Column(DateTime)
    discord_msg_id  = Column(String(50))
    sent_to_tiers   = Column(Text, default="[]")
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class WatchlistItem(Base):
    __tablename__ = "watchlist"
    id          = Column(Integer, primary_key=True)
    ticker      = Column(String(10), nullable=False)
    added_by    = Column(String(50), default="system")
    priority    = Column(Integer, default=1)
    notes       = Column(Text)
    active      = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

class SystemLog(Base):
    __tablename__ = "system_logs"
    id          = Column(Integer, primary_key=True)
    level       = Column(String(10))
    module      = Column(String(50))
    message     = Column(Text)
    created_at  = Column(DateTime, default=datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)
    print("Database tables created")

if __name__ == "__main__":
    init_db()
