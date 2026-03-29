from sqlalchemy import create_engine, Column, Integer, Float, String, Boolean, DateTime, Text, JSON
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

# ─── ALERTS ──────────────────────────────────────────────
class Alert(Base):
    __tablename__ = "alerts"

    id              = Column(Integer, primary_key=True, index=True)
    ticker          = Column(String(10), nullable=False, index=True)
    asset_type      = Column(String(20))        # STOCK / OPTION / FUTURE
    mode            = Column(String(20))        # SWING / DAY_TRADE / PRIMA / LONG_TERM
    tier            = Column(Integer, default=1)

    # Score breakdown
    score_total     = Column(Integer)
    score_icc       = Column(Integer)
    score_darkpool  = Column(Integer)
    score_flow      = Column(Integer)
    score_regime    = Column(Integer)
    score_macro     = Column(Integer)

    # Price levels
    entry_price     = Column(Float)
    current_price   = Column(Float)
    stop_loss       = Column(Float)
    target1         = Column(Float)
    target2         = Column(Float)

    # Options specific
    contract        = Column(String(50))        # NVDA 850C 21-Apr
    strike          = Column(Float)
    expiration      = Column(String(20))
    delta           = Column(Float)
    iv_rank         = Column(Float)
    premium         = Column(Float)
    volume          = Column(Integer)
    open_interest   = Column(Integer)
    vol_oi_ratio    = Column(Float)

    # Dark Pool
    dp_print_price  = Column(Float)
    dp_print_size   = Column(Float)
    dp_above_vwap   = Column(Boolean)
    dp_cluster      = Column(Boolean)

    # ICC
    icc_phase       = Column(String(20))        # INDICATION / CORRECTION / CONTINUATION
    icc_timeframe   = Column(String(10))        # 1H / 4H
    icc_signal      = Column(String(100))

    # Context
    signal_summary  = Column(Text)
    news_catalyst   = Column(Text)
    regime          = Column(String(20))        # TRENDING / CHOP / REVERSAL
    market_session  = Column(String(20))        # PRE / REGULAR / POST

    # Result tracking
    status          = Column(String(20), default="pending")  # pending/open/win/loss
    pnl_pct         = Column(Float)
    pnl_dollar      = Column(Float)
    closed_at       = Column(DateTime)

    # Discord
    discord_msg_id  = Column(String(50))
    sent_to_tiers   = Column(JSON, default=list)

    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─── WATCHLIST ───────────────────────────────────────────
class WatchlistItem(Base):
    __tablename__ = "watchlist"

    id          = Column(Integer, primary_key=True)
    ticker      = Column(String(10), nullable=False)
    added_by    = Column(String(50), default="system")
    priority    = Column(Integer, default=1)
    notes       = Column(Text)
    active      = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


# ─── MARKET STATS ────────────────────────────────────────
class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id          = Column(Integer, primary_key=True)
    ticker      = Column(String(10), nullable=False)
    price       = Column(Float)
    volume      = Column(Integer)
    vwap        = Column(Float)
    adx         = Column(Float)
    rsi         = Column(Float)
    iv_rank     = Column(Float)
    gex         = Column(Float)
    regime      = Column(String(20))
    session     = Column(String(20))
    snapshot_at = Column(DateTime, default=datetime.utcnow)


# ─── SYSTEM LOG ──────────────────────────────────────────
class SystemLog(Base):
    __tablename__ = "system_logs"

    id          = Column(Integer, primary_key=True)
    level       = Column(String(10))    # INFO / WARNING / ERROR
    module      = Column(String(50))
    message     = Column(Text)
    data        = Column(JSON)
    created_at  = Column(DateTime, default=datetime.utcnow)


# ─── CREATE ALL TABLES ───────────────────────────────────
def init_db():
    Base.metadata.create_all(bind=engine)
    print("✓ Database tables created")


if __name__ == "__main__":
    init_db()
