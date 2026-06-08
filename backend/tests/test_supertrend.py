"""SuperTrend indicator tests."""

import numpy as np
import pandas as pd

from app.trading.indicators.supertrend import supertrend


def _downtrend_df(n: int = 80) -> pd.DataFrame:
    close = 4500 - np.arange(n, dtype=float) * 3
    return pd.DataFrame(
        {
            "open": close + 1,
            "high": close + 5,
            "low": close - 5,
            "close": close,
        }
    )


def test_supertrend_produces_values_not_all_nan() -> None:
    data = supertrend(_downtrend_df(), period=10, multiplier=3.0)
    assert data["st_value"].iloc[-1] == data["st_value"].iloc[-1]  # not NaN
    assert not pd.isna(data["st_value"].iloc[-1])


def test_supertrend_flags_downtrend_on_sustained_drop() -> None:
    data = supertrend(_downtrend_df(), period=10, multiplier=3.0)
    assert int(data["st_direction"].iloc[-1]) == -1
