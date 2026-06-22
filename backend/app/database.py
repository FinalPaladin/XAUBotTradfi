"""SQLAlchemy engine, session factory, and database bootstrap."""

from collections.abc import Generator

from datetime import datetime, timezone

from sqlalchemy import create_engine, event
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


@event.listens_for(engine, "connect")
def _set_mysql_utc_timezone(dbapi_connection, _connection_record) -> None:
    """MySQL NOW() / func.now() theo UTC — tránh lệch opened_at vs closed_at."""
    if engine.dialect.name != "mysql":
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("SET time_zone = '+00:00'")
    finally:
        cursor.close()


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

    dca_columns: list[tuple[str, str]] = [
        ("max_layers", "INT NOT NULL DEFAULT 5"),
        ("isolated_leverage", "INT NOT NULL DEFAULT 50"),
        ("base_equity_usd", "FLOAT NOT NULL DEFAULT 200.0"),
        ("first_layer_notional_usd", "FLOAT NOT NULL DEFAULT 6750.0"),
        ("dca_volume_multiplier", "FLOAT NOT NULL DEFAULT 1.35"),
        ("layer_spacing_min", "FLOAT NOT NULL DEFAULT 5.0"),
        ("layer_spacing_max", "FLOAT NOT NULL DEFAULT 7.0"),
        ("basket_tp_min_usd", "FLOAT NOT NULL DEFAULT 2.0"),
        ("basket_tp_max_usd", "FLOAT NOT NULL DEFAULT 5.0"),
        ("single_tp_min_usd", "FLOAT NOT NULL DEFAULT 1.0"),
        ("single_tp_max_usd", "FLOAT NOT NULL DEFAULT 2.0"),
        ("single_tp_distance", "FLOAT NOT NULL DEFAULT 1.2"),
        ("single_tp_min_usd", "FLOAT NOT NULL DEFAULT 1.0"),
        ("single_tp_max_usd", "FLOAT NOT NULL DEFAULT 2.0"),
        ("hard_stop_adverse_distance", "FLOAT NOT NULL DEFAULT 12.0"),
        ("max_basket_loss_usd", "FLOAT NOT NULL DEFAULT 10.0"),
        ("max_basket_loss_pct", "FLOAT NOT NULL DEFAULT 20.0"),
        ("counter_trend_max_layers", "INT NOT NULL DEFAULT 5"),
        ("atr_stop_multiplier", "FLOAT NOT NULL DEFAULT 2.0"),
        ("basket_time_stop_minutes", "INT NOT NULL DEFAULT 60"),
        ("ema_period", "INT NOT NULL DEFAULT 21"),
        ("ema_weight", "FLOAT NOT NULL DEFAULT 0.15"),
        ("ema_distance_threshold", "FLOAT NOT NULL DEFAULT 0.4"),
    ]
    for col, typedef in dca_columns:
        if col not in existing:
            alters.append(f"ALTER TABLE bot_config ADD COLUMN {col} {typedef}")

    pos_existing: set[str] = set()
    if "trade_positions" in insp.get_table_names():
        pos_existing = {c["name"] for c in insp.get_columns("trade_positions")}
        if "highest_price" not in pos_existing:
            alters.append("ALTER TABLE trade_positions ADD COLUMN highest_price FLOAT NULL")
        if "lowest_price" not in pos_existing:
            alters.append("ALTER TABLE trade_positions ADD COLUMN lowest_price FLOAT NULL")
        if "layer_index" not in pos_existing:
            alters.append(
                "ALTER TABLE trade_positions ADD COLUMN layer_index INT NOT NULL DEFAULT 0"
            )
        if "basket_anchor_price" not in pos_existing:
            alters.append(
                "ALTER TABLE trade_positions ADD COLUMN basket_anchor_price FLOAT NULL"
            )
        if "basket_peak_pnl" not in pos_existing:
            alters.append(
                "ALTER TABLE trade_positions ADD COLUMN basket_peak_pnl FLOAT NULL"
            )

    if not alters:
        return
    with engine.begin() as conn:
        for stmt in alters:
            conn.execute(text(stmt))


