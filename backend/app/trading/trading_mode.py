"""Trading mode overlays — NORMAL vs SUPER_SAFE effective settings."""

from __future__ import annotations

from app.models import BotConfig, TradingMode

# DCA-4 strategy (NORMAL)
NORMAL_MAX_LAYERS = 4
NORMAL_LAYER_SPACING = 4.0
NORMAL_BASKET_TP_USD = 1.0
NORMAL_FULL_STACK_LOSS_PCT = 40.0

# SUPER_SAFE — stricter entry, smaller stack, tighter exits
SUPER_SAFE_SIGNAL_THRESHOLD = 0.80
SUPER_SAFE_MAX_LAYERS = 2
SUPER_SAFE_LAYER_SPACING = 5.0
SUPER_SAFE_BASKET_TP_USD = 0.5
SUPER_SAFE_FULL_STACK_LOSS_PCT = 20.0
SUPER_SAFE_COUNTER_TREND_MAX_LAYERS = 1


def is_super_safe(config: BotConfig) -> bool:
    mode = getattr(config, "trading_mode", None)
    return mode == TradingMode.SUPER_SAFE


def effective_signal_threshold(config: BotConfig) -> float:
    if is_super_safe(config):
        return max(config.signal_threshold, SUPER_SAFE_SIGNAL_THRESHOLD)
    return config.signal_threshold


def resolve_entry_threshold(config: BotConfig, atr_factor: float = 1.0) -> float:
    """Ngưỡng M5 entry — SUPER_SAFE: cố định 0.80, không hạ bởi ATR dampen."""
    from app.trading.aggregator import normalize_score

    base = effective_signal_threshold(config)
    if is_super_safe(config):
        return normalize_score(base)
    return normalize_score(base * atr_factor)


def resolve_trend_threshold(config: BotConfig, trend_weight: float) -> float:
    """Ngưỡng H1 trend — SUPER_SAFE: cố định 0.80."""
    from app.trading.aggregator import normalize_score

    base = effective_signal_threshold(config)
    if is_super_safe(config):
        return normalize_score(base)
    return normalize_score(base * trend_weight)


def effective_scalp_entry_threshold(config: BotConfig) -> float:
    """H1 NEUTRAL scalp gate — disabled in SUPER_SAFE (returns impossibly high)."""
    if is_super_safe(config):
        return 1.0
    from app.trading.signal_engine import SCALP_ENTRY_THRESHOLD

    return SCALP_ENTRY_THRESHOLD


def effective_max_layers(config: BotConfig) -> int:
    cap = SUPER_SAFE_MAX_LAYERS if is_super_safe(config) else NORMAL_MAX_LAYERS
    stored = getattr(config, "max_layers", None) or config.max_open_positions
    return min(stored, cap)


def effective_layer_spacing_min(config: BotConfig) -> float:
    if is_super_safe(config):
        return SUPER_SAFE_LAYER_SPACING
    return getattr(config, "layer_spacing_min", None) or NORMAL_LAYER_SPACING


def effective_basket_tp_usd(config: BotConfig) -> float:
    if is_super_safe(config):
        return SUPER_SAFE_BASKET_TP_USD
    return getattr(config, "basket_tp_min_usd", None) or NORMAL_BASKET_TP_USD


def effective_full_stack_loss_pct(config: BotConfig) -> float:
    if is_super_safe(config):
        return SUPER_SAFE_FULL_STACK_LOSS_PCT
    pct = getattr(config, "max_basket_loss_pct", None)
    if pct is not None and pct > 0:
        return pct
    return NORMAL_FULL_STACK_LOSS_PCT


def effective_counter_trend_max_layers(config: BotConfig) -> int:
    if is_super_safe(config):
        return SUPER_SAFE_COUNTER_TREND_MAX_LAYERS
    return getattr(config, "counter_trend_max_layers", 1) or 1


def effective_full_stack_layer_count(config: BotConfig) -> int:
    return effective_max_layers(config)
