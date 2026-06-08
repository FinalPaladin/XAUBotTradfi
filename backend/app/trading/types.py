"""Shared types for the trading pipeline."""

from dataclasses import dataclass, field
from enum import Enum, IntEnum

import pandas as pd

from app.models import OrderSide


class NetSignal(IntEnum):
    SELL = -1
    HOLD = 0
    BUY = 1


class PositionAction(str, Enum):
    HOLD = "HOLD"
    MODIFY_TRAIL = "MODIFY_TRAIL"
    CLOSE_SL = "CLOSE_SL"
    CLOSE_TP = "CLOSE_TP"
    CLOSE_TRAIL = "CLOSE_TRAIL"
    CLOSE_SIGNAL = "CLOSE_SIGNAL"
    CLOSE_STOP_ALL = "CLOSE_STOP_ALL"
    CLOSE_BASKET_TP = "CLOSE_BASKET_TP"
    CLOSE_SINGLE_SCALP = "CLOSE_SINGLE_SCALP"
    CLOSE_HARD_STOP = "CLOSE_HARD_STOP"


class BasketAction(str, Enum):
    """Hành động cấp basket (multi-layer DCA)."""

    HOLD = "HOLD"
    CLOSE_BASKET_TP = "CLOSE_BASKET_TP"
    CLOSE_SINGLE_SCALP = "CLOSE_SINGLE_SCALP"
    CLOSE_HARD_STOP = "CLOSE_HARD_STOP"
    ADD_LAYER = "ADD_LAYER"


@dataclass
class StrategyResult:
    name: str
    score: float
    raw: dict = field(default_factory=dict)


@dataclass
class AggregatedSignal:
    strategy_results: list[StrategyResult]
    weighted_score: float
    net_signal: int
    is_scalp_mode: bool = False


@dataclass
class OrderPlan:
    side: OrderSide
    volume: float
    entry_price: float
    symbol: str
    magic: int
    sl_price: float | None = None
    tp_price: float | None = None
    comment: str = "XAUBot"
    layer_index: int = 0
    basket_anchor_price: float | None = None
    use_broker_sl_tp: bool = True


@dataclass
class PositionDecision:
    action: PositionAction
    ticket_id: str | None = None
    new_sl: float | None = None
    close_reason: str | None = None


@dataclass
class BasketDecision:
    action: BasketAction
    close_reason: str | None = None
    meta: dict = field(default_factory=dict)


OHLCV = pd.DataFrame
