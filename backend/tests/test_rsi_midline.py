"""Unit tests for RSI midline entry scoring."""

import numpy as np
import pandas as pd
import pytest

from app.models import BotConfig, BotStatus
from app.trading.strategies.rsi_midline_strategy import evaluate


@pytest.fixture
def config() -> BotConfig:
    return BotConfig(
        id=1,
        name="t",
        status=BotStatus.STOPPED,
        rsi_period=14,
    )


def _flat_df(close: float, n: int = 30) -> pd.DataFrame:
    arr = np.full(n, close)
    return pd.DataFrame(
        {
            "open": arr,
            "high": arr + 1,
            "low": arr - 1,
            "close": arr,
        }
    )


def test_rsi_midline_bearish_strong(config: BotConfig) -> None:
    df = _flat_df(100.0)
    df.loc[df.index[-5:], "close"] = np.linspace(100, 70, 5)
    df.loc[df.index[-5:], "low"] = df.loc[df.index[-5:], "close"] - 1
    df.loc[df.index[-5:], "high"] = df.loc[df.index[-5:], "close"] + 1
    result = evaluate(df, config)
    assert result.score <= -0.5


def test_rsi_midline_bullish_strong(config: BotConfig) -> None:
    df = _flat_df(100.0)
    df.loc[df.index[-5:], "close"] = np.linspace(100, 130, 5)
    df.loc[df.index[-5:], "low"] = df.loc[df.index[-5:], "close"] - 1
    df.loc[df.index[-5:], "high"] = df.loc[df.index[-5:], "close"] + 1
    result = evaluate(df, config)
    assert result.score >= 0.5
