"""RSI midline (50) trend bias for entry scoring."""

import pandas as pd

from app.models import BotConfig
from app.trading.indicators.rsi_divergence import rsi
from app.trading.types import StrategyResult


def _rsi_midline_score(rsi_val: float) -> float:
    if rsi_val < 45.0:
        return -1.0
    if rsi_val < 50.0:
        return -0.5 + (-0.5) * (50.0 - rsi_val) / 5.0
    if rsi_val > 55.0:
        return 1.0
    if rsi_val > 50.0:
        return 0.5 + 0.5 * (rsi_val - 50.0) / 5.0
    return 0.0


def evaluate(df: pd.DataFrame, config: BotConfig) -> StrategyResult:
    if len(df) < config.rsi_period + 2:
        return StrategyResult("rsi", 0.0, {"reason": "insufficient_data"})

    rsi_vals = rsi(df["close"], config.rsi_period)
    last_rsi = float(rsi_vals.iloc[-1])
    if pd.isna(last_rsi):
        return StrategyResult("rsi", 0.0, {"reason": "insufficient_data"})

    score = _rsi_midline_score(last_rsi)
    return StrategyResult(
        "rsi",
        score,
        {"rsi": last_rsi, "period": config.rsi_period, "mode": "midline"},
    )
