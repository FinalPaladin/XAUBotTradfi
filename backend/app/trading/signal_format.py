"""Format strategy scores and weighted-score formula for logs/UI."""

from __future__ import annotations

from app.models import BotConfig
from app.trading.aggregator import SCORE_DECIMALS, normalize_score
from app.trading.trading_mode import resolve_entry_threshold, resolve_trend_threshold
from app.trading.types import NetSignal, StrategyResult

_DISPLAY_NAMES = {
    "donchian": "Donchian",
    "supertrend": "SuperTrend",
    "rsi": "RSI",
    "ema21": "EMA21",
}

_EMA_DISTANCE_PENALTY_FACTOR = 0.2


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


def format_entry_scoring_monitor(entry_scoring: dict | None) -> list[str]:
    """Human-readable M5 scoring layers for worker / Telegram monitoring."""
    if not entry_scoring:
        return []

    lines: list[str] = []
    raw_rsi = entry_scoring.get("m5_raw_rsi")
    rsi_score = entry_scoring.get("rsi_score")
    rsi_static = entry_scoring.get("rsi_score_static")

    if raw_rsi is not None:
        if rsi_score is not None and rsi_static is not None and rsi_score != rsi_static:
            lines.append(
                f"  M5 RSI={raw_rsi:.1f} | động={rsi_score:+.2f} "
                f"(tĩnh={rsi_static:+.2f})"
            )
        elif rsi_score is not None:
            lines.append(f"  M5 RSI={raw_rsi:.1f} | score={rsi_score:+.2f}")

    if entry_scoring.get("rsi_veto"):
        reason = entry_scoring.get("block_reason", "")
        if reason == "rsi_exhaustion_long":
            lines.append("  >> CHẶN LONG (RSI kiệt sức / quá mua)")
        elif reason == "rsi_exhaustion_short":
            lines.append("  >> CHẶN SHORT (RSI kiệt sức / quá bán)")
        else:
            lines.append("  >> CHẶN entry (RSI veto)")

    dist = entry_scoring.get("ema_distance_percent")
    thresh = entry_scoring.get("ema_distance_threshold")
    if dist is not None and thresh is not None:
        if entry_scoring.get("ema_distance_penalty"):
            before = entry_scoring.get("score_before_penalty")
            before_txt = f"{before:+.2f}" if before is not None else "n/a"
            lines.append(
                f"  >> PHẠT EMA distance: {dist:.3f}% > {thresh:.3f}% "
                f"| score {before_txt} x{_EMA_DISTANCE_PENALTY_FACTOR}"
            )
        else:
            lines.append(f"  EMA distance={dist:.3f}% (ok, <= {thresh:.3f}%)")

    return lines


def breakdown_weighted_score(
    config: BotConfig,
    results: list[StrategyResult],
    *,
    include_rsi: bool = True,
    atr_factor: float = 1.0,
    entry_scoring: dict | None = None,
    weighted_score: float | None = None,
) -> dict:
    """Build per-strategy contributions and human-readable formula."""
    if include_rsi:
        pairs = [
            (results[0], config.donchian_weight),
            (results[1], config.supertrend_weight),
            (results[2], config.rsi_weight),
            (results[3], config.ema_weight),
        ]
        threshold = resolve_entry_threshold(config, atr_factor)
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
        threshold = resolve_trend_threshold(config, trend_weight)

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
        score = float(result.score)
        if key == "rsi" and entry_scoring and entry_scoring.get("rsi_score") is not None:
            score = float(entry_scoring["rsi_score"])
        if key in scores:
            scores[key] = score

        contrib = weight * score
        total += contrib
        label = _DISPLAY_NAMES.get(result.name, result.name)
        suffix = ""
        if key == "rsi" and entry_scoring and entry_scoring.get("rsi_score") is not None:
            if score != float(result.score):
                suffix = " [RSI động]"
        parts.append(f"{weight:.2f}*{score:+.2f} [{label}{suffix}]")

    if include_rsi and entry_scoring and entry_scoring.get("ema_distance_penalty"):
        total *= _EMA_DISTANCE_PENALTY_FACTOR
        parts.append(f"* {_EMA_DISTANCE_PENALTY_FACTOR:.1f} [EMA distance]")

    if include_rsi and atr_factor != 1.0:
        total *= atr_factor
        parts.append(f"* {atr_factor:.1f} [ATR dampen]")

    if weighted_score is not None:
        weighted = normalize_score(weighted_score)
    else:
        weighted = normalize_score(total)
    formula = " + ".join(parts) + f" = {weighted:+.4f}"

    return {
        **scores,
        "weighted_score": weighted,
        "threshold": threshold,
        "formula": formula,
        "atr_factor": atr_factor,
        "entry_scoring_monitor": format_entry_scoring_monitor(entry_scoring),
    }


def format_pnl(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}"

