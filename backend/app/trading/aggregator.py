"""Weighted multi-strategy signal aggregation."""

from __future__ import annotations

import logging
from typing import Literal

import pandas as pd

from app.models import BotConfig
from app.trading.indicators.atr import average_true_range
from app.trading.scoring import compute_strategy_scores
from app.trading.trading_mode import resolve_entry_threshold, resolve_trend_threshold
from app.trading.types import AggregatedSignal, NetSignal, OHLCV, StrategyResult

logger = logging.getLogger(__name__)

# 4 chữ số thập phân — tránh float drift (0.35+0.30 → 0.649999… thay vì 0.65)
SCORE_DECIMALS = 4
ATR_PERIOD = 14
ATR_AVG_LOOKBACK = 20
ATR_DAMPEN_FACTOR = 0.5

RSI_EXHAUSTION_LONG = 75.0
RSI_EXHAUSTION_SHORT = 25.0
EMA_DISTANCE_PENALTY_FACTOR = 0.2

H1Trend = Literal["BULLISH", "BEARISH", "NEUTRAL"]


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


def _rsi_midline_score(rsi_val: float) -> float:
    """Static RSI midline bias used when H1 trend is neutral."""
    if rsi_val < 45.0:
        return -1.0
    if rsi_val < 50.0:
        return -0.5 + (-0.5) * (50.0 - rsi_val) / 5.0
    if rsi_val > 55.0:
        return 1.0
    if rsi_val > 50.0:
        return 0.5 + 0.5 * (rsi_val - 50.0) / 5.0
    return 0.0


def _dynamic_rsi_momentum_score(rsi_val: float, h1_trend: H1Trend | None) -> float:
    """
    Zone-based RSI contribution aligned with H1 trend.

    Bullish sweet spot: RSI 55-65 (full +1). RSI 65-70 fades; RSI 70-75 anticipates pullback.
    Bearish uses mirrored RSI zones.
    """
    if h1_trend not in ("BULLISH", "BEARISH"):
        return _rsi_midline_score(rsi_val)

    aligned_rsi = rsi_val if h1_trend == "BULLISH" else 100.0 - rsi_val

    if aligned_rsi < 45.0:
        return max(-1.0, -0.5 + (aligned_rsi - 45.0) / 20.0)
    if aligned_rsi < 50.0:
        return -0.5 + 0.5 * (aligned_rsi - 45.0) / 5.0
    if aligned_rsi <= 55.0:
        return 0.5 * (aligned_rsi - 50.0) / 5.0
    if aligned_rsi <= 65.0:
        return 0.5 + 0.5 * (aligned_rsi - 55.0) / 10.0
    if aligned_rsi <= 70.0:
        return 1.0 - 0.7 * (aligned_rsi - 65.0) / 5.0
    if aligned_rsi <= 75.0:
        return 0.3 - 0.6 * (aligned_rsi - 70.0) / 5.0
    return -0.5


def compute_m5_entry_score(
    config: BotConfig,
    results: list[StrategyResult],
    *,
    h1_trend: H1Trend | None = None,
) -> tuple[float, dict]:
    """
    M5 entry score with layered risk controls:

    1. RSI exhaustion veto (blocks late entries when RSI is stretched).
    2. Dynamic RSI momentum zones (favor 55-65, fade >70).
    3. EMA21 mean-reversion penalty when price is too far from EMA.
    """
    donchian = results[0].score
    supertrend = results[1].score
    rsi_result = results[2]
    ema_result = results[3]

    m5_raw_rsi = rsi_result.raw.get("rsi")
    ema21_value = ema_result.raw.get("ema")
    current_price = ema_result.raw.get("close")

    meta: dict = {
        "h1_trend": h1_trend,
        "m5_raw_rsi": m5_raw_rsi,
        "rsi_veto": False,
        "ema_distance_penalty": False,
    }

    if h1_trend == "BULLISH" and m5_raw_rsi is not None and m5_raw_rsi > RSI_EXHAUSTION_LONG:
        logger.info(
            "BLOCKED LONG (RSI Exhaustion): RSI=%.2f > %.0f",
            m5_raw_rsi,
            RSI_EXHAUSTION_LONG,
        )
        meta["rsi_veto"] = True
        meta["block_reason"] = "rsi_exhaustion_long"
        return 0.0, meta

    if h1_trend == "BEARISH" and m5_raw_rsi is not None and m5_raw_rsi < RSI_EXHAUSTION_SHORT:
        logger.info(
            "BLOCKED SHORT (RSI Exhaustion): RSI=%.2f < %.0f",
            m5_raw_rsi,
            RSI_EXHAUSTION_SHORT,
        )
        meta["rsi_veto"] = True
        meta["block_reason"] = "rsi_exhaustion_short"
        return 0.0, meta

    if m5_raw_rsi is not None:
        rsi_score = _dynamic_rsi_momentum_score(m5_raw_rsi, h1_trend)
    else:
        rsi_score = rsi_result.score
    meta["rsi_score"] = rsi_score
    meta["rsi_score_static"] = rsi_result.score

    m5_score = (
        config.donchian_weight * donchian
        + config.supertrend_weight * supertrend
        + config.rsi_weight * rsi_score
        + config.ema_weight * ema_result.score
    )
    meta["score_before_penalty"] = m5_score

    distance_threshold = getattr(config, "ema_distance_threshold", None) or 0.4
    if current_price is not None and ema21_value is not None and ema21_value > 0:
        distance_percent = abs(current_price - ema21_value) / ema21_value * 100
        meta["ema_distance_percent"] = distance_percent
        meta["ema_distance_threshold"] = distance_threshold
        if distance_percent > distance_threshold:
            logger.info(
                "PENALIZED entry (EMA Distance): distance=%.3f%% > threshold=%.3f%%",
                distance_percent,
                distance_threshold,
            )
            m5_score *= EMA_DISTANCE_PENALTY_FACTOR
            meta["ema_distance_penalty"] = True

    meta["final_score"] = m5_score
    return m5_score, meta


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
    h1_trend: H1Trend | None = None,
) -> AggregatedSignal:
    results = compute_strategy_scores(df, config)

    if include_rsi:
        raw_weighted, entry_meta = compute_m5_entry_score(
            config, results, h1_trend=h1_trend
        )
        atr_factor = 1.0
        if apply_atr_filter:
            atr_factor, atr_meta = atr_volatility_factor(df)
            raw_weighted *= atr_factor
            entry_meta["atr_factor"] = atr_factor
            entry_meta["atr"] = atr_meta
        weighted = normalize_score(raw_weighted)
        used_results = results
        threshold = resolve_entry_threshold(config, atr_factor)
    else:
        weighted = normalize_score(_weighted_trend_score(config, results))
        used_results = results[:2]
        trend_weight = config.donchian_weight + config.supertrend_weight
        threshold = resolve_trend_threshold(config, trend_weight)
        entry_meta = {}

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
        scoring_meta=entry_meta,
    )
