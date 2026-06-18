"""Pydantic schemas for API request/response (placeholder shapes for UI integration)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import BotStatus, LogLevel, OrderSide, TradingMode


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BotConfigRead(ORMBase):
    id: int
    name: str
    status: BotStatus
    trading_mode: TradingMode
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
    ema_period: int
    ema_weight: float
    signal_threshold: float
    max_layers: int = 5
    isolated_leverage: int = 50
    base_equity_usd: float = 200.0
    first_layer_notional_usd: float = 6750.0
    dca_volume_multiplier: float = 1.35
    layer_spacing_min: float = 5.0
    layer_spacing_max: float = 7.0
    basket_tp_min_usd: float = 2.0
    basket_tp_max_usd: float = 5.0
    single_tp_min_usd: float = 1.0
    single_tp_max_usd: float = 2.0
    single_tp_distance: float = 1.2
    hard_stop_adverse_distance: float = 12.0
    max_basket_loss_usd: float = 10.0
    max_basket_loss_pct: float = 20.0
    counter_trend_max_layers: int = 5
    atr_stop_multiplier: float = 2.0
    basket_time_stop_minutes: int = 60
    created_at: datetime
    updated_at: datetime


class BotConfigUpdate(BaseModel):
    """Partial update payload from React UI."""

    id: int | None = None
    name: str | None = None
    status: BotStatus | None = None
    trading_mode: TradingMode | None = None
    symbol: str | None = None
    timeframe: str | None = None
    bars_lookback: int | None = Field(None, ge=50, le=5000)
    risk_per_trade_pct: float | None = Field(None, ge=0.1, le=10)
    max_open_positions: int | None = Field(None, ge=1, le=10)
    max_layers: int | None = Field(None, ge=1, le=10)
    isolated_leverage: int | None = Field(None, ge=1, le=200)
    base_equity_usd: float | None = Field(None, ge=10, le=100000)
    first_layer_notional_usd: float | None = Field(None, ge=100, le=500000)
    dca_volume_multiplier: float | None = Field(None, ge=1.0, le=3.0)
    layer_spacing_min: float | None = Field(None, ge=0.5, le=50)
    layer_spacing_max: float | None = Field(None, ge=0.5, le=50)
    basket_tp_min_usd: float | None = Field(None, ge=0.1, le=1000)
    basket_tp_max_usd: float | None = Field(None, ge=0.1, le=1000)
    single_tp_min_usd: float | None = Field(None, ge=0.1, le=1000)
    single_tp_max_usd: float | None = Field(None, ge=0.1, le=1000)
    single_tp_distance: float | None = Field(None, ge=0.1, le=20)
    hard_stop_adverse_distance: float | None = Field(None, ge=5, le=200)
    max_basket_loss_usd: float | None = Field(None, ge=1, le=10000)
    max_basket_loss_pct: float | None = Field(None, ge=0, le=100)
    counter_trend_max_layers: int | None = Field(None, ge=1, le=10)
    atr_stop_multiplier: float | None = Field(None, ge=0.5, le=10)
    basket_time_stop_minutes: int | None = Field(None, ge=5, le=1440)
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
    ema_period: int | None = Field(None, ge=1)
    ema_weight: float | None = Field(None, ge=0, le=1)
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
    basket_peak_pnl: float | None = None
    layer_index: int = 0
    basket_anchor_price: float | None = None
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


class TradeHistoryPageRead(BaseModel):
    """Paginated trade history for UI filters and search."""

    items: list[TradeHistoryRead]
    total: int
    page: int
    page_size: int
    total_pages: int
    total_pnl: float


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
