from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, date
from typing import Iterator

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from antigravity.config import get_settings

settings = get_settings()
database_url = settings.database_url

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

engine_kwargs = {"pool_pre_ping": True}
if database_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(database_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class RawUwEvent(Base):
    __tablename__ = "raw_uw_events"

    id = Column(Integer, primary_key=True)
    endpoint = Column(String(120), index=True, nullable=False)
    symbol = Column(String(20), index=True)
    event_type = Column(String(50), index=True)
    status_code = Column(Integer)
    payload = Column(JSON, nullable=False)
    response_headers = Column(JSON, default=dict)
    request_params = Column(JSON, default=dict)
    fetched_at = Column(DateTime, default=datetime.utcnow, index=True)


class OptionFlowSignal(Base):
    __tablename__ = "option_flow_signals"
    __table_args__ = (
        UniqueConstraint("source_event_id", "contract_symbol", "tape_time", name="uq_option_flow_source_contract_time"),
    )

    id = Column(Integer, primary_key=True)
    source_event_id = Column(Integer, index=True)
    uw_alert_id = Column(String(64), index=True)
    ticker = Column(String(20), index=True, nullable=False)
    contract_symbol = Column(String(80), index=True)
    contract_type = Column(String(10))
    strike = Column(Float)
    expiry = Column(Date)
    tape_time = Column(DateTime, index=True)
    side = Column(String(20), index=True)
    execution_type = Column(String(40))
    volume = Column(Integer, default=0)
    open_interest = Column(Integer, default=0)
    premium = Column(Float, default=0)
    underlying_price = Column(Float)
    ask_side_pct = Column(Float, default=0)
    volume_oi_ratio = Column(Float, default=0)
    oi_broken = Column(Boolean, default=False, index=True)
    is_single_leg = Column(Boolean, default=True)
    score = Column(Integer, default=0)
    status = Column(String(30), default="NEW", index=True)
    rejection_reason = Column(Text)
    accepted_reason = Column(Text)
    raw = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class MarketRegime(Base):
    __tablename__ = "market_regime"

    id = Column(Integer, primary_key=True)
    evaluation_time = Column(DateTime, default=datetime.utcnow, index=True)
    evaluation_date = Column(Date, default=date.today, index=True)
    dxy_trend = Column(String(20))
    vix_level = Column(Float)
    spy_price = Column(Float)
    spy_sma_50 = Column(Float)
    liquidity_index = Column(String(20))
    market_bias = Column(String(20), index=True)
    notes = Column(Text)
    raw = Column(JSON, default=dict)


class SectorRotation(Base):
    __tablename__ = "sector_rotation_unified"
    __table_args__ = (UniqueConstraint("check_date", "sector_ticker", name="uq_unified_sector_date"),)

    id = Column(Integer, primary_key=True)
    check_date = Column(Date, default=date.today, index=True)
    sector_ticker = Column(String(12), index=True, nullable=False)
    capital_flow_rank = Column(Integer)
    performance_20d = Column(Float)
    status = Column(String(30), index=True)
    raw = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MarketTide(Base):
    __tablename__ = "market_tide"

    id = Column(Integer, primary_key=True)
    observed_at = Column(DateTime, default=datetime.utcnow, index=True)
    net_call_premium = Column(Float)
    net_put_premium = Column(Float)
    net_delta = Column(Float)
    sentiment = Column(String(30), index=True)
    speed_index = Column(String(30))
    raw = Column(JSON, default=dict)


class GexLevel(Base):
    __tablename__ = "gex_levels"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), index=True, nullable=False)
    observed_at = Column(DateTime, default=datetime.utcnow, index=True)
    support_level = Column(Float)
    resistance_level = Column(Float)
    spot_price = Column(Float)
    raw = Column(JSON, default=dict)


class DarkPoolActivity(Base):
    __tablename__ = "dark_pool_activity"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), index=True, nullable=False)
    observed_at = Column(DateTime, default=datetime.utcnow, index=True)
    total_premium = Column(Float, default=0)
    largest_print = Column(Float, default=0)
    print_count = Column(Integer, default=0)
    accumulation = Column(Boolean, default=False, index=True)
    raw = Column(JSON, default=dict)


