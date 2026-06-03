"""Pydantic schemas for API request/response (placeholder shapes for UI integration)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import BotStatus, LogLevel, OrderSide


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BotConfigRead(ORMBase):
    id: int
    name: str
    status: BotStatus
    symbol: str
    timeframe: str
    bars_lookback: int
    risk_per_trade_pct: float
    max_open_positions: int
    magic_number: int
    rsi_swing_lookback: int
    take_profit_pct: float
    stop_loss_pct: float
    trailing_stop_enabled: bool
    trailing_stop_pct: float | None
    donchian_period: int
    donchian_weight: float
    supertrend_period: int
    supertrend_multiplier: float
    supertrend_weight: float
    rsi_period: int
    rsi_overbought: float
    rsi_oversold: float
    rsi_weight: float
    signal_threshold: float
    created_at: datetime
    updated_at: datetime


class BotConfigUpdate(BaseModel):
    """Partial update payload from React UI."""

    id: int | None = None
    name: str | None = None
    status: BotStatus | None = None
    symbol: str | None = None
    timeframe: str | None = None
    bars_lookback: int | None = Field(None, ge=50, le=5000)
    risk_per_trade_pct: float | None = Field(None, ge=0.1, le=10)
    max_open_positions: int | None = Field(None, ge=1, le=10)
    magic_number: int | None = None
    rsi_swing_lookback: int | None = Field(None, ge=2, le=20)
    take_profit_pct: float | None = Field(None, ge=0)
    stop_loss_pct: float | None = Field(None, ge=0)
    trailing_stop_enabled: bool | None = None
    trailing_stop_pct: float | None = Field(None, ge=0)
    donchian_period: int | None = Field(None, ge=1)
    donchian_weight: float | None = Field(None, ge=0, le=1)
    supertrend_period: int | None = Field(None, ge=1)
    supertrend_multiplier: float | None = Field(None, gt=0)
    supertrend_weight: float | None = Field(None, ge=0, le=1)
    rsi_period: int | None = Field(None, ge=1)
    rsi_overbought: float | None = None
    rsi_oversold: float | None = None
    rsi_weight: float | None = Field(None, ge=0, le=1)
    signal_threshold: float | None = Field(None, ge=0, le=1)


class TradePositionRead(ORMBase):
    id: int
    bot_id: int
    ticket_id: str
    symbol: str
    side: OrderSide
    volume: float
    entry_price: float
    current_tp: float | None
    current_sl: float | None
    highest_price: float | None
    lowest_price: float | None
    opened_at: datetime


class StrategyResultRead(BaseModel):
    name: str
    score: float
    raw: dict[str, object] = Field(default_factory=dict)


class AggregatedSignalRead(BaseModel):
    strategy_results: list[StrategyResultRead]
    weighted_score: float
    net_signal: int


class TradeHistoryRead(ORMBase):
    id: int
    bot_id: int
    ticket_id: str
    symbol: str
    side: OrderSide
    volume: float
    entry_price: float
    exit_price: float
    profit_loss: float
    close_reason: str | None
    opened_at: datetime
    closed_at: datetime


class BotStatusResponse(BaseModel):
    """Aggregated status for dashboard."""

    bots: list[BotConfigRead] = []
    open_positions: list[TradePositionRead] = []
    recent_history: list[TradeHistoryRead] = []
    meta: dict[str, Any] = Field(default_factory=dict)


class MessageResponse(BaseModel):
    message: str
    detail: dict[str, Any] | None = None


class SystemLogRead(ORMBase):
    id: int
    bot_id: int | None
    level: LogLevel
    source: str
    message: str
    created_at: datetime


class ExchangeConfigRead(BaseModel):
    """Exchange / broker connection info (from env, read-only for UI)."""

    id: str
    name: str
    platform: str
    server: str | None = None
    login: str | None = None
    connected: bool = False
    error: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
