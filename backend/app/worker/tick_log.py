"""Compact worker tick log formatting."""

from __future__ import annotations


def format_tick_log(result: dict) -> str:
    if result.get("skipped"):
        return f"bot_id={result.get('bot_id')} skipped ({result.get('reason')})"

    if result.get("error"):
        return f"bot_id={result.get('bot_id')} ERROR: {result['error']}"

    s = result.get("summary")
    if not s:
        return f"bot_id={result.get('bot_id')} (no summary)"

    lines = [
        (
            f"bot_id={s['bot_id']} | price={s['price']:.2f} | "
            f"open={s['open_count']} | floating_pnl={s['floating_pnl']} USD | "
            f"DD={s['drawdown_pct']:.1f}% | balance={s['balance']:.0f}"
        ),
        (
            f"  trend={s['main_trend']} ({s['trend_source']}) | "
            f"allowed={s['allowed']} | "
            f"H1 score={s['h1_score']:+.2f} net={s['h1_net']}"
        ),
        (
            f"  entry {s['entry_tf']} | net_signal={s['net_signal']} "
            f"(raw={s['entry_net_raw']}) | score={s['entry_score']:+.2f} "
            f"(need >={s['entry_threshold']:.2f} LONG / "
            f"<={-s['entry_threshold']:.2f} SHORT)"
        ),
        (
            f"  Donchian={s['donchian']:+.2f} | "
            f"SuperTrend={s['supertrend']:+.2f} | "
            f"RSI={s['rsi']:+.2f} | "
            f"EMA21={s['ema21']:+.2f}"
        ),
        f"  formula: {s['formula']}",
    ]

    for line in s.get("entry_scoring_monitor") or []:
        lines.append(line)

    filter_log = s.get("filter_log")
    if filter_log:
        lines.append(f"  filter: {filter_log}")

    if s.get("is_scalp_mode"):
        lines.append("  mode: SCALP (50% volume, 50% TP distance)")

    action = s.get("action")
    if action:
        lines.append(f"  >> {action}")

    return "\n".join(lines)
