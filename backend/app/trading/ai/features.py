"""
Feature engineering cho Meta-Labeling (training + live inference).

Vector đặc trưng cố định thứ tự — lưu kèm model để inference khớp 100%.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from app.trading.aggregator import atr_volatility_factor, compute_m5_entry_score
from app.trading.indicators.atr import average_true_range
from app.trading.scoring import compute_strategy_scores
from app.trading.signal_engine import MainTrend, _resolve_main_trend
from app.trading.types import NetSignal

if TYPE_CHECKING:
    from app.models import BotConfig
    from app.trading.ai.precompute import PrecomputedTrainingData

ATR_PERIOD = 14
ATR_AVG_LOOKBACK = 20

FEATURE_NAMES: list[str] = [
    "atr_current",
    "atr_ratio",
    "atr_factor",
    "ema_distance_pct",
    "rsi",
    "entry_score",
    "h1_score",
    "donchian_score",
    "supertrend_score",
    "rsi_strategy_score",
    "ema_strategy_score",
    "h1_trend_code",
    "hour_norm",
    "day_of_week_norm",
    "session_asia",
    "session_london",
    "session_new_york",
    "is_scalp_mode",
    "direction",
    "spread",
]

H1_TREND_CODES = {
    MainTrend.BULLISH.value: 1.0,
    MainTrend.BEARISH.value: -1.0,
    MainTrend.NEUTRAL.value: 0.0,
}


def _session_flags(ts: datetime) -> tuple[float, float, float]:
    """Phiên giao dịch theo giờ UTC (XAUUSD)."""
    hour = ts.hour
    asia = 1.0 if 0 <= hour < 8 else 0.0
    london = 1.0 if 8 <= hour < 16 else 0.0
    new_york = 1.0 if 13 <= hour < 22 else 0.0
    return asia, london, new_york


def _atr_ratio(df: pd.DataFrame) -> tuple[float, float]:
    min_bars = ATR_PERIOD + ATR_AVG_LOOKBACK + 1
    if len(df) < min_bars:
        return 1.0, 0.0

    atr_series = average_true_range(df, ATR_PERIOD)
    current = float(atr_series.iloc[-1])
    avg = float(atr_series.iloc[-(ATR_AVG_LOOKBACK + 1) : -1].mean())
    if pd.isna(current) or pd.isna(avg) or avg <= 0:
        return 1.0, 0.0
    return current / avg, current


def build_entry_features(
    *,
    df_m5: pd.DataFrame,
    df_h1: pd.DataFrame,
    config: BotConfig,
    main_trend: MainTrend,
    entry_score: float,
    h1_score: float,
    entry_net: int,
    is_scalp_mode: bool,
    bar_time: datetime | pd.Timestamp | None = None,
) -> dict[str, float]:
    """
    Trích xuất vector đặc trưng tại thời điểm có tín hiệu entry M5.

    Dùng chung cho training offline và inference live.
    """
    results = compute_strategy_scores(df_m5, config)
    _, entry_meta = compute_m5_entry_score(
        config, results, h1_trend=main_trend.value
    )
    atr_factor, _ = atr_volatility_factor(df_m5)
    atr_ratio, atr_current = _atr_ratio(df_m5)

    rsi_raw = results[2].raw.get("rsi")
    ema_val = results[3].raw.get("ema")
    close = results[3].raw.get("close")
    ema_distance_pct = 0.0
    if close is not None and ema_val is not None and ema_val > 0:
        ema_distance_pct = abs(close - ema_val) / ema_val * 100.0

    ts = bar_time if bar_time is not None else df_m5["time"].iloc[-1]
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    hour_norm = ts.hour / 23.0
    dow_norm = ts.weekday() / 6.0
    session_asia, session_london, session_ny = _session_flags(ts)

    direction = 0.0
    if entry_net == int(NetSignal.BUY):
        direction = 1.0
    elif entry_net == int(NetSignal.SELL):
        direction = -1.0

    spread = 0.0
    if "spread" in df_m5.columns:
        spread = float(df_m5["spread"].iloc[-1])

    return {
        "atr_current": float(atr_current),
        "atr_ratio": float(atr_ratio),
        "atr_factor": float(atr_factor),
        "ema_distance_pct": float(ema_distance_pct),
        "rsi": float(rsi_raw) if rsi_raw is not None else 50.0,
        "entry_score": float(entry_score),
        "h1_score": float(h1_score),
        "donchian_score": float(results[0].score),
        "supertrend_score": float(results[1].score),
        "rsi_strategy_score": float(entry_meta.get("rsi_score", results[2].score)),
        "ema_strategy_score": float(results[3].score),
        "h1_trend_code": H1_TREND_CODES.get(main_trend.value, 0.0),
        "hour_norm": float(hour_norm),
        "day_of_week_norm": float(dow_norm),
        "session_asia": session_asia,
        "session_london": session_london,
        "session_new_york": session_ny,
        "is_scalp_mode": 1.0 if is_scalp_mode else 0.0,
        "direction": direction,
        "spread": spread,
    }


def features_to_vector(features: dict[str, float]) -> list[float]:
    """Chuyển dict → list theo thứ tự FEATURE_NAMES (cho XGBoost DMatrix)."""
    return [float(features[name]) for name in FEATURE_NAMES]


def build_features_from_precomputed(
    *,
    pc: PrecomputedTrainingData,
    bar_index: int,
    df_m5: pd.DataFrame,
    main_trend: MainTrend,
    entry_score: float,
    h1_score: float,
    entry_net: int,
    is_scalp_mode: bool,
) -> dict[str, float]:
    """Features nhanh từ mảng precompute (training)."""
    ts = df_m5["time"].iloc[bar_index]
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    hour_norm = ts.hour / 23.0
    dow_norm = ts.weekday() / 6.0
    session_asia, session_london, session_ny = _session_flags(ts)

    direction = 0.0
    if entry_net == int(NetSignal.BUY):
        direction = 1.0
    elif entry_net == int(NetSignal.SELL):
        direction = -1.0

    rsi = pc.m5_rsi_raw[bar_index]
    if np.isnan(rsi):
        rsi = 50.0

    spread = 0.0
    if "spread" in df_m5.columns:
        spread = float(df_m5["spread"].iloc[bar_index])

    atr_current = pc.m5_atr_value[bar_index]
    if np.isnan(atr_current):
        atr_current = 0.0

    return {
        "atr_current": float(atr_current),
        "atr_ratio": float(pc.m5_atr_ratio[bar_index]),
        "atr_factor": float(pc.m5_atr_factor[bar_index]),
        "ema_distance_pct": float(pc.m5_ema_distance_pct[bar_index]),
        "rsi": float(rsi),
        "entry_score": float(entry_score),
        "h1_score": float(h1_score),
        "donchian_score": float(pc.m5_donchian[bar_index]),
        "supertrend_score": float(pc.m5_supertrend[bar_index]),
        "rsi_strategy_score": float(pc.m5_rsi_score[bar_index]),
        "ema_strategy_score": float(pc.m5_ema[bar_index]),
        "h1_trend_code": H1_TREND_CODES.get(main_trend.value, 0.0),
        "hour_norm": float(hour_norm),
        "day_of_week_norm": float(dow_norm),
        "session_asia": session_asia,
        "session_london": session_london,
        "session_new_york": session_ny,
        "is_scalp_mode": 1.0 if is_scalp_mode else 0.0,
        "direction": direction,
        "spread": spread,
    }


def resolve_h1_trend_from_slice(df_h1: pd.DataFrame, config: BotConfig) -> tuple[MainTrend, float]:
    """H1 trend + score từ slice H1 (dùng khi training walk-forward)."""
    from app.trading.aggregator import aggregate_signal

    h1_signal = aggregate_signal(df_h1, config, include_rsi=False)
    main_trend, _, _ = _resolve_main_trend(h1_signal.net_signal)
    return main_trend, float(h1_signal.weighted_score)
