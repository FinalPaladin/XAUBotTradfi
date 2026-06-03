"""RSI and swing-based divergence detection."""

import pandas as pd


def rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def _swing_lows(series: pd.Series, window: int) -> list[tuple[int, float]]:
    swings: list[tuple[int, float]] = []
    half = window // 2
    for i in range(half, len(series) - half):
        segment = series.iloc[i - half : i + half + 1]
        if series.iloc[i] == segment.min():
            swings.append((i, float(series.iloc[i])))
    return swings


def _swing_highs(series: pd.Series, window: int) -> list[tuple[int, float]]:
    swings: list[tuple[int, float]] = []
    half = window // 2
    for i in range(half, len(series) - half):
        segment = series.iloc[i - half : i + half + 1]
        if series.iloc[i] == segment.max():
            swings.append((i, float(series.iloc[i])))
    return swings


def detect_divergence(
    df: pd.DataFrame,
    rsi_period: int,
    swing_lookback: int,
    overbought: float,
    oversold: float,
) -> dict:
    """
    Returns divergence type on the latest bar region:
    bullish | bearish | none
    """
    if len(df) < rsi_period + swing_lookback * 4:
        return {"type": "none", "rsi": None}

    close = df["close"]
    rsi_vals = rsi(close, rsi_period)
    last_rsi = float(rsi_vals.iloc[-1])

    price_lows = _swing_lows(close, swing_lookback)
    price_highs = _swing_highs(close, swing_lookback)
    rsi_lows = _swing_lows(rsi_vals.dropna(), swing_lookback)
    rsi_highs = _swing_highs(rsi_vals.dropna(), swing_lookback)

    div_type = "none"

    if len(price_lows) >= 2 and len(rsi_lows) >= 2:
        p1, p2 = price_lows[-2], price_lows[-1]
        r1, r2 = rsi_lows[-2], rsi_lows[-1]
        if p2[1] < p1[1] and r2[1] > r1[1] and last_rsi <= oversold + 10:
            div_type = "bullish"

    if len(price_highs) >= 2 and len(rsi_highs) >= 2:
        p1, p2 = price_highs[-2], price_highs[-1]
        r1, r2 = rsi_highs[-2], rsi_highs[-1]
        if p2[1] > p1[1] and r2[1] < r1[1] and last_rsi >= overbought - 10:
            div_type = "bearish"

    return {
        "type": div_type,
        "rsi": last_rsi,
        "overbought": overbought,
        "oversold": oversold,
    }
