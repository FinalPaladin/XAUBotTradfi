"""Weighted multi-strategy signal aggregation."""

from __future__ import annotations

import pandas as pd

from app.models import BotConfig
from app.trading.indicators.atr import average_true_range
from app.trading.scoring import compute_strategy_scores
from app.trading.types import AggregatedSignal, NetSignal, OHLCV, StrategyResult

# 4 chữ số thập phân — tránh float drift (0.35+0.30 → 0.649999… thay vì 0.65)
SCORE_DECIMALS = 4
ATR_PERIOD = 14
ATR_AVG_LOOKBACK = 20
ATR_DAMPEN_FACTOR = 0.5


def normalize_score(value: float) -> float:
    """Làm tròn score để so sánh ngưỡng và hiển thị API ổn định."""
    return round(value, SCORE_DECIMALS)


def atr_volatility_factor(df: pd.DataFrame) -> tuple[float, dict]:
    """Giảm score khi ATR hiện tại thấp hơn trung bình 20 phiên (sideway/noise)."""
    min_bars = ATR_PERIOD + ATR_AVG_LOOKBACK + 1
    if len(df) < min_bars:
        return 1.0, {"reason": "insufficient_data", "dampened": False}

    atr_series = average_true_range(df, ATR_PERIOD)
    current_atr = float(atr_series.iloc[-1])
    avg_atr = float(atr_series.iloc[-(ATR_AVG_LOOKBACK + 1) : -1].mean())
    if pd.isna(current_atr) or pd.isna(avg_atr):
        return 1.0, {"reason": "insufficient_data", "dampened": False}

    dampened = current_atr < avg_atr
    factor = ATR_DAMPEN_FACTOR if dampened else 1.0
    return factor, {
        "current_atr": current_atr,
        "avg_atr": avg_atr,
        "dampened": dampened,
        "factor": factor,
    }


def _weighted_entry_score(config: BotConfig, results: list[StrategyResult]) -> float:
    return (
        config.donchian_weight * results[0].score
        + config.supertrend_weight * results[1].score
        + config.rsi_weight * results[2].score
        + config.ema_weight * results[3].score
    )


def _weighted_trend_score(config: BotConfig, results: list[StrategyResult]) -> float:
    trend_weight = config.donchian_weight + config.supertrend_weight
    if trend_weight <= 0:
        return 0.0
    return (
        (config.donchian_weight / trend_weight) * results[0].score
        + (config.supertrend_weight / trend_weight) * results[1].score
    )


def aggregate_signal(
    df: OHLCV,
    config: BotConfig,
    *,
    include_rsi: bool = True,
    apply_atr_filter: bool = False,
) -> AggregatedSignal:
    results = compute_strategy_scores(df, config)

    if include_rsi:
        raw_weighted = _weighted_entry_score(config, results)
        atr_factor = 1.0
        if apply_atr_filter:
            atr_factor, _ = atr_volatility_factor(df)
            raw_weighted *= atr_factor
        weighted = normalize_score(raw_weighted)
        used_results = results
        threshold = normalize_score(config.signal_threshold * atr_factor)
    else:
        weighted = normalize_score(_weighted_trend_score(config, results))
        used_results = results[:2]
        trend_weight = config.donchian_weight + config.supertrend_weight
        threshold = normalize_score(config.signal_threshold * trend_weight)

    if weighted >= threshold:
        net = int(NetSignal.BUY)
    elif weighted <= -threshold:
        net = int(NetSignal.SELL)
    else:
        net = int(NetSignal.HOLD)

    return AggregatedSignal(
        strategy_results=used_results,
        weighted_score=weighted,
        net_signal=net,
    )
