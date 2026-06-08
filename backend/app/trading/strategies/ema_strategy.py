"""EMA trend bias with sideways (chop) detection."""

import pandas as pd

from app.models import BotConfig
from app.trading.indicators.ema import ema
from app.trading.types import StrategyResult

SIDEWAY_LOOKBACK = 10
MAX_EMA_CROSSES = 2


def _count_ema_crosses(close: pd.Series, ema_line: pd.Series, lookback: int) -> int:
    above = close > ema_line
    recent = above.iloc[-lookback:]
    if len(recent) < 2:
        return 0
    return int((recent.astype(int).diff().abs() == 1).sum())


def evaluate(df: pd.DataFrame, config: BotConfig) -> StrategyResult:
    period = config.ema_period
    min_bars = period + SIDEWAY_LOOKBACK + 2
    if len(df) < min_bars:
        return StrategyResult("ema21", 0.0, {"reason": "insufficient_data"})

    ema_line = ema(df["close"], period)
    close = float(df["close"].iloc[-1])
    ema_val = float(ema_line.iloc[-1])
    if pd.isna(ema_val):
        return StrategyResult("ema21", 0.0, {"reason": "insufficient_data"})

    crosses = _count_ema_crosses(df["close"], ema_line, SIDEWAY_LOOKBACK)
    if crosses > MAX_EMA_CROSSES:
        score = 0.0
        mode = "sideway"
    elif close > ema_val:
        score = 1.0
        mode = "above"
    elif close < ema_val:
        score = -1.0
        mode = "below"
    else:
        score = 0.0
        mode = "on_ema"

    return StrategyResult(
        "ema21",
        score,
        {
            "close": close,
            "ema": ema_val,
            "period": period,
            "crosses": crosses,
            "mode": mode,
        },
    )
