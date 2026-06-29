"""
Động cơ tín hiệu scalping đa khung thời gian.

Luồng:
  1. H1 → xác định xu hướng chính (Main Trend)
  2. M5 → tín hiệu vào lệnh chi tiết (Entry Signal)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from app.models import BotConfig
from app.trading.aggregator import aggregate_signal, atr_volatility_factor
from app.trading.market_data import MarketDataProvider
from app.trading.trading_mode import (
    effective_scalp_entry_threshold,
    effective_signal_threshold,
    is_super_safe,
)
from app.trading.types import AggregatedSignal, NetSignal, StrategyResult

if TYPE_CHECKING:
    from app.trading.ai.ai_filter import MetaLabelingFilter

logger = logging.getLogger(__name__)

ENTRY_TIMEFRAME = "M5"
AI_FILTER_MIN_WIN_PROBABILITY = 55.0
AI_FILTER_VOLATILE_WIN_PROBABILITY = 62.0
ATR_VOLATILITY_BLOCK_RATIO = 1.15
COMPOSITE_MIN_ABS_M5_SCORE = 0.58


class _DisabledMetaLabelingFilter:
    """Placeholder khi worker không bật AI filter."""

    is_active = False
    min_win_probability = AI_FILTER_MIN_WIN_PROBABILITY

    def predict_win_probability(self, features: dict[str, float]) -> float:
        return 100.0


_NO_AI_FILTER = _DisabledMetaLabelingFilter()
SCALP_ENTRY_THRESHOLD = 0.8
# NORMAL + H1 trend: lớp 1 chỉ khi M5 đủ mạnh (tránh vào yếu kiểu -0.57)
NORMAL_TREND_MIN_SCORE = COMPOSITE_MIN_ABS_M5_SCORE


def resolve_entry_gate_threshold(
    config: BotConfig,
    *,
    main_trend: MainTrend,
    is_scalp_mode: bool = False,
) -> float:
    """
    Ngưỡng |M5 score| thực tế để mở lớp 1 (sau filter H1) — dùng cho worker log/UI.

    Khác aggregator net threshold (có ATR dampen ~0.33): đây là gate cuối.
    """
    if main_trend == MainTrend.NEUTRAL:
        return effective_scalp_entry_threshold(config)
    if is_super_safe(config):
        return effective_signal_threshold(config)
    return NORMAL_TREND_MIN_SCORE


class MainTrend(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


@dataclass
class TrendEntrySignal:
    """Kết quả sau khi lọc đa khung thời gian."""

    strategy_results: list[StrategyResult]
    weighted_score: float
    net_signal: int
    main_trend: MainTrend
    trend_source: str  # H1 | NONE
    entry_timeframe: str
    is_scalp_mode: bool = False
    h1_score: float = 0.0
    entry_score: float = 0.0
    h1_results: list[StrategyResult] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def as_aggregated(self) -> AggregatedSignal:
        return AggregatedSignal(
            strategy_results=self.strategy_results,
            weighted_score=self.weighted_score,
            net_signal=self.net_signal,
            is_scalp_mode=self.is_scalp_mode,
        )


def _net_to_trend(net: int) -> MainTrend | None:
    if net == int(NetSignal.BUY):
        return MainTrend.BULLISH
    if net == int(NetSignal.SELL):
        return MainTrend.BEARISH
    return None


def _resolve_main_trend(h1_net: int) -> tuple[MainTrend, str, set[int]]:
    """Xác định xu hướng chính từ H1. Chỉ giao dịch thuận trend (trừ H1 NEUTRAL scalp)."""
    h1_trend = _net_to_trend(h1_net)

    if h1_trend == MainTrend.BULLISH:
        return MainTrend.BULLISH, "H1", {int(NetSignal.BUY)}
    if h1_trend == MainTrend.BEARISH:
        return MainTrend.BEARISH, "H1", {int(NetSignal.SELL)}
    return MainTrend.NEUTRAL, "NONE", set()


def _apply_entry_safety_filters(
    final_net: int,
    is_scalp_mode: bool,
    filter_log: str,
    *,
    entry_score: float,
    atr_ratio: float | None,
    ai_filter: MetaLabelingFilter | None,
    ai_features: dict[str, float] | None,
) -> tuple[int, bool, str, float | None]:
    """
    Lớp bảo vệ composite trước khi mở lớp 1:
      - |M5 score| < 0.58
      - atr_ratio > 1.15 (volatility gate)
      - ai_win_prob < 55%
      - ai_win_prob < 62% AND atr_ratio > 1.15
    """
    if final_net not in (int(NetSignal.BUY), int(NetSignal.SELL)):
        return final_net, is_scalp_mode, filter_log, None

    if abs(entry_score) < COMPOSITE_MIN_ABS_M5_SCORE:
        logger.info(
            "[SAFETY] Blocked weak M5 score (%.2f, need |score| >= %.2f)",
            entry_score,
            COMPOSITE_MIN_ABS_M5_SCORE,
        )
        return int(NetSignal.HOLD), is_scalp_mode, (
            f"{filter_log} | [SAFETY] Blocked weak M5 "
            f"(|{entry_score:.2f}| < {COMPOSITE_MIN_ABS_M5_SCORE})"
        ), None

    ratio = atr_ratio
    if ratio is None and ai_features:
        ratio = float(ai_features.get("atr_ratio", 0.0))

    if ratio is not None and ratio > ATR_VOLATILITY_BLOCK_RATIO:
        logger.info(
            "[ATR GATE] Blocked entry — atr_ratio %.2f > %.2f",
            ratio,
            ATR_VOLATILITY_BLOCK_RATIO,
        )
        return int(NetSignal.HOLD), is_scalp_mode, (
            f"{filter_log} | [ATR GATE] Blocked high volatility "
            f"(atr_ratio={ratio:.2f} > {ATR_VOLATILITY_BLOCK_RATIO})"
        ), None

    win_prob: float | None = None
    if (
        ai_filter is not None
        and ai_filter.is_active
        and ai_features
    ):
        features = dict(ai_features)
        features["direction"] = 1.0 if final_net == int(NetSignal.BUY) else -1.0
        features["is_scalp_mode"] = 1.0 if is_scalp_mode else 0.0
        win_prob = ai_filter.predict_win_probability(features)

        if win_prob < AI_FILTER_MIN_WIN_PROBABILITY:
            logger.info(
                "[AI FILTER] Blocked entry due to low win probability (%.1f%%)",
                win_prob,
            )
            return int(NetSignal.HOLD), is_scalp_mode, (
                f"{filter_log} | [AI FILTER] Blocked entry due to low win probability "
                f"({win_prob:.1f}% < {AI_FILTER_MIN_WIN_PROBABILITY}%)"
            ), win_prob

        if (
            ratio is not None
            and ratio > ATR_VOLATILITY_BLOCK_RATIO
            and win_prob < AI_FILTER_VOLATILE_WIN_PROBABILITY
        ):
            logger.info(
                "[AI FILTER] Blocked volatile entry (prob %.1f%%, atr_ratio %.2f)",
                win_prob,
                ratio,
            )
            return int(NetSignal.HOLD), is_scalp_mode, (
                f"{filter_log} | [AI FILTER] Blocked volatile entry "
                f"(win {win_prob:.1f}% < {AI_FILTER_VOLATILE_WIN_PROBABILITY}% "
                f"and atr_ratio={ratio:.2f})"
            ), win_prob

        return final_net, is_scalp_mode, (
            f"{filter_log} | [AI FILTER] Win probability {win_prob:.1f}%"
        ), win_prob

    return final_net, is_scalp_mode, filter_log, win_prob


def _filter_entry_signal(
    entry_net: int,
    entry_score: float,
    main_trend: MainTrend,
    *,
    entry_threshold: float,
    scalp_threshold: float,
    super_safe: bool,
    atr_ratio: float | None = None,
    ai_filter: MetaLabelingFilter | None = None,
    ai_features: dict[str, float] | None = None,
) -> tuple[int, bool, str, float | None]:
    """
    Lọc tín hiệu M5 theo xu hướng H1.

    - H1 BULLISH: chỉ LONG (chặn SHORT ngược trend).
    - H1 BEARISH: chỉ SHORT (chặn LONG ngược trend).
    - H1 NEUTRAL: scalp mode khi điểm M5 cực cao (>= scalp_threshold).
    - SUPER_SAFE: không vào khi H1 NEUTRAL (chỉ thuận trend + ngưỡng cao).
    - NORMAL + H1 trend: lớp 1 cần |M5 score| >= NORMAL_TREND_MIN_SCORE (0.58).
    """
    if main_trend == MainTrend.BULLISH:
        if super_safe:
            if entry_score >= entry_threshold:
                return _apply_entry_safety_filters(
                    int(NetSignal.BUY),
                    False,
                    (
                        f"H1 BULLISH | M5 Score: {entry_score:+.2f} "
                        f"-> Allowed LONG (SUPER_SAFE, need >= +{entry_threshold})"
                    ),
                    entry_score=entry_score,
                    atr_ratio=atr_ratio,
                    ai_filter=ai_filter,
                    ai_features=ai_features,
                )
            return int(NetSignal.HOLD), False, (
                f"H1 BULLISH | M5 Score: {entry_score:+.2f} "
                f"-> BLOCKED (SUPER_SAFE need >= +{entry_threshold} LONG)"
            ), None
        if entry_score >= NORMAL_TREND_MIN_SCORE:
            return _apply_entry_safety_filters(
                int(NetSignal.BUY),
                False,
                (
                    f"H1 BULLISH | M5 Score: {entry_score:+.2f} "
                    f"-> Allowed LONG (NORMAL, need >= +{NORMAL_TREND_MIN_SCORE})"
                ),
                entry_score=entry_score,
                atr_ratio=atr_ratio,
                ai_filter=ai_filter,
                ai_features=ai_features,
            )
        if entry_net == int(NetSignal.SELL):
            return int(NetSignal.HOLD), False, (
                f"H1 BULLISH | M5 Score: {entry_score:+.2f} "
                f"-> BLOCKED SHORT (trend-only mode)"
            ), None
        return int(NetSignal.HOLD), False, (
            f"H1 BULLISH | M5 Score: {entry_score:+.2f} "
            f"-> BLOCKED (NORMAL need >= +{NORMAL_TREND_MIN_SCORE} LONG)"
        ), None

    if main_trend == MainTrend.BEARISH:
        if super_safe:
            if entry_score <= -entry_threshold:
                return _apply_entry_safety_filters(
                    int(NetSignal.SELL),
                    False,
                    (
                        f"H1 BEARISH | M5 Score: {entry_score:+.2f} "
                        f"-> Allowed SHORT (SUPER_SAFE, need <= -{entry_threshold})"
                    ),
                    entry_score=entry_score,
                    atr_ratio=atr_ratio,
                    ai_filter=ai_filter,
                    ai_features=ai_features,
                )
            return int(NetSignal.HOLD), False, (
                f"H1 BEARISH | M5 Score: {entry_score:+.2f} "
                f"-> BLOCKED (SUPER_SAFE need <= -{entry_threshold} SHORT)"
            ), None
        if entry_score <= -NORMAL_TREND_MIN_SCORE:
            return _apply_entry_safety_filters(
                int(NetSignal.SELL),
                False,
                (
                    f"H1 BEARISH | M5 Score: {entry_score:+.2f} "
                    f"-> Allowed SHORT (NORMAL, need <= -{NORMAL_TREND_MIN_SCORE})"
                ),
                entry_score=entry_score,
                atr_ratio=atr_ratio,
                ai_filter=ai_filter,
                ai_features=ai_features,
            )
        if entry_net == int(NetSignal.BUY):
            return int(NetSignal.HOLD), False, (
                f"H1 BEARISH | M5 Score: {entry_score:+.2f} "
                f"-> BLOCKED LONG (trend-only mode)"
            ), None
        return int(NetSignal.HOLD), False, (
            f"H1 BEARISH | M5 Score: {entry_score:+.2f} "
            f"-> BLOCKED (NORMAL need <= -{NORMAL_TREND_MIN_SCORE} SHORT)"
        ), None

    if super_safe:
        return int(NetSignal.HOLD), False, (
            f"H1 NEUTRAL | M5 Score: {entry_score:+.2f} "
            f"-> BLOCKED (SUPER_SAFE — chỉ thuận H1 trend)"
        ), None

    if entry_score >= scalp_threshold:
        return _apply_entry_safety_filters(
            int(NetSignal.BUY),
            True,
            (
                f"H1 NEUTRAL | M5 Score: {entry_score:+.2f} "
                f"-> OVERRIDE: Allowed LONG (SCALP MODE - 50% Volume)"
            ),
            entry_score=entry_score,
            atr_ratio=atr_ratio,
            ai_filter=ai_filter,
            ai_features=ai_features,
        )
    if entry_score <= -scalp_threshold:
        return _apply_entry_safety_filters(
            int(NetSignal.SELL),
            True,
            (
                f"H1 NEUTRAL | M5 Score: {entry_score:+.2f} "
                f"-> OVERRIDE: Allowed SHORT (SCALP MODE - 50% Volume)"
            ),
            entry_score=entry_score,
            atr_ratio=atr_ratio,
            ai_filter=ai_filter,
            ai_features=ai_features,
        )
    return int(NetSignal.HOLD), False, (
        f"H1 NEUTRAL | M5 Score: {entry_score:+.2f} "
        f"-> BLOCKED (need >= +{scalp_threshold} LONG / "
        f"<= -{scalp_threshold} SHORT)"
    ), None


def check_trend_and_entry_signal(
    config: BotConfig,
    market: MarketDataProvider | None = None,
    *,
    ai_filter: MetaLabelingFilter | None = None,
) -> TrendEntrySignal:
    """
    Quét H1 (trend) + M5 (entry) và trả về tín hiệu vào lệnh đã lọc.

    Bước 1 — Main Trend (H1):
        Donchian + SuperTrend trên H1 (không dùng RSI/EMA).

    Bước 2 — Entry (M5):
        Donchian, SuperTrend, RSI, EMA21 + ATR dampen (ngưỡng scale theo atr_factor).
    """
    provider = market or MarketDataProvider()
    lookback = config.bars_lookback

    df_h1 = provider.fetch_timeframe(config.symbol, "H1", lookback)
    h1_signal = aggregate_signal(df_h1, config, include_rsi=False)

    main_trend, trend_source, allowed_nets = _resolve_main_trend(
        h1_signal.net_signal,
    )

    df_entry = provider.fetch_timeframe(config.symbol, ENTRY_TIMEFRAME, lookback)
    atr_factor, atr_meta = atr_volatility_factor(df_entry)
    entry_signal = aggregate_signal(
        df_entry,
        config,
        apply_atr_filter=True,
        h1_trend=main_trend.value,
    )

    if ai_filter is None:
        ai_filter = _NO_AI_FILTER

    from app.trading.ai.features import _atr_ratio, build_entry_features

    atr_ratio_value, _ = _atr_ratio(df_entry)
    ai_features = None
    if ai_filter.is_active:
        ai_features = build_entry_features(
            df_m5=df_entry,
            df_h1=df_h1,
            config=config,
            main_trend=main_trend,
            entry_score=entry_signal.weighted_score,
            h1_score=h1_signal.weighted_score,
            entry_net=entry_signal.net_signal,
            is_scalp_mode=False,
        )

    final_net, is_scalp_mode, filter_log, ai_win_probability = _filter_entry_signal(
        entry_signal.net_signal,
        entry_signal.weighted_score,
        main_trend,
        entry_threshold=effective_signal_threshold(config),
        scalp_threshold=effective_scalp_entry_threshold(config),
        super_safe=is_super_safe(config),
        atr_ratio=atr_ratio_value,
        ai_filter=ai_filter,
        ai_features=ai_features,
    )

    ai_threshold = (
        ai_filter.min_win_probability if ai_filter.is_active else None
    )

    meta = {
        "h1_net": h1_signal.net_signal,
        "entry_net_raw": entry_signal.net_signal,
        "allowed_nets": sorted(allowed_nets),
        "main_trend": main_trend.value,
        "is_scalp_mode": is_scalp_mode,
        "filter_log": filter_log,
        "atr_factor": atr_factor,
        "atr_ratio": atr_ratio_value,
        "atr": atr_meta,
        "entry_scoring": entry_signal.scoring_meta,
        "ai_win_probability": ai_win_probability,
        "ai_filter_threshold": ai_threshold,
    }

    return TrendEntrySignal(
        strategy_results=entry_signal.strategy_results,
        weighted_score=entry_signal.weighted_score,
        net_signal=final_net,
        main_trend=main_trend,
        trend_source=trend_source,
        entry_timeframe=ENTRY_TIMEFRAME,
        is_scalp_mode=is_scalp_mode,
        h1_score=h1_signal.weighted_score,
        entry_score=entry_signal.weighted_score,
        h1_results=h1_signal.strategy_results,
        meta=meta,
    )
