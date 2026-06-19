"""Tests for Telegram alert HTML templates."""

from app.services.telegram.templates import (
    BLOCK_DIVIDER,
    build_close_trade_message,
    build_open_trade_message,
    escape_html,
)
from app.services.telegram.types import (
    CloseTradeAlert,
    OpenTradeAlert,
    TradeDirection,
    TradeOutcome,
)


def test_build_open_trade_message_long() -> None:
    alert = OpenTradeAlert(
        symbol="XAUUSD",
        direction=TradeDirection.LONG,
        entry=2650.50,
        sl=2640.00,
        tp=2670.00,
        ticket_id="12345678",
        reason="Tín hiệu đồng thuận từ SuperTrend và RSI Divergence",
    )
    text = build_open_trade_message(alert)

    assert "🟢" in text
    assert "<b>LONG</b> XAUUSD" in text
    assert BLOCK_DIVIDER in text
    assert "$2,650.50" in text
    assert "12345678" in text
    assert "$2,670.00" in text
    assert "SL:" not in text
    assert "SuperTrend" in text


def test_build_open_trade_message_short() -> None:
    alert = OpenTradeAlert(
        symbol="XAUUSD",
        direction=TradeDirection.SHORT,
        entry=2650.0,
        sl=None,
        tp=None,
        ticket_id="87654321",
        reason="Donchian breakdown",
    )
    text = build_open_trade_message(alert)

    assert "🔴" in text
    assert "<b>SHORT</b>" in text
    assert "87654321" in text
    assert "SL:" not in text
    assert "TP: <b>—</b>" in text


def test_build_close_trade_message_win() -> None:
    alert = CloseTradeAlert(
        symbol="XAUUSD",
        direction=TradeDirection.LONG,
        outcome=TradeOutcome.WIN,
        pnl_amount=125.40,
        pnl_percent=2.35,
        entry=2650.0,
        close_price=2675.0,
        ticket_id="12345678",
        account_balance=5125.40,
        reason="Chạm TP1",
    )
    text = build_close_trade_message(alert)

    assert "🏆" in text
    assert "<b>CLOSE</b> XAUUSD - <b>LONG</b>" in text
    assert "+$125.40" in text
    assert "(+2.35%)" in text
    assert "12345678" in text
    assert "$5,125.40" in text
    assert "Chạm TP1" in text


def test_build_close_trade_message_loss() -> None:
    alert = CloseTradeAlert(
        symbol="XAUUSD",
        direction=TradeDirection.SHORT,
        outcome=TradeOutcome.LOSS,
        pnl_amount=-80.0,
        pnl_percent=-1.5,
        entry=2650.0,
        close_price=2662.0,
        ticket_id="87654321",
        account_balance=None,
        reason="Quét Trailing Stop",
    )
    text = build_close_trade_message(alert)

    assert "🩸" in text
    assert "-$80.00" in text
    assert "(-1.50%)" in text


def test_escape_html_special_chars() -> None:
    assert escape_html("a < b & c") == "a &lt; b &amp; c"
