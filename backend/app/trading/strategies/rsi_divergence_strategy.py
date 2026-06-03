"""RSI divergence reversal strategy."""

import pandas as pd

from app.models import BotConfig
from app.trading.indicators.rsi_divergence import detect_divergence
from app.trading.types import StrategyResult


def evaluate(df: pd.DataFrame, config: BotConfig) -> StrategyResult:
    swing = getattr(config, "rsi_swing_lookback", None) or 5
    div = detect_divergence(
        df,
        config.rsi_period,
        swing,
        config.rsi_overbought,
        config.rsi_oversold,
    )
    div_type = div["type"]
    if div_type == "bullish":
        score = 1.0
    elif div_type == "bearish":
        score = -1.0
    else:
        score = 0.0

    return StrategyResult("rsi_divergence", score, div)
