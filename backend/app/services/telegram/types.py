"""Data types for Telegram trade alerts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TradeDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class TradeOutcome(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"


@dataclass(frozen=True, slots=True)
class OpenTradeAlert:
    symbol: str
    direction: TradeDirection
    entry: float
    sl: float | None
    tp: float | None
    ticket_id: str
    reason_lines: tuple[str, ...]
    win_probability: float | None = None


@dataclass(frozen=True, slots=True)
class CloseTradeAlert:
    symbol: str
    direction: TradeDirection
    outcome: TradeOutcome
    pnl_amount: float
    pnl_percent: float
    entry: float
    close_price: float
    ticket_id: str
    account_balance: float | None
    reason: str
