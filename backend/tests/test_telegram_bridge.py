"""Tests for Telegram ↔ trading bridge."""

from app.models import OrderSide, TradeHistory
from app.services.telegram.bridge import (
    build_entry_reason_lines,
    history_to_close_alert,
    humanize_close_reason,
    order_side_to_direction,
)
from app.services.telegram.types import TradeDirection, TradeOutcome
from app.trading.signal_engine import MainTrend, TrendEntrySignal
from app.trading.types import NetSignal, StrategyResult


def test_build_entry_reason_lines_splits_and_moves_win_prob() -> None:
    signal = TrendEntrySignal(
        strategy_results=[
            StrategyResult("donchian", -1.0),
            StrategyResult("supertrend", 1.0),
            StrategyResult("rsi", 1.0),
            StrategyResult("ema21", -1.0),
        ],
        weighted_score=-0.73,
        net_signal=int(NetSignal.SELL),
        main_trend=MainTrend.BEARISH,
        trend_source="H1",
        entry_timeframe="M5",
        is_scalp_mode=False,
        h1_score=-0.8,
        entry_score=-0.73,
        meta={
            "filter_log": (
                "H1 BEARISH | M5 Score: -0.73 -> Allowed SHORT "
                "(NORMAL, need <= -0.58) | [AI FILTER] Win probability 72.0%"
            ),
            "ai_win_probability": 72.0,
            "ai_filter_threshold": 55.0,
            "entry_scoring": {
                "m5_raw_rsi": 59.7,
                "rsi_score": -0.73,
                "rsi_score_static": 1.0,
                "ema_distance_percent": 0.011,
                "ema_distance_threshold": 0.4,
                "ema_distance_penalty": False,
            },
        },
    )

    lines, win_prob = build_entry_reason_lines(signal, extra="Lớp 1")

    assert win_prob == 72.0
    assert lines[0] == "H1 BEARISH"
    assert "Allowed SHORT" in lines[1]
    assert "[AI FILTER]" not in " ".join(lines)
    assert "72.0%" not in " ".join(lines)
    assert any("AI filter: PASS" in line for line in lines)
    assert any("M5 RSI=59.7" in line for line in lines)
    assert any(line.startswith("Donchian:") for line in lines)
    assert lines[-1] == "Lớp 1"


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
