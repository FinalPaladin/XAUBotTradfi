"""SuperTrend trend-following strategy."""

import pandas as pd

from app.models import BotConfig
from app.trading.indicators.supertrend import supertrend
from app.trading.types import StrategyResult


def evaluate(df: pd.DataFrame, config: BotConfig) -> StrategyResult:
    data = supertrend(
        df,
        config.supertrend_period,
        config.supertrend_multiplier,
    )
    if data["st_direction"].isna().all():
        return StrategyResult("supertrend", 0.0, {"reason": "insufficient_data"})

    direction_raw = data["st_direction"].iloc[-1]
    st_raw = data["st_value"].iloc[-1]
    if pd.isna(direction_raw) or pd.isna(st_raw):
        return StrategyResult("supertrend", 0.0, {"reason": "insufficient_data"})

    direction = int(direction_raw)
    close = float(data["close"].iloc[-1])
    st_val = float(st_raw)

    score = 1.0 if direction == 1 else -1.0
    prev_dir = int(data["st_direction"].iloc[-2]) if len(data) > 1 else direction
    if direction != prev_dir:
        score = 0.5 * score

    return StrategyResult(
        "supertrend",
        score,
        {
            "direction": direction,
            "st_value": st_val,
            "close": close,
            "period": config.supertrend_period,
            "multiplier": config.supertrend_multiplier,
        },
    )
