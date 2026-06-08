"""Tests for worker tick log formatting."""

from app.worker.tick_log import format_tick_log


def test_format_tick_log_compact_summary() -> None:
    result = {
        "summary": {
            "bot_id": 2,
            "price": 4287.72,
            "open_count": 0,
            "balance": 200.0,
            "floating_pnl": "-12.50",
            "drawdown_pct": 6.25,
            "main_trend": "BEARISH",
            "trend_source": "H4",
            "allowed": "SHORT",
            "h4_score": -0.5,
            "h1_score": -0.5,
            "h4_net": "SELL",
            "h1_net": "SELL",
            "entry_tf": "M15",
            "entry_score": 0.05,
            "entry_threshold": 0.65,
            "entry_net_raw": "HOLD",
            "net_signal": "HOLD",
            "donchian": 0.0,
            "supertrend": -1.0,
            "rsi": 1.0,
            "ema21": 0.0,
            "formula": (
                "0.35*+0.00 [Donchian] + 0.30*-1.00 [SuperTrend] + "
                "0.20*+1.00 [RSI] + 0.15*+0.00 [EMA21] = +0.0500"
            ),
            "action": None,
        }
    }
    text = format_tick_log(result)
    assert "floating_pnl=-12.50 USD" in text
    assert "net_signal=HOLD" in text
    assert "Donchian=+0.00" in text
    assert "EMA21=+0.00" in text
    assert "formula:" in text
    assert "bot_id=2" in text
    assert "dynamic_notional" not in text


def test_format_tick_log_error() -> None:
    text = format_tick_log({"bot_id": 2, "error": "No tick for XAUUSD+"})
    assert "ERROR" in text
