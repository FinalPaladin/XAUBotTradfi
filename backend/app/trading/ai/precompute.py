"""Precompute strategy scores theo từng nến M5 — tăng tốc training Meta-Labeling."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.models import BotConfig
from app.trading.aggregator import atr_volatility_factor, compute_m5_entry_score, normalize_score
from app.trading.ai.data_loader import precompute_h1_end_indices, slice_h1_by_index
from app.trading.scoring import compute_strategy_scores
from app.trading.signal_engine import _resolve_main_trend
from app.trading.strategies import donchian_strategy, supertrend_strategy
from app.trading.trading_mode import resolve_entry_threshold, resolve_trend_threshold
from app.trading.types import NetSignal


@dataclass
class PrecomputedTrainingData:
    min_bar: int
    valid: np.ndarray
    h1_weighted: np.ndarray
    h1_net: np.ndarray
    m5_entry_weighted: np.ndarray
    m5_entry_net: np.ndarray
    m5_atr_factor: np.ndarray
    m5_atr_value: np.ndarray
    m5_atr_ratio: np.ndarray
    m5_rsi_raw: np.ndarray
    m5_ema_distance_pct: np.ndarray
    m5_donchian: np.ndarray
    m5_supertrend: np.ndarray
    m5_rsi_score: np.ndarray
    m5_ema: np.ndarray


def _net_from_weighted(weighted: float, threshold: float) -> int:
    if weighted >= threshold:
        return int(NetSignal.BUY)
    if weighted <= -threshold:
        return int(NetSignal.SELL)
    return int(NetSignal.HOLD)


def precompute_training_data(
    df_h1: pd.DataFrame,
    df_m5: pd.DataFrame,
    config: BotConfig,
    *,
    lookback: int | None = None,
) -> PrecomputedTrainingData:
    lookback = lookback or config.bars_lookback
    min_bar = max(lookback, 50)
    n = len(df_m5)

    valid = np.zeros(n, dtype=np.bool_)
    h1_weighted = np.zeros(n, dtype=np.float64)
    h1_net = np.zeros(n, dtype=np.int8)
    m5_entry_weighted = np.zeros(n, dtype=np.float64)
    m5_entry_net = np.zeros(n, dtype=np.int8)
    m5_atr_factor = np.ones(n, dtype=np.float64)
    m5_atr_value = np.full(n, np.nan, dtype=np.float64)
    m5_atr_ratio = np.ones(n, dtype=np.float64)
    m5_rsi_raw = np.full(n, np.nan, dtype=np.float64)
    m5_ema_distance_pct = np.zeros(n, dtype=np.float64)
    m5_donchian = np.zeros(n, dtype=np.float64)
    m5_supertrend = np.zeros(n, dtype=np.float64)
    m5_rsi_score = np.zeros(n, dtype=np.float64)
    m5_ema = np.zeros(n, dtype=np.float64)

    h1_end_indices = precompute_h1_end_indices(df_h1, df_m5)
    trend_weight = config.donchian_weight + config.supertrend_weight
    total = max(n - min_bar, 1)
    report_every = max(2000, total // 10)

    for offset, i in enumerate(range(min_bar, n)):
        if offset > 0 and offset % report_every == 0:
            print(f"  precompute: {offset}/{total} bars...", flush=True)

        h1_end = int(h1_end_indices[i])
        if h1_end < 29:
            continue

        h1_slice = slice_h1_by_index(df_h1, h1_end, lookback)
        m5_slice = df_m5.iloc[max(0, i - lookback + 1) : i + 1].reset_index(drop=True)
        if len(h1_slice) < 30 or len(m5_slice) < 30:
            continue

        valid[i] = True

        h1_d = donchian_strategy.evaluate(h1_slice, config).score
        h1_st = supertrend_strategy.evaluate(h1_slice, config).score
        if trend_weight > 0:
            hw = normalize_score(
                (config.donchian_weight / trend_weight) * h1_d
                + (config.supertrend_weight / trend_weight) * h1_st
            )
        else:
            hw = 0.0
        h1_weighted[i] = hw
        h1_threshold = normalize_score(config.signal_threshold * trend_weight)
        h1_net[i] = _net_from_weighted(hw, h1_threshold)

        main_trend, _, _ = _resolve_main_trend(int(h1_net[i]))
        results = compute_strategy_scores(m5_slice, config)
        m5_donchian[i] = results[0].score
        m5_supertrend[i] = results[1].score
        m5_rsi_score[i] = results[2].score
        m5_ema[i] = results[3].score

        rsi_raw = results[2].raw.get("rsi")
        if rsi_raw is not None:
            m5_rsi_raw[i] = float(rsi_raw)

        ema_val = results[3].raw.get("ema")
        close = results[3].raw.get("close")
        if close is not None and ema_val is not None and ema_val > 0:
            m5_ema_distance_pct[i] = abs(close - ema_val) / ema_val * 100.0

        entry_score, _ = compute_m5_entry_score(
            config, results, h1_trend=main_trend.value
        )
        atr_factor, atr_meta = atr_volatility_factor(m5_slice)
        m5_atr_factor[i] = atr_factor
        current_atr = atr_meta.get("current_atr")
        avg_atr = atr_meta.get("avg_atr")
        if current_atr is not None:
            m5_atr_value[i] = float(current_atr)
        if current_atr is not None and avg_atr is not None and avg_atr > 0:
            m5_atr_ratio[i] = float(current_atr) / float(avg_atr)

        weighted = normalize_score(entry_score * atr_factor)
        m5_entry_weighted[i] = weighted
        threshold = resolve_entry_threshold(config, atr_factor)
        m5_entry_net[i] = _net_from_weighted(weighted, threshold)

    return PrecomputedTrainingData(
        min_bar=min_bar,
        valid=valid,
        h1_weighted=h1_weighted,
        h1_net=h1_net,
        m5_entry_weighted=m5_entry_weighted,
        m5_entry_net=m5_entry_net,
        m5_atr_factor=m5_atr_factor,
        m5_atr_value=m5_atr_value,
        m5_atr_ratio=m5_atr_ratio,
        m5_rsi_raw=m5_rsi_raw,
        m5_ema_distance_pct=m5_ema_distance_pct,
        m5_donchian=m5_donchian,
        m5_supertrend=m5_supertrend,
        m5_rsi_score=m5_rsi_score,
        m5_ema=m5_ema,
    )
