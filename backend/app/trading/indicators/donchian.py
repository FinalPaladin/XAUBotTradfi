"""Donchian Channel indicator."""

import pandas as pd


def donchian_channel(df: pd.DataFrame, period: int) -> pd.DataFrame:
    out = df.copy()
    out["dc_upper"] = out["high"].rolling(period).max()
    out["dc_lower"] = out["low"].rolling(period).min()
    out["dc_mid"] = (out["dc_upper"] + out["dc_lower"]) / 2
    return out
