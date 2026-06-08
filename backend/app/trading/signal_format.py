"""Format strategy scores and weighted-score formula for logs/UI."""

from __future__ import annotations

from app.models import BotConfig
from app.trading.aggregator import SCORE_DECIMALS, normalize_score
from app.trading.types import NetSignal, StrategyResult

_DISPLAY_NAMES = {
    "donchian": "Donchian",
    "supertrend": "SuperTrend",
    "rsi": "RSI",
    "ema21": "EMA21",
}


def net_signal_label(net: int) -> str:
    if net == int(NetSignal.BUY):
        return "BUY"
    if net == int(NetSignal.SELL):
        return "SELL"
    return "HOLD"


def allowed_nets_label(allowed: list[int] | set[int]) -> str:
    labels: list[str] = []
    if int(NetSignal.BUY) in allowed:
        labels.append("LONG")
    if int(NetSignal.SELL) in allowed:
        labels.append("SHORT")
    return "/".join(labels) if labels else "NONE"


def breakdown_weighted_score(
    config: BotConfig,
    results: list[StrategyResult],
    *,
    include_rsi: bool = True,
    atr_factor: float = 1.0,
) -> dict:
    """Build per-strategy contributions and human-readable formula."""
    if include_rsi:
        pairs = [
            (results[0], config.donchian_weight),
            (results[1], config.supertrend_weight),
            (results[2], config.rsi_weight),
            (results[3], config.ema_weight),
        ]
        threshold = normalize_score(config.signal_threshold)
    else:
        trend_weight = config.donchian_weight + config.supertrend_weight
        if trend_weight <= 0:
            return {
                "donchian": 0.0,
                "supertrend": 0.0,
                "rsi": None,
                "ema21": None,
                "weighted_score": 0.0,
                "threshold": 0.0,
                "formula": "n/a",
                "atr_factor": atr_factor,
            }
        pairs = [
            (results[0], config.donchian_weight / trend_weight),
            (results[1], config.supertrend_weight / trend_weight),
        ]
        threshold = normalize_score(config.signal_threshold * trend_weight)

    scores: dict[str, float | None] = {
        "donchian": 0.0,
        "supertrend": 0.0,
        "rsi": None,
        "ema21": None,
    }
    parts: list[str] = []
    total = 0.0

    for result, weight in pairs:
        key = result.name.replace("_divergence", "")
        if key in scores:
            scores[key] = float(result.score)

        contrib = weight * result.score
        total += contrib
        label = _DISPLAY_NAMES.get(result.name, result.name)
        parts.append(f"{weight:.2f}*{result.score:+.2f} [{label}]")

    if include_rsi and atr_factor != 1.0:
        total *= atr_factor
        parts.append(f"* {atr_factor:.1f} [ATR dampen]")

    weighted = normalize_score(total)
    formula = " + ".join(parts) + f" = {weighted:+.4f}"

    return {
        **scores,
        "weighted_score": weighted,
        "threshold": threshold,
        "formula": formula,
        "atr_factor": atr_factor,
    }


def format_pnl(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}"
