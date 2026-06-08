"""Run all strategies and collect scores."""

import pandas as pd

from app.models import BotConfig
from app.trading.strategies import (
    donchian_strategy,
    ema_strategy,
    rsi_midline_strategy,
    supertrend_strategy,
)
from app.trading.types import StrategyResult


def compute_strategy_scores(df: pd.DataFrame, config: BotConfig) -> list[StrategyResult]:
    return [
        donchian_strategy.evaluate(df, config),
        supertrend_strategy.evaluate(df, config),
        rsi_midline_strategy.evaluate(df, config),
        ema_strategy.evaluate(df, config),
    ]