def _migrate_risk_tuning() -> None:
    """Apply tighter risk defaults to existing bot_config rows (idempotent)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "bot_config" not in insp.get_table_names():
        return

    existing = {c["name"] for c in insp.get_columns("bot_config")}
    with engine.begin() as conn:
        if "hard_stop_adverse_distance" in existing:
            conn.execute(
                text(
                    "UPDATE bot_config SET hard_stop_adverse_distance = 12.0 "
                    "WHERE hard_stop_adverse_distance >= 35.0"
                )
            )
        if "max_basket_loss_usd" in existing:
            conn.execute(
                text(
                    "UPDATE bot_config SET max_basket_loss_usd = 10.0 "
                    "WHERE max_basket_loss_usd IS NULL OR max_basket_loss_usd <= 0"
                )
            )
        if "counter_trend_max_layers" in existing:
            conn.execute(
                text(
                    "UPDATE bot_config SET counter_trend_max_layers = 1 "
                    "WHERE counter_trend_max_layers IS NULL OR counter_trend_max_layers >= 5"
                )
            )
        if "max_basket_loss_pct" in existing:
            conn.execute(
                text(
                    "UPDATE bot_config SET max_basket_loss_pct = 4.0 "
                    "WHERE max_basket_loss_pct IS NULL OR max_basket_loss_pct >= 20.0"
                )
            )
        if "max_layers" in existing:
            conn.execute(
                text(
                    "UPDATE bot_config SET max_layers = 2, max_open_positions = 2 "
                    "WHERE max_layers >= 5 OR max_open_positions >= 5"
                )
            )
        if "hard_stop_adverse_distance" in existing:
            conn.execute(
                text(
                    "UPDATE bot_config SET hard_stop_adverse_distance = 9.0 "
                    "WHERE hard_stop_adverse_distance IS NULL "
                    "OR hard_stop_adverse_distance >= 12.0"
                )
            )
        if "single_tp_min_usd" in existing:
            conn.execute(
                text(
                    "UPDATE bot_config SET single_tp_min_usd = 2.0, "
                    "single_tp_distance = 2.0 "
                    "WHERE single_tp_min_usd <= 1.0 OR single_tp_distance <= 1.2"
                )
            )
        if "basket_time_stop_minutes" in existing:
            conn.execute(
                text(
                    "UPDATE bot_config SET basket_time_stop_minutes = 60 "
                    "WHERE basket_time_stop_minutes IS NULL"
                )
            )


def _migrate_fix_atr_stop_multiplier() -> None:
    """Fix invalid atr_stop_multiplier values (e.g. 50 mistaken for leverage)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "bot_config" not in insp.get_table_names():
        return

    existing = {c["name"] for c in insp.get_columns("bot_config")}
    if "atr_stop_multiplier" not in existing:
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE bot_config SET atr_stop_multiplier = 2.0 "
                "WHERE atr_stop_multiplier > 10 OR atr_stop_multiplier < 0.5"
            )
        )


def _migrate_trading_mode_manual() -> None:
    """Allow user to stay on NORMAL after manual override."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "bot_config" not in insp.get_table_names():
        return

    existing = {c["name"] for c in insp.get_columns("bot_config")}
    if "trading_mode_manual" not in existing:
        with engine.begin() as conn:
            if engine.dialect.name == "mysql":
                conn.execute(
                    text(
                        "ALTER TABLE bot_config ADD COLUMN trading_mode_manual "
                        "BOOLEAN NOT NULL DEFAULT 0"
                    )
                )
            else:
                conn.execute(
                    text(
                        "ALTER TABLE bot_config ADD COLUMN trading_mode_manual "
                        "BOOLEAN NOT NULL DEFAULT 0"
                    )
                )


def _migrate_trading_mode_and_dca_v4() -> None:
    """Add trading_mode column + DCA-4 defaults."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "bot_config" not in insp.get_table_names():
        return

    existing = {c["name"] for c in insp.get_columns("bot_config")}
    alters: list[str] = []
    if "trading_mode" not in existing:
        alters.append(
            "ALTER TABLE bot_config ADD COLUMN trading_mode "
            "VARCHAR(16) NOT NULL DEFAULT 'NORMAL'"
        )

    with engine.begin() as conn:
        for stmt in alters:
            conn.execute(text(stmt))

        if engine.dialect.name == "mysql":
            conn.execute(
                text(
                    "UPDATE bot_config SET "
                    "max_layers = 4, "
                    "max_open_positions = GREATEST(max_open_positions, 4), "
                    "layer_spacing_min = 4.0, "
                    "layer_spacing_max = 4.0, "
                    "basket_tp_min_usd = 1.0, "
                    "single_tp_min_usd = 1.0, "
                    "max_basket_loss_pct = 40.0 "
                    "WHERE max_layers >= 5 OR layer_spacing_min >= 5.0 "
                    "OR basket_tp_min_usd >= 2.0"
                )
            )
        else:
            conn.execute(
                text(
                    "UPDATE bot_config SET "
                    "max_layers = 4, "
                    "max_open_positions = CASE WHEN max_open_positions < 4 "
                    "THEN 4 ELSE max_open_positions END, "
                    "layer_spacing_min = 4.0, "
                    "layer_spacing_max = 4.0, "
                    "basket_tp_min_usd = 1.0, "
                    "single_tp_min_usd = 1.0, "
                    "max_basket_loss_pct = 40.0 "
                    "WHERE max_layers >= 5 OR layer_spacing_min >= 5.0 "
                    "OR basket_tp_min_usd >= 2.0"
                )
            )


