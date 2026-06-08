"""SuperTrend indicator (ATR-based)."""

import numpy as np
import pandas as pd


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def supertrend(
    df: pd.DataFrame, period: int, multiplier: float
) -> pd.DataFrame:
    out = df.copy()
    atr = _atr(out, period)
    hl2 = (out["high"] + out["low"]) / 2
    basic_ub = hl2 + multiplier * atr
    basic_lb = hl2 - multiplier * atr

    final_ub = basic_ub.copy()
    final_lb = basic_lb.copy()
    st = pd.Series(np.nan, index=out.index)
    direction = pd.Series(np.nan, index=out.index)

    for i in range(1, len(out)):
        prev_ub = final_ub.iloc[i - 1]
        prev_lb = final_lb.iloc[i - 1]

        if (
            pd.isna(prev_ub)
            or basic_ub.iloc[i] < prev_ub
            or out["close"].iloc[i - 1] > prev_ub
        ):
            final_ub.iloc[i] = basic_ub.iloc[i]
        else:
            final_ub.iloc[i] = prev_ub

        if (
            pd.isna(prev_lb)
            or basic_lb.iloc[i] > prev_lb
            or out["close"].iloc[i - 1] < prev_lb
        ):
            final_lb.iloc[i] = basic_lb.iloc[i]
        else:
            final_lb.iloc[i] = prev_lb

        prev_dir = direction.iloc[i - 1]
        if pd.isna(prev_dir):
            direction.iloc[i] = 1 if out["close"].iloc[i] >= final_lb.iloc[i] else -1
        elif prev_dir == 1:
            if out["close"].iloc[i] < final_lb.iloc[i]:
                direction.iloc[i] = -1
            else:
                direction.iloc[i] = 1
        else:
            if out["close"].iloc[i] > final_ub.iloc[i]:
                direction.iloc[i] = 1
            else:
                direction.iloc[i] = -1

        st.iloc[i] = (
            final_lb.iloc[i] if direction.iloc[i] == 1 else final_ub.iloc[i]
        )

    out["st_value"] = st
    out["st_direction"] = direction
    return out
