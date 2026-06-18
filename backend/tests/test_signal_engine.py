"""Unit tests for multi-timeframe signal engine."""

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from app.models import BotConfig, BotStatus
from app.trading.signal_engine import (
    SCALP_ENTRY_THRESHOLD,
    MainTrend,
    _filter_entry_signal,
    check_trend_and_entry_signal,
)
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
    h1_net: int,
    entry_net: int,
    *,
    h1_score: float | None = None,
    entry_score: float | None = None,
) -> MagicMock:
    from app.trading.types import AggregatedSignal

    market = MagicMock()
    market.fetch_timeframe.return_value = _make_ohlcv()

    call_idx = {"n": 0}

    def patched(_df, _config, **kwargs):
        idx = call_idx["n"]
        call_idx["n"] += 1
        if idx == 0:
            net = h1_net
            score = h1_score if h1_score is not None else float(net)
        else:
            net = entry_net
            score = entry_score if entry_score is not None else float(net)
        return AggregatedSignal(
            strategy_results=[StrategyResult("mock", score, {})],
            weighted_score=score,
            net_signal=net,
        )

    monkeypatch.setattr("app.trading.signal_engine.aggregate_signal", patched)
    return market


def test_bearish_h1_blocks_reversal_long(
    bot_config: BotConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    market = _mock_market(
        monkeypatch,
        h1_net=int(NetSignal.SELL),
        entry_net=int(NetSignal.BUY),
        entry_score=0.9,
    )
    result = check_trend_and_entry_signal(bot_config, market)
    assert result.main_trend == MainTrend.BEARISH
    assert result.net_signal == int(NetSignal.HOLD)
    assert "BLOCKED LONG" in result.meta["filter_log"]


def test_bearish_h1_allows_short(
    bot_config: BotConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    market = _mock_market(
        monkeypatch,
        h1_net=int(NetSignal.SELL),
        entry_net=int(NetSignal.SELL),
        entry_score=-0.5,
    )
    result = check_trend_and_entry_signal(bot_config, market)
    assert result.net_signal == int(NetSignal.SELL)
    assert "Allowed SHORT" in result.meta["filter_log"]


def test_bullish_h1_allows_long_entry(
    bot_config: BotConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    market = _mock_market(
        monkeypatch,
        h1_net=int(NetSignal.BUY),
        entry_net=int(NetSignal.BUY),
        entry_score=0.7,
    )
    result = check_trend_and_entry_signal(bot_config, market)
    assert result.main_trend == MainTrend.BULLISH
    assert result.net_signal == int(NetSignal.BUY)
    assert result.is_scalp_mode is False
    assert "NORMAL - 100% Volume" in result.meta["filter_log"]


def test_bullish_h1_blocks_short(
    bot_config: BotConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    market = _mock_market(
        monkeypatch,
        h1_net=int(NetSignal.BUY),
        entry_net=int(NetSignal.SELL),
        entry_score=-0.9,
    )
    result = check_trend_and_entry_signal(bot_config, market)
    assert result.net_signal == int(NetSignal.HOLD)
    assert "BLOCKED SHORT" in result.meta["filter_log"]


def test_neutral_h1_blocks_moderate_score(
    bot_config: BotConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    market = _mock_market(
        monkeypatch,
        h1_net=int(NetSignal.HOLD),
        entry_net=int(NetSignal.BUY),
        entry_score=0.75,
    )
    result = check_trend_and_entry_signal(bot_config, market)
    assert result.main_trend == MainTrend.NEUTRAL
    assert result.net_signal == int(NetSignal.HOLD)


def test_neutral_h1_scalp_override_long(
    bot_config: BotConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    market = _mock_market(
        monkeypatch,
        h1_net=int(NetSignal.HOLD),
        entry_net=int(NetSignal.BUY),
        entry_score=0.85,
    )
    result = check_trend_and_entry_signal(bot_config, market)
    assert result.net_signal == int(NetSignal.BUY)
    assert result.is_scalp_mode is True
    assert "SCALP MODE" in result.meta["filter_log"]


def test_neutral_h1_scalp_override_short(
    bot_config: BotConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    market = _mock_market(
        monkeypatch,
        h1_net=int(NetSignal.HOLD),
        entry_net=int(NetSignal.SELL),
        entry_score=-0.85,
    )
    result = check_trend_and_entry_signal(bot_config, market)
    assert result.net_signal == int(NetSignal.SELL)
    assert result.is_scalp_mode is True


def test_bullish_h1_blocks_short_filter() -> None:
    net, scalp, log = _filter_entry_signal(
        int(NetSignal.SELL),
        -0.65,
        MainTrend.BULLISH,
        entry_threshold=0.65,
        scalp_threshold=SCALP_ENTRY_THRESHOLD,
        super_safe=False,
    )
    assert net == int(NetSignal.HOLD)
    assert scalp is False
    assert "BLOCKED SHORT" in log


def test_filter_entry_signal_neutral_threshold() -> None:
    net, scalp, log = _filter_entry_signal(
        int(NetSignal.BUY),
        SCALP_ENTRY_THRESHOLD - 0.01,
        MainTrend.NEUTRAL,
        entry_threshold=0.65,
        scalp_threshold=SCALP_ENTRY_THRESHOLD,
        super_safe=False,
    )
    assert net == int(NetSignal.HOLD)
    assert "BLOCKED" in log

    net, scalp, log = _filter_entry_signal(
        int(NetSignal.BUY),
        SCALP_ENTRY_THRESHOLD,
        MainTrend.NEUTRAL,
        entry_threshold=0.65,
        scalp_threshold=SCALP_ENTRY_THRESHOLD,
        super_safe=False,
    )
    assert net == int(NetSignal.BUY)
    assert scalp is True
