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
            "trend_source": "H1",
            "allowed": "SHORT",
            "h1_score": -0.5,
            "h1_net": "SELL",
            "is_scalp_mode": False,
            "filter_log": "H1 BEARISH | M5 Score: +0.05 -> BLOCKED",
            "entry_tf": "M5",
            "entry_score": 0.05,
            "entry_threshold": 0.5,
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
    assert "H1 score=-0.50" in text
    assert "H4" not in text
    assert "filter: H1 BEARISH" in text
    assert "Donchian=+0.00" in text
    assert "EMA21=+0.00" in text
    assert "gate >=0.50" in text or "gate >= +0.50" in text
    assert "bot_id=2" in text
    assert "dynamic_notional" not in text


def test_format_tick_log_scalp_mode() -> None:
    result = {
        "summary": {
            "bot_id": 1,
            "price": 2400.0,
            "open_count": 0,
            "balance": 200.0,
            "floating_pnl": "0.00",
            "drawdown_pct": 0.0,
            "main_trend": "NEUTRAL",
            "trend_source": "NONE",
            "allowed": "—",
            "h1_score": 0.0,
            "h1_net": "HOLD",
            "is_scalp_mode": True,
            "filter_log": (
                "H1 NEUTRAL | M5 Score: +0.85 "
                "-> OVERRIDE: Allowed LONG (SCALP MODE - 50% Volume)"
            ),
            "entry_tf": "M5",
            "entry_score": 0.85,
            "entry_threshold": 0.5,
            "entry_net_raw": "BUY",
            "net_signal": "BUY",
            "donchian": 1.0,
            "supertrend": 1.0,
            "rsi": 0.5,
            "ema21": 0.5,
            "formula": "mock",
            "action": "MỞ LỚP 1 BUY vol=0.01 SCALP_MODE",
        }
    }
    text = format_tick_log(result)
    assert "mode: SCALP" in text
    assert "OVERRIDE: Allowed LONG" in text


def test_format_tick_log_error() -> None:
    text = format_tick_log({"bot_id": 2, "error": "No tick for XAUUSD+"})
    assert "ERROR" in text
