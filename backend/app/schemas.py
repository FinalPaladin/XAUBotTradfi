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

    name: str | None = None
    status: BotStatus | None = None
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
    opened_at: datetime


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
