"""High-level trade alert notifier (templates + transport)."""

from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.services.telegram.client import (
    DEFAULT_PARSE_MODE,
    NoOpTelegramNotifier,
    TelegramHttpClient,
    TelegramNotifier,
    TelegramSendResult,
)
from app.services.telegram.templates import (
    build_close_trade_message,
    build_open_trade_message,
)
from app.services.telegram.types import CloseTradeAlert, OpenTradeAlert


class TradeAlertNotifier:
    """Builds formatted alerts and dispatches them via a TelegramNotifier."""

    def __init__(self, client: TelegramNotifier) -> None:
        self._client = client

    def notify_open_trade(
        self,
        alert: OpenTradeAlert,
        *,
        chat_id: str | None = None,
    ) -> TelegramSendResult:
        text = build_open_trade_message(alert)
        return self._client.send_message(text, chat_id=chat_id, parse_mode=DEFAULT_PARSE_MODE)

    def notify_close_trade(
        self,
        alert: CloseTradeAlert,
        *,
        chat_id: str | None = None,
    ) -> TelegramSendResult:
        text = build_close_trade_message(alert)
        return self._client.send_message(text, chat_id=chat_id, parse_mode=DEFAULT_PARSE_MODE)

    def notify_open_trade_with_chart(
        self,
        alert: OpenTradeAlert,
        chart_image: bytes,
        *,
        chat_id: str | None = None,
    ) -> TelegramSendResult:
        """Send chart first, then the open-trade text (extensible alert flow)."""
        caption = build_open_trade_message(alert)
        return self._client.send_photo(
            chart_image,
            caption=caption,
            chat_id=chat_id,
            parse_mode=DEFAULT_PARSE_MODE,
        )


@lru_cache
def get_telegram_client() -> TelegramNotifier:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return NoOpTelegramNotifier()
    return TelegramHttpClient(
        bot_token=settings.telegram_bot_token,
        default_chat_id=settings.telegram_chat_id,
    )


def get_trade_alert_notifier() -> TradeAlertNotifier:
    return TradeAlertNotifier(get_telegram_client())