def _migrate_trade_history_dedupe() -> None:
    """Remove duplicate history rows and add unique (bot_id, ticket_id) index."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "trade_history" not in insp.get_table_names():
        return

    dialect = engine.dialect.name
    indexes = {idx["name"] for idx in insp.get_indexes("trade_history")}
    with engine.begin() as conn:
        if dialect == "mysql":
            conn.execute(
                text(
                    "DELETE t1 FROM trade_history t1 "
                    "INNER JOIN trade_history t2 "
                    "ON t1.bot_id = t2.bot_id AND t1.ticket_id = t2.ticket_id "
                    "AND t1.id > t2.id"
                )
            )
        elif dialect == "sqlite":
            conn.execute(
                text(
                    "DELETE FROM trade_history WHERE id NOT IN ("
                    "SELECT MIN(id) FROM trade_history "
                    "GROUP BY bot_id, ticket_id)"
                )
            )

        if "ix_trade_history_bot_ticket" not in indexes:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX ix_trade_history_bot_ticket "
                    "ON trade_history (bot_id, ticket_id)"
                )
            )


def _migrate_dca_strategy_v2() -> None:
    """Cập nhật config DCA: 5 giá spacing, tối đa 5 lớp, cắt lỗ 50 USD."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "bot_config" not in insp.get_table_names():
        return

    existing = {c["name"] for c in insp.get_columns("bot_config")}
    if "max_layers" not in existing:
        return

    with engine.begin() as conn:
        if engine.dialect.name == "mysql":
            conn.execute(
                text(
                    "UPDATE bot_config SET "
                    "max_layers = 5, "
                    "max_open_positions = GREATEST(max_open_positions, 5), "
                    "layer_spacing_min = 5.0, "
                    "max_basket_loss_usd = 50.0, "
                    "max_basket_loss_pct = 0, "
                    "counter_trend_max_layers = 5 "
                    "WHERE max_layers <= 2 "
                    "OR max_basket_loss_usd <= 10 "
                    "OR layer_spacing_min >= 6.0 "
                    "OR counter_trend_max_layers <= 1"
                )
            )
        else:
            conn.execute(
                text(
                    "UPDATE bot_config SET "
                    "max_layers = 5, "
                    "max_open_positions = CASE WHEN max_open_positions < 5 "
                    "THEN 5 ELSE max_open_positions END, "
                    "layer_spacing_min = 5.0, "
                    "max_basket_loss_usd = 50.0, "
                    "max_basket_loss_pct = 0, "
                    "counter_trend_max_layers = 5 "
                    "WHERE max_layers <= 2 "
                    "OR max_basket_loss_usd <= 10 "
                    "OR layer_spacing_min >= 6.0 "
                    "OR counter_trend_max_layers <= 1"
                )
            )


def _migrate_fix_history_opened_at_shift() -> None:
    """Sửa opened_at bị lệch -7h do coerce_utc cũ (coi naive = VN trên MySQL UTC)."""
    from datetime import timedelta

    from sqlalchemy import inspect

    from app.models import TradeHistory

    insp = inspect(engine)
    if "trade_history" not in insp.get_table_names():
        return

    with SessionLocal() as db:
        rows = db.query(TradeHistory).all()
        changed = 0
        for row in rows:
            if row.opened_at is None or row.closed_at is None:
                continue
            diff_h = (row.closed_at - row.opened_at).total_seconds() / 3600
            if 6.0 <= diff_h <= 9.0:
                row.opened_at = row.opened_at + timedelta(hours=7)
                changed += 1
        if changed:
            db.commit()


def init_db() -> None:
    """Create tables if missing and seed default bot config when empty."""
    from app import models  # noqa: F401 — register models with Base.metadata
    from app.seed import seed_if_empty

    Base.metadata.create_all(bind=engine)
    _migrate_bot_config_columns()
    _migrate_risk_tuning()
    _migrate_trade_history_dedupe()
    _migrate_dca_strategy_v2()
    _migrate_trading_mode_and_dca_v4()
    _migrate_fix_atr_stop_multiplier()
    _migrate_trading_mode_manual()
    _migrate_fix_history_opened_at_shift()
    with SessionLocal() as db:
        if seed_if_empty(db):
            db.commit()
