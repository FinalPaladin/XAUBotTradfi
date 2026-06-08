"""Unit tests for multi-timeframe signal engine."""

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from app.models import BotConfig, BotStatus
from app.trading.signal_engine import MainTrend, check_trend_and_entry_signal
from app.trading.types import NetSignal, StrategyResult


def _make_ohlcv(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = 2400 + np.cumsum(rng.normal(0, 2, n))
    return pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=n, freq="15min"),
            "open": close,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "tick_volume": rng.integers(100, 500, n),
            "spread": np.zeros(n),
            "real_volume": np.zeros(n),
        }
    )


@pytest.fixture
def bot_config() -> BotConfig:
    return BotConfig(
        id=1,
        name="mtf-test",
        status=BotStatus.RUNNING,
        symbol="XAUUSD+",
        bars_lookback=200,
        signal_threshold=0.65,
        donchian_weight=0.35,
        supertrend_weight=0.30,
        rsi_weight=0.20,
        ema_period=21,
        ema_weight=0.15,
    )


def _mock_market(
    monkeypatch: pytest.MonkeyPatch,
    h4_net: int,
    h1_net: int,
    entry_net: int,
) -> MagicMock:
    from app.trading.types import AggregatedSignal

    market = MagicMock()
    market.fetch_timeframe.return_value = _make_ohlcv()

    call_order = iter([h4_net, h1_net, entry_net])

    def patched(_df, _config, **kwargs):
        net = next(call_order)
        return AggregatedSignal(
            strategy_results=[StrategyResult("mock", float(net), {})],
            weighted_score=float(net),
            net_signal=net,
        )

    monkeypatch.setattr("app.trading.signal_engine.aggregate_signal", patched)
    return market


def test_bearish_h4_h1_blocks_long_entry(
    bot_config: BotConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    market = _mock_market(
        monkeypatch,
        h4_net=int(NetSignal.SELL),
        h1_net=int(NetSignal.SELL),
        entry_net=int(NetSignal.BUY),
    )
    result = check_trend_and_entry_signal(bot_config, market)
    assert result.main_trend == MainTrend.BEARISH
    assert result.trend_source == "H4"
    assert result.entry_timeframe == "M15"
    assert result.net_signal == int(NetSignal.HOLD)


def test_sideway_allows_both_directions(
    bot_config: BotConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    market = _mock_market(
        monkeypatch,
        h4_net=int(NetSignal.BUY),
        h1_net=int(NetSignal.SELL),
        entry_net=int(NetSignal.SELL),
    )
    result = check_trend_and_entry_signal(bot_config, market)
    assert result.main_trend == MainTrend.SIDEWAY
    assert result.trend_source == "MIXED"
    assert result.entry_timeframe == "M5"
    assert result.net_signal == int(NetSignal.SELL)
