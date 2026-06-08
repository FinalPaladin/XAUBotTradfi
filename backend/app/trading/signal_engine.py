"""
Động cơ tín hiệu đa khung thời gian (Multi-Timeframe).

Luồng:
  1. H4 + H1 → xác định xu hướng chính (Main Trend)
  2. M15 hoặc M5 → tín hiệu vào lệnh chi tiết (Entry Signal)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.models import BotConfig
from app.trading.aggregator import aggregate_signal, atr_volatility_factor
from app.trading.market_data import MarketDataProvider
from app.trading.types import AggregatedSignal, NetSignal, StrategyResult


class MainTrend(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    SIDEWAY = "SIDEWAY"
    NEUTRAL = "NEUTRAL"


@dataclass
class TrendEntrySignal:
    """Kết quả sau khi lọc đa khung thời gian."""

    strategy_results: list[StrategyResult]
    weighted_score: float
    net_signal: int
    main_trend: MainTrend
    trend_source: str  # H4 | H1 | MIXED | NONE
    entry_timeframe: str
    h4_score: float = 0.0
    h1_score: float = 0.0
    entry_score: float = 0.0
    h4_results: list[StrategyResult] = field(default_factory=list)
    h1_results: list[StrategyResult] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def as_aggregated(self) -> AggregatedSignal:
        return AggregatedSignal(
            strategy_results=self.strategy_results,
            weighted_score=self.weighted_score,
            net_signal=self.net_signal,
        )


def _net_to_trend(net: int) -> MainTrend | None:
    if net == int(NetSignal.BUY):
        return MainTrend.BULLISH
    if net == int(NetSignal.SELL):
        return MainTrend.BEARISH
    return None


def _entry_timeframe_for_source(source: str) -> str:
    """H4 → M15 entry; H1 → M5 entry; sideway/mixed → M5 scalping."""
    if source == "H4":
        return "M15"
    return "M5"


def _resolve_main_trend(
    h4_net: int,
    h1_net: int,
) -> tuple[MainTrend, str, set[int]]:
    """
    Xác định xu hướng chính và chiều được phép giao dịch.

    - H4 & H1 đồng thuận TĂNG/GIẢM → chỉ LONG hoặc chỉ SHORT (nguồn H4 → M15)
    - H4 & H1 xung đột → SIDEWAY, cho phép cả LONG & SHORT (entry M5)
    - Chỉ một khung có xu hướng rõ → theo khung đó (H4→M15, H1→M5)
    """
    h4_trend = _net_to_trend(h4_net)
    h1_trend = _net_to_trend(h1_net)

    if h4_trend is not None and h4_trend == h1_trend:
        allowed = {h4_net}
        return h4_trend, "H4", allowed

    if h4_trend is not None and h1_trend is not None and h4_trend != h1_trend:
        return MainTrend.SIDEWAY, "MIXED", {int(NetSignal.BUY), int(NetSignal.SELL)}

    if h4_trend is not None and h1_trend is None:
        return h4_trend, "H4", {h4_net}

    if h1_trend is not None and h4_trend is None:
        return h1_trend, "H1", {h1_net}

    return MainTrend.NEUTRAL, "NONE", set()


def _filter_entry_signal(
    entry_net: int,
    allowed_nets: set[int],
    main_trend: MainTrend,
) -> int:
    """Chặn tín hiệu ngược xu hướng chính (trừ chế độ SIDEWAY)."""
    if main_trend == MainTrend.SIDEWAY:
        return entry_net
    if not allowed_nets:
        return int(NetSignal.HOLD)
    if entry_net in allowed_nets:
        return entry_net
    return int(NetSignal.HOLD)


def check_trend_and_entry_signal(
    config: BotConfig,
    market: MarketDataProvider | None = None,
) -> TrendEntrySignal:
    """
    Quét đa khung thời gian và trả về tín hiệu vào lệnh đã lọc.

    Bước 1 — Main Trend (H4 + H1):
        Donchian + SuperTrend trên H4 và H1 (không dùng RSI/EMA entry —
        các chỉ báo này chỉ dùng cho khung entry M15/M5).

    Bước 2 — Entry (M15 hoặc M5):
        Xu hướng từ H4 → quét entry trên M15.
        Xu hướng từ H1 hoặc SIDEWAY → quét entry trên M5.
    """
    provider = market or MarketDataProvider()
    lookback = config.bars_lookback

    df_h4 = provider.fetch_timeframe(config.symbol, "H4", lookback)
    df_h1 = provider.fetch_timeframe(config.symbol, "H1", lookback)

    h4_signal = aggregate_signal(df_h4, config, include_rsi=False)
    h1_signal = aggregate_signal(df_h1, config, include_rsi=False)

    main_trend, trend_source, allowed_nets = _resolve_main_trend(
        h4_signal.net_signal,
        h1_signal.net_signal,
    )
    entry_tf = _entry_timeframe_for_source(trend_source)

    df_entry = provider.fetch_timeframe(config.symbol, entry_tf, lookback)
    atr_factor, atr_meta = atr_volatility_factor(df_entry)
    entry_signal = aggregate_signal(df_entry, config, apply_atr_filter=True)

    final_net = _filter_entry_signal(
        entry_signal.net_signal,
        allowed_nets,
        main_trend,
    )

    meta = {
        "h4_net": h4_signal.net_signal,
        "h1_net": h1_signal.net_signal,
        "entry_net_raw": entry_signal.net_signal,
        "allowed_nets": sorted(allowed_nets),
        "main_trend": main_trend.value,
        "atr_factor": atr_factor,
        "atr": atr_meta,
    }

    return TrendEntrySignal(
        strategy_results=entry_signal.strategy_results,
        weighted_score=entry_signal.weighted_score,
        net_signal=final_net,
        main_trend=main_trend,
        trend_source=trend_source,
        entry_timeframe=entry_tf,
        h4_score=h4_signal.weighted_score,
        h1_score=h1_signal.weighted_score,
        entry_score=entry_signal.weighted_score,
        h4_results=h4_signal.strategy_results,
        h1_results=h1_signal.strategy_results,
        meta=meta,
    )
