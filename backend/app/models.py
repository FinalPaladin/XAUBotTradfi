"""SQLAlchemy ORM models for bot configuration, positions, history, logs, and users."""

import enum
import json
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.permissions import ADMIN_ROLE, parse_permissions
from app.database import Base


class User(Base):
    """Application user accounts with role and fine-grained permissions."""

    __tablename__ = "users"
    __table_args__ = (Index("ix_users_username", "username", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default=ADMIN_ROLE, nullable=False)
    permissions_json: Mapped[str] = mapped_column(
        Text, default="[]", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @property
    def permissions_list(self) -> list[str]:
        return parse_permissions(self.permissions_json)

    def set_permissions(self, permissions: list[str]) -> None:
        self.permissions_json = json.dumps(parse_permissions(permissions))


class BotStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"


class TradingMode(str, enum.Enum):
    NORMAL = "NORMAL"
    SUPER_SAFE = "SUPER_SAFE"


class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class LogLevel(str, enum.Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class BotConfig(Base):
    """Per-bot trading configuration and strategy weights."""

    __tablename__ = "bot_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    status: Mapped[BotStatus] = mapped_column(
        Enum(BotStatus),
        default=BotStatus.STOPPED,
        nullable=False,
    )
    trading_mode: Mapped[TradingMode] = mapped_column(
        Enum(TradingMode),
        default=TradingMode.NORMAL,
        nullable=False,
    )
    # True when user explicitly chose NORMAL — profit lock vẫn ép SUPER_SAFE trong ngày.
    trading_mode_manual: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    symbol: Mapped[str] = mapped_column(String(32), default="XAUUSD+", nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), default="M5", nullable=False)
    bars_lookback: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    risk_per_trade_pct: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    max_open_positions: Mapped[int] = mapped_column(Integer, default=999, nullable=False)
    magic_number: Mapped[int] = mapped_column(Integer, default=202501, nullable=False)
    rsi_swing_lookback: Mapped[int] = mapped_column(Integer, default=5, nullable=False)

    take_profit_pct: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    stop_loss_pct: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    trailing_stop_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    trailing_stop_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Multi-layer DCA Scalping (Bybit Master Trader style)
    max_layers: Mapped[int] = mapped_column(Integer, default=999, nullable=False)
    isolated_leverage: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    base_equity_usd: Mapped[float] = mapped_column(Float, default=200.0, nullable=False)
    first_layer_notional_usd: Mapped[float] = mapped_column(
        Float, default=6750.0, nullable=False
    )
    dca_volume_multiplier: Mapped[float] = mapped_column(
        Float, default=1.35, nullable=False
    )
    layer_spacing_min: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    layer_spacing_max: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    basket_tp_min_usd: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)
    basket_tp_max_usd: Mapped[float] = mapped_column(Float, default=5.0, nullable=False)
    single_tp_min_usd: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    single_tp_max_usd: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)
    single_tp_distance: Mapped[float] = mapped_column(Float, default=1.2, nullable=False)
    hard_stop_adverse_distance: Mapped[float] = mapped_column(
        Float, default=12.0, nullable=False
    )
    max_basket_loss_usd: Mapped[float] = mapped_column(
        Float, default=50.0, nullable=False
    )
    max_basket_loss_pct: Mapped[float] = mapped_column(
        Float, default=40.0, nullable=False
    )
    counter_trend_max_layers: Mapped[int] = mapped_column(
        Integer, default=5, nullable=False
    )
    atr_stop_multiplier: Mapped[float] = mapped_column(
        Float, default=2.0, nullable=False
    )
    basket_time_stop_minutes: Mapped[int] = mapped_column(
        Integer, default=60, nullable=False
    )

    # Donchian channel strategy
    donchian_period: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    donchian_weight: Mapped[float] = mapped_column(Float, default=0.35, nullable=False)

    # SuperTrend strategy
    supertrend_period: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    supertrend_multiplier: Mapped[float] = mapped_column(
        Float, default=3.0, nullable=False
    )
    supertrend_weight: Mapped[float] = mapped_column(Float, default=0.30, nullable=False)

    # RSI strategy
    rsi_period: Mapped[int] = mapped_column(Integer, default=14, nullable=False)
    rsi_overbought: Mapped[float] = mapped_column(Float, default=80.0, nullable=False)
    rsi_oversold: Mapped[float] = mapped_column(Float, default=20.0, nullable=False)
    rsi_weight: Mapped[float] = mapped_column(Float, default=0.20, nullable=False)

    # EMA trend bias (entry M15)
    ema_period: Mapped[int] = mapped_column(Integer, default=21, nullable=False)
    ema_weight: Mapped[float] = mapped_column(Float, default=0.15, nullable=False)
    ema_distance_threshold: Mapped[float] = mapped_column(
        Float, default=0.4, nullable=False
    )

    # Combined signal gate
    signal_threshold: Mapped[float] = mapped_column(Float, default=0.65, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    positions: Mapped[list["TradePosition"]] = relationship(
        back_populates="bot",
        cascade="all, delete-orphan",
    )
    history: Mapped[list["TradeHistory"]] = relationship(
        back_populates="bot",
        cascade="all, delete-orphan",
    )
    logs: Mapped[list["SystemLog"]] = relationship(back_populates="bot")


class TradePosition(Base):
    """Open positions synced from MT5 / Bybit TradFi."""

    __tablename__ = "trade_positions"
    __table_args__ = (Index("ix_trade_positions_ticket", "ticket_id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bot_config.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticket_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), default="XAUUSD+", nullable=False)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide), nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    current_tp: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_sl: Mapped[float | None] = mapped_column(Float, nullable=True)
    highest_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    lowest_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    basket_peak_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    layer_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    basket_anchor_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    bot: Mapped["BotConfig"] = relationship(back_populates="positions")


class TradeHistory(Base):
    """Closed trades for reporting and UI charts."""

    __tablename__ = "trade_history"
    __table_args__ = (
        Index("ix_trade_history_closed_at", "closed_at"),
        Index("ix_trade_history_bot_ticket", "bot_id", "ticket_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int] = mapped_column(
        ForeignKey("bot_config.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticket_id: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), default="XAUUSD+", nullable=False)
    side: Mapped[OrderSide] = mapped_column(Enum(OrderSide), nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float] = mapped_column(Float, nullable=False)
    profit_loss: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    close_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    bot: Mapped["BotConfig"] = relationship(back_populates="history")


class SystemLog(Base):
    """Bot activity logs and API / MT5 errors."""

    __tablename__ = "system_logs"
    __table_args__ = (Index("ix_system_logs_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bot_id: Mapped[int | None] = mapped_column(
        ForeignKey("bot_config.id", ondelete="SET NULL"),
        nullable=True,
    )
    level: Mapped[LogLevel] = mapped_column(
        Enum(LogLevel),
        default=LogLevel.INFO,
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(64), default="bot", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    bot: Mapped["BotConfig | None"] = relationship(back_populates="logs")
