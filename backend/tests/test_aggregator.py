"""Unit tests for signal aggregation (no MT5 required)."""



import numpy as np

import pandas as pd

import pytest



from app.models import BotConfig, BotStatus

from app.trading.aggregator import aggregate_signal, normalize_score





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

        supertrend_weight=0.30,

        rsi_period=14,

        rsi_overbought=70.0,

        rsi_oversold=30.0,

        rsi_weight=0.20,

        ema_period=21,

        ema_weight=0.15,

        rsi_swing_lookback=5,

        signal_threshold=0.65,

    )





def test_aggregate_signal_net_in_range(bot_config: BotConfig) -> None:

    df = _make_ohlcv()

    result = aggregate_signal(df, bot_config)

    assert -1 <= result.net_signal <= 1

    assert len(result.strategy_results) == 4

    assert all(-1.0 <= r.score <= 1.0 for r in result.strategy_results)





def test_weights_sum_produces_bounded_score(bot_config: BotConfig) -> None:

    df = _make_ohlcv()

    result = aggregate_signal(df, bot_config)

    assert -1.0 <= result.weighted_score <= 1.0





def test_float_drift_at_threshold_triggers_buy(

    bot_config: BotConfig, monkeypatch: pytest.MonkeyPatch

) -> None:

    """0.30×1 + 0.20×1 + 0.15×1 = 0.65 nhưng float raw có thể lệch — phải làm tròn → BUY."""

    from app.trading.types import StrategyResult



    def mock_scores(_df, _config):

        return [

            StrategyResult("donchian", 0.0, {}),

            StrategyResult("supertrend", 1.0, {}),

            StrategyResult("rsi", 1.0, {}),

            StrategyResult("ema21", 1.0, {}),

        ]



    monkeypatch.setattr(

        "app.trading.aggregator.compute_strategy_scores", mock_scores

    )

    result = aggregate_signal(_make_ohlcv(), bot_config)

    assert result.weighted_score == 0.65

    assert result.net_signal == 1





def test_trend_only_renormalizes_weights(

    bot_config: BotConfig, monkeypatch: pytest.MonkeyPatch

) -> None:

    from app.trading.types import StrategyResult



    def mock_scores(_df, _config):

        return [

            StrategyResult("donchian", 0.0, {}),

            StrategyResult("supertrend", -1.0, {}),

            StrategyResult("rsi", 1.0, {}),

            StrategyResult("ema21", 1.0, {}),

        ]



    monkeypatch.setattr(

        "app.trading.aggregator.compute_strategy_scores", mock_scores

    )

    entry = aggregate_signal(_make_ohlcv(), bot_config, include_rsi=True)

    trend = aggregate_signal(_make_ohlcv(), bot_config, include_rsi=False)



    assert entry.weighted_score == 0.05

    assert entry.net_signal == 0

    assert trend.weighted_score == normalize_score(-0.30 / 0.65)

    assert trend.net_signal == -1

    assert len(trend.strategy_results) == 2





def test_atr_filter_halves_score(

    bot_config: BotConfig, monkeypatch: pytest.MonkeyPatch

) -> None:

    from app.trading.types import StrategyResult



    def mock_scores(_df, _config):

        return [

            StrategyResult("donchian", 1.0, {}),

            StrategyResult("supertrend", 1.0, {}),

            StrategyResult("rsi", 1.0, {}),

            StrategyResult("ema21", 1.0, {}),

        ]



    monkeypatch.setattr(

        "app.trading.aggregator.compute_strategy_scores", mock_scores

    )

    monkeypatch.setattr(

        "app.trading.aggregator.atr_volatility_factor",

        lambda _df: (0.5, {"dampened": True}),

    )



    result = aggregate_signal(_make_ohlcv(), bot_config, apply_atr_filter=True)

    assert result.weighted_score == 0.5

    assert result.net_signal == 1


