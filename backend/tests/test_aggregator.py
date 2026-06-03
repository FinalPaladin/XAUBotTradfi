"""Unit tests for signal aggregation (no MT5 required)."""

import numpy as np
import pandas as pd
import pytest

from app.models import BotConfig, BotStatus
from app.trading.aggregator import aggregate_signal


def _make_ohlcv(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 2400 + np.cumsum(rng.normal(0, 2, n))
    high = close + rng.uniform(1, 5, n)
    low = close - rng.uniform(1, 5, n)
    open_ = close + rng.normal(0, 1, n)
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=n, freq="15min"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "tick_volume": rng.integers(100, 1000, n),
            "spread": np.zeros(n),
            "real_volume": np.zeros(n),
        }
    )


@pytest.fixture
def bot_config() -> BotConfig:
    return BotConfig(
        id=1,
        name="test",
        status=BotStatus.STOPPED,
        symbol="XAUUSD+",
        timeframe="M15",
        bars_lookback=500,
        donchian_period=20,
        donchian_weight=0.35,
        supertrend_period=10,
        supertrend_multiplier=3.0,
        supertrend_weight=0.35,
        rsi_period=14,
        rsi_overbought=70.0,
        rsi_oversold=30.0,
        rsi_weight=0.30,
        rsi_swing_lookback=5,
        signal_threshold=0.65,
    )


def test_aggregate_signal_net_in_range(bot_config: BotConfig) -> None:
    df = _make_ohlcv()
    result = aggregate_signal(df, bot_config)
    assert -1 <= result.net_signal <= 1
    assert len(result.strategy_results) == 3
    assert all(-1.0 <= r.score <= 1.0 for r in result.strategy_results)


def test_weights_sum_produces_bounded_score(bot_config: BotConfig) -> None:
    df = _make_ohlcv()
    result = aggregate_signal(df, bot_config)
    assert -1.0 <= result.weighted_score <= 1.0
