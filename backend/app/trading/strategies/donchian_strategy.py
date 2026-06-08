"""Donchian breakout and pullback strategy."""

import pandas as pd

from app.models import BotConfig
from app.trading.indicators.donchian import donchian_channel
from app.trading.types import StrategyResult


def _pullback_score(
    *,
    close: float,
    open_: float,
    high: float,
    low: float,
    upper_prev: float,
    lower_prev: float,
    upper: float,
    lower: float,
    mid: float,
) -> tuple[float, str]:
    if close > upper_prev:
        return 1.0, "breakout_upper"
    if close < lower_prev:
        return -1.0, "breakout_lower"

    channel_width = upper - lower
    if channel_width <= 0:
        return 0.0, "flat_channel"

    touch_eps = channel_width * 0.05
    body = abs(close - open_)
    upper_wick = high - max(open_, close)
    lower_wick = min(open_, close) - low
    bearish = close < open_
    bullish = close > open_

    tested_upper_zone = high >= mid - touch_eps or high >= upper - touch_eps
    rejection_down = bearish or (
        upper_wick > body and upper_wick > lower_wick
    )
    if tested_upper_zone and rejection_down:
        return -1.0, "pullback_short"

    tested_lower_zone = low <= mid + touch_eps or low <= lower + touch_eps
    rejection_up = bullish or (
        lower_wick > body and lower_wick > upper_wick
    )
    if tested_lower_zone and rejection_up:
        return 1.0, "pullback_long"

    return 0.0, "neutral"


def evaluate(df: pd.DataFrame, config: BotConfig) -> StrategyResult:
    data = donchian_channel(df, config.donchian_period)
    if len(data) < config.donchian_period + 2:
        return StrategyResult("donchian", 0.0, {"reason": "insufficient_data"})

    row = data.iloc[-1]
    close = float(row["close"])
    open_ = float(row["open"])
    high = float(row["high"])
    low = float(row["low"])
    upper = float(row["dc_upper"])
    lower = float(row["dc_lower"])
    mid = float(row["dc_mid"])
    upper_prev = float(data["dc_upper"].iloc[-2])
    lower_prev = float(data["dc_lower"].iloc[-2])

    score, reason = _pullback_score(
        close=close,
        open_=open_,
        high=high,
        low=low,
        upper_prev=upper_prev,
        lower_prev=lower_prev,
        upper=upper,
        lower=lower,
        mid=mid,
    )

    return StrategyResult(
        "donchian",
        score,
        {
            "close": close,
            "upper": upper,
            "lower": lower,
            "mid": mid,
            "upper_prev": upper_prev,
            "lower_prev": lower_prev,
            "period": config.donchian_period,
            "reason": reason,
        },
    )
