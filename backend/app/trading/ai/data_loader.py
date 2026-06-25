"""Load OHLCV CSV cho Meta-Labeling training (không phụ thuộc optimizer_ga)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.config import BACKEND_ROOT

PROJECT_ROOT = BACKEND_ROOT.parent

DEFAULT_H1_CSV = "data/xauusd_h1.csv"
DEFAULT_M5_CSV = "data/xauusd_m5.csv"

MT5_COLUMN_ALIASES: dict[str, str] = {
    "date": "date_part",
    "datetime": "time",
    "timestamp": "time",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "tick_volume": "tick_volume",
    "tickvolume": "tick_volume",
    "tick_vol": "tick_volume",
    "volume": "tick_volume",
    "vol": "tick_volume",
    "spread": "spread",
    "real_volume": "real_volume",
    "realvolume": "real_volume",
}


def _resolve_data_path(relative: str) -> Path:
    rel = Path(relative)
    candidates = [
        rel,
        Path.cwd() / rel,
        BACKEND_ROOT / rel,
        BACKEND_ROOT / "data" / rel.name,
        PROJECT_ROOT / rel,
        PROJECT_ROOT / "data" / rel.name,
    ]
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError(f"Không tìm thấy {relative}")


def _normalize_column_name(name: str) -> str:
    key = str(name).strip().lower()
    key = key.replace("<", "").replace(">", "").replace(" ", "_")
    while "__" in key:
        key = key.replace("__", "_")
    return MT5_COLUMN_ALIASES.get(key, key)


def _normalize_csv_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [_normalize_column_name(c) for c in df.columns]

    if "date_part" in df.columns and "time" in df.columns:
        combined = (
            df["date_part"].astype(str).str.strip()
            + " "
            + df["time"].astype(str).str.strip()
        )
        df["time"] = pd.to_datetime(combined, utc=True, errors="coerce")
        df = df.drop(columns=["date_part"], errors="ignore")
    elif "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")

    if "tick_volume" in df.columns:
        df["tick_volume"] = pd.to_numeric(df["tick_volume"], errors="coerce").fillna(0)

    return df


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    raw_path = Path(path)
    file_path = raw_path if raw_path.is_file() else _resolve_data_path(str(path))

    df = pd.read_csv(file_path, sep=None, engine="python")
    df = _normalize_csv_columns(df)

    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV thiếu cột OHLC {missing}: {file_path}")

    if "time" not in df.columns:
        raise ValueError(f"CSV cần cột thời gian: {file_path}")

    if not pd.api.types.is_datetime64_any_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")

    df = df.dropna(subset=["time", "open", "high", "low", "close"])
    df = df.sort_values("time").reset_index(drop=True)

    for col in ("tick_volume", "spread", "real_volume"):
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df[["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]]


def trim_backtest_data(
    df_h1: pd.DataFrame,
    df_m5: pd.DataFrame,
    max_m5_bars: int | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if max_m5_bars is None or len(df_m5) <= max_m5_bars:
        return df_h1, df_m5

    df_m5 = df_m5.tail(max_m5_bars).reset_index(drop=True)
    m5_start = df_m5["time"].iloc[0]
    m5_end = df_m5["time"].iloc[-1]
    h1_start = m5_start - pd.Timedelta(hours=500)
    df_h1 = df_h1[(df_h1["time"] >= h1_start) & (df_h1["time"] <= m5_end)].reset_index(drop=True)
    return df_h1, df_m5


def load_backtest_environment(
    h1_path: str = DEFAULT_H1_CSV,
    m5_path: str = DEFAULT_M5_CSV,
    *,
    max_m5_bars: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    df_h1 = load_ohlcv_csv(h1_path)
    df_m5 = load_ohlcv_csv(m5_path)
    return trim_backtest_data(df_h1, df_m5, max_m5_bars)


def precompute_h1_end_indices(df_h1: pd.DataFrame, df_m5: pd.DataFrame) -> np.ndarray:
    h1_times = df_h1["time"].to_numpy()
    m5_times = df_m5["time"].to_numpy()
    return np.searchsorted(h1_times, m5_times, side="right") - 1


def slice_h1_by_index(df_h1: pd.DataFrame, end_idx: int, lookback: int) -> pd.DataFrame:
    if end_idx < 0:
        return df_h1.iloc[0:0]
    start_idx = max(0, end_idx - lookback + 1)
    return df_h1.iloc[start_idx : end_idx + 1].reset_index(drop=True)
