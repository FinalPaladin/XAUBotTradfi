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


@dataclass
class OrderPlan:
    side: OrderSide
    volume: float
    entry_price: float
    sl_price: float
    tp_price: float
    symbol: str
    magic: int
    comment: str = "XAUBot"


@dataclass
class PositionDecision:
    action: PositionAction
    ticket_id: str | None = None
    new_sl: float | None = None
    close_reason: str | None = None


OHLCV = pd.DataFrame