class TradeIdea(Base):
    __tablename__ = "trade_ideas"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), index=True, nullable=False)
    direction = Column(String(10), index=True)
    source_signal_id = Column(Integer, index=True)
    thesis = Column(Text)
    macro_bias = Column(String(20))
    sector_status = Column(String(30))
    tide_sentiment = Column(String(30))
    conviction_score = Column(Integer, default=0, index=True)
    status = Column(String(30), default="CANDIDATE", index=True)
    rejection_reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class TradePlan(Base):
    __tablename__ = "trade_plans_unified"

    id = Column(Integer, primary_key=True)
    idea_id = Column(Integer, index=True)
    ticker = Column(String(20), index=True, nullable=False)
    direction = Column(String(10), index=True)
    entry_zone = Column(String(160))
    stop_loss = Column(Float)
    target_zone = Column(String(160))
    invalidation = Column(Text)
    approval_reason = Column(Text)
    risk_notes = Column(Text)
    setup_grade = Column(String(20))
    execution_status = Column(String(30), default="PENDING", index=True)
    conviction_score = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ContractMonitor(Base):
    __tablename__ = "contract_monitors"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), index=True, nullable=False)
    contract_symbol = Column(String(80), index=True)
    contract_type = Column(String(10))
    strike = Column(Float)
    expiry = Column(Date)
    direction = Column(String(10), index=True)
    source_signal_id = Column(Integer, index=True)
    alert_tape_time = Column(DateTime, index=True)
    alert_underlying_price = Column(Float)
    alert_premium = Column(Float)
    status = Column(String(30), default="ACTIVE", index=True)
    watch_reason = Column(Text)
    last_seen_at = Column(DateTime)
    last_premium = Column(Float)
    last_volume = Column(Integer)
    last_note = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BacktestContract(Base):
    __tablename__ = "backtest_contracts"

    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), index=True, nullable=False)
    contract_symbol = Column(String(80), index=True)
    contract_type = Column(String(10))
    strike = Column(Float)
    expiry = Column(Date)
    direction = Column(String(10), index=True)
    source_signal_id = Column(Integer, index=True)
    alert_tape_time = Column(DateTime, index=True)
    alert_underlying_price = Column(Float)
    alert_premium = Column(Float)
    status = Column(String(30), default="QUEUED", index=True)
    result_summary = Column(Text)
    result_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True)
    agent_name = Column(String(80), index=True, nullable=False)
    status = Column(String(30), index=True, nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    finished_at = Column(DateTime)
    records_processed = Column(Integer, default=0)
    message = Column(Text)
    error = Column(Text)
    metadata_json = Column(JSON, default=dict)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_schema()


def _ensure_schema() -> None:
    """Lightweight additive migrations for local MVP iteration."""
    inspector = inspect(engine)
    option_flow_columns = {column["name"] for column in inspector.get_columns("option_flow_signals")} if inspector.has_table("option_flow_signals") else set()
    option_flow_missing = {
        "rejection_reason": "TEXT",
        "accepted_reason": "TEXT",
        "underlying_price": "FLOAT",
        "uw_alert_id": "VARCHAR(64)",
    }

    with engine.connect() as conn:
        for column, column_type in option_flow_missing.items():
            if column not in option_flow_columns:
                conn.execute(text(f"ALTER TABLE option_flow_signals ADD COLUMN {column} {column_type}"))

        if inspector.has_table("trade_plans_unified"):
            trade_plan_columns = {column["name"] for column in inspector.get_columns("trade_plans_unified")}
            trade_plan_missing = {
                "approval_reason": "TEXT",
                "risk_notes": "TEXT",
                "setup_grade": "VARCHAR(20)",
            }
            for column, column_type in trade_plan_missing.items():
                if column not in trade_plan_columns:
                    conn.execute(text(f"ALTER TABLE trade_plans_unified ADD COLUMN {column} {column_type}"))
        conn.commit()


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

