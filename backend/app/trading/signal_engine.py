"""
Động cơ tín hiệu scalping đa khung thời gian.

Luồng:
  1. H1 → xác định xu hướng chính (Main Trend)
  2. M5 → tín hiệu vào lệnh chi tiết (Entry Signal)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.models import BotConfig
from app.trading.aggregator import aggregate_signal, atr_volatility_factor
from app.trading.market_data import MarketDataProvider
from app.trading.types import AggregatedSignal, NetSignal, StrategyResult

ENTRY_TIMEFRAME = "M5"
SCALP_ENTRY_THRESHOLD = 0.8


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


def _filter_entry_signal(
    entry_net: int,
    entry_score: float,
    main_trend: MainTrend,
    *,
    entry_threshold: float,
) -> tuple[int, bool, str]:
    """
    Lọc tín hiệu M5 theo xu hướng H1.

    - H1 BULLISH: chỉ LONG (chặn SHORT ngược trend).
    - H1 BEARISH: chỉ SHORT (chặn LONG ngược trend).
    - H1 NEUTRAL: scalp mode khi điểm M5 cực cao (>= 0.8 / <= -0.8).
    """
    if main_trend == MainTrend.BULLISH:
        if entry_net == int(NetSignal.BUY):
            return entry_net, False, (
                f"H1 BULLISH | M5 Score: {entry_score:+.2f} "
                f"-> Allowed LONG (NORMAL - 100% Volume)"
            )
        return int(NetSignal.HOLD), False, (
            f"H1 BULLISH | M5 Score: {entry_score:+.2f} "
            f"-> BLOCKED SHORT (trend-only mode)"
        )

    if main_trend == MainTrend.BEARISH:
        if entry_net == int(NetSignal.SELL):
            return entry_net, False, (
                f"H1 BEARISH | M5 Score: {entry_score:+.2f} "
                f"-> Allowed SHORT (NORMAL - 100% Volume)"
            )
        return int(NetSignal.HOLD), False, (
            f"H1 BEARISH | M5 Score: {entry_score:+.2f} "
            f"-> BLOCKED LONG (trend-only mode)"
        )

    if entry_score >= SCALP_ENTRY_THRESHOLD:
        return int(NetSignal.BUY), True, (
            f"H1 NEUTRAL | M5 Score: {entry_score:+.2f} "
            f"-> OVERRIDE: Allowed LONG (SCALP MODE - 50% Volume)"
        )
    if entry_score <= -SCALP_ENTRY_THRESHOLD:
        return int(NetSignal.SELL), True, (
            f"H1 NEUTRAL | M5 Score: {entry_score:+.2f} "
            f"-> OVERRIDE: Allowed SHORT (SCALP MODE - 50% Volume)"
        )
    return int(NetSignal.HOLD), False, (
        f"H1 NEUTRAL | M5 Score: {entry_score:+.2f} "
        f"-> BLOCKED (need >= +{SCALP_ENTRY_THRESHOLD} LONG / "
        f"<= -{SCALP_ENTRY_THRESHOLD} SHORT)"
    )


def check_trend_and_entry_signal(
    config: BotConfig,
    market: MarketDataProvider | None = None,
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
    entry_signal = aggregate_signal(df_entry, config, apply_atr_filter=True)

    final_net, is_scalp_mode, filter_log = _filter_entry_signal(
        entry_signal.net_signal,
        entry_signal.weighted_score,
        main_trend,
        entry_threshold=config.signal_threshold,
    )

    meta = {
        "h1_net": h1_signal.net_signal,
        "entry_net_raw": entry_signal.net_signal,
        "allowed_nets": sorted(allowed_nets),
        "main_trend": main_trend.value,
        "is_scalp_mode": is_scalp_mode,
        "filter_log": filter_log,
        "atr_factor": atr_factor,
        "atr": atr_meta,
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
