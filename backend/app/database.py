"""SQLAlchemy engine, session factory, and database bootstrap."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


settings = get_settings()

_engine_kwargs: dict = {"echo": settings.debug}
if settings.database_url.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    _engine_kwargs["pool_pre_ping"] = True
    _engine_kwargs["pool_recycle"] = 3600

engine = create_engine(settings.database_url, **_engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yield a DB session and close it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_bot_config_columns() -> None:
    """Add new columns to existing bot_config / trade_positions (idempotent)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "bot_config" not in insp.get_table_names():
        return

    existing = {c["name"] for c in insp.get_columns("bot_config")}
    alters: list[str] = []
    if "symbol" not in existing:
        alters.append(
            "ALTER TABLE bot_config ADD COLUMN symbol VARCHAR(32) NOT NULL DEFAULT 'XAUUSD+'"
        )
    if "timeframe" not in existing:
        alters.append(
            "ALTER TABLE bot_config ADD COLUMN timeframe VARCHAR(8) NOT NULL DEFAULT 'M15'"
        )
    if "bars_lookback" not in existing:
        alters.append(
            "ALTER TABLE bot_config ADD COLUMN bars_lookback INT NOT NULL DEFAULT 500"
        )
    if "risk_per_trade_pct" not in existing:
        alters.append(
            "ALTER TABLE bot_config ADD COLUMN risk_per_trade_pct FLOAT NOT NULL DEFAULT 1.0"
        )
    if "max_open_positions" not in existing:
        alters.append(
            "ALTER TABLE bot_config ADD COLUMN max_open_positions INT NOT NULL DEFAULT 1"
        )
    if "magic_number" not in existing:
        alters.append(
            "ALTER TABLE bot_config ADD COLUMN magic_number INT NOT NULL DEFAULT 202501"
        )
    if "rsi_swing_lookback" not in existing:
        alters.append(
            "ALTER TABLE bot_config ADD COLUMN rsi_swing_lookback INT NOT NULL DEFAULT 5"
        )

    pos_existing: set[str] = set()
    if "trade_positions" in insp.get_table_names():
        pos_existing = {c["name"] for c in insp.get_columns("trade_positions")}
        if "highest_price" not in pos_existing:
            alters.append("ALTER TABLE trade_positions ADD COLUMN highest_price FLOAT NULL")
        if "lowest_price" not in pos_existing:
            alters.append("ALTER TABLE trade_positions ADD COLUMN lowest_price FLOAT NULL")

    if not alters:
        return
    with engine.begin() as conn:
        for stmt in alters:
            conn.execute(text(stmt))


def init_db() -> None:
    """Create tables if missing and seed default bot config when empty."""
    from app import models  # noqa: F401 — register models with Base.metadata
    from app.seed import seed_if_empty

    Base.metadata.create_all(bind=engine)
    _migrate_bot_config_columns()
    with SessionLocal() as db:
        if seed_if_empty(db):
            db.commit()
