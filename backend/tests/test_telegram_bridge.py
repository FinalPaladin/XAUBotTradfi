"""Tests for Telegram ↔ trading bridge."""

from app.models import OrderSide, TradeHistory
from app.services.telegram.bridge import (
    history_to_close_alert,
    humanize_close_reason,
    order_side_to_direction,
)
from app.services.telegram.types import TradeDirection, TradeOutcome


def test_order_side_to_direction() -> None:
    assert order_side_to_direction(OrderSide.BUY) == TradeDirection.LONG
    assert order_side_to_direction(OrderSide.SELL) == TradeDirection.SHORT


def test_humanize_close_reason() -> None:
    assert humanize_close_reason("BASKET_TP") == "Chạm Basket TP"
    assert humanize_close_reason("custom") == "custom"


def test_history_to_close_alert_win() -> None:
    from datetime import datetime, timezone

    history = TradeHistory(
        bot_id=1,
        ticket_id="123",
        symbol="XAUUSD",
        side=OrderSide.BUY,
        volume=0.1,
        entry_price=2650.0,
        exit_price=2675.0,
        profit_loss=25.0,
        close_reason="BASKET_TP",
        opened_at=datetime.now(timezone.utc),
        closed_at=datetime.now(timezone.utc),
    )
    alert = history_to_close_alert(history)

    assert alert.outcome == TradeOutcome.WIN
    assert alert.pnl_amount == 25.0
    assert alert.pnl_percent > 0
    assert alert.ticket_id == "123"
    assert alert.reason == "Chạm Basket TP"
