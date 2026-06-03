"""Donchian breakout strategy."""

import pandas as pd

from app.models import BotConfig
from app.trading.indicators.donchian import donchian_channel
from app.trading.types import StrategyResult


def evaluate(df: pd.DataFrame, config: BotConfig) -> StrategyResult:
    data = donchian_channel(df, config.donchian_period)
    if len(data) < config.donchian_period + 2:
        return StrategyResult("donchian", 0.0, {"reason": "insufficient_data"})

    close = float(data["close"].iloc[-1])
    upper_prev = float(data["dc_upper"].iloc[-2])
    lower_prev = float(data["dc_lower"].iloc[-2])

    if close > upper_prev:
        score = 1.0
    elif close < lower_prev:
        score = -1.0
    else:
        score = 0.0

    return StrategyResult(
        "donchian",
        score,
        {
            "close": close,
            "upper_prev": upper_prev,
            "lower_prev": lower_prev,
            "period": config.donchian_period,
        },
    )
