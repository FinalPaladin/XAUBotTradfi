"""Telegram notification services for trade alerts."""

from app.services.telegram.client import (
    DEFAULT_PARSE_MODE,
    NoOpTelegramNotifier,
    TelegramHttpClient,
    TelegramNotifier,
    TelegramSendResult,
)
from app.services.telegram.notifier import TradeAlertNotifier, get_trade_alert_notifier
from app.services.telegram.templates import (
    build_close_trade_message,
    build_open_trade_message,
)
from app.services.telegram.types import (
    CloseTradeAlert,
    OpenTradeAlert,
    TradeDirection,
    TradeOutcome,
)

__all__ = [
    "DEFAULT_PARSE_MODE",
    "CloseTradeAlert",
    "NoOpTelegramNotifier",
    "OpenTradeAlert",
    "TelegramHttpClient",
    "TelegramNotifier",
    "TelegramSendResult",
    "TradeAlertNotifier",
    "TradeDirection",
    "TradeOutcome",
    "build_close_trade_message",
    "build_open_trade_message",
    "get_trade_alert_notifier",
]
