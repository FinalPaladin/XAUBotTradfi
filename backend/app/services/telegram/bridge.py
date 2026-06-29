"""Map trading domain objects → Telegram alerts (orchestrator / execution hooks)."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from app.models import OrderSide, TradeHistory, TradePosition
from app.services.telegram.notifier import TradeAlertNotifier
from app.services.telegram.types import (
    CloseTradeAlert,
    OpenTradeAlert,
    TradeDirection,
    TradeOutcome,
)
from app.trading.risk import resolve_account_balance
from app.trading.signal_format import format_entry_scoring_monitor
from app.trading.types import OrderPlan

if TYPE_CHECKING:
    from app.trading.signal_engine import TrendEntrySignal

logger = logging.getLogger(__name__)

_STRATEGY_LABELS = {
    "donchian": "Donchian",
    "supertrend": "SuperTrend",
    "rsi": "RSI",
    "rsi_divergence": "RSI Divergence",
    "ema21": "EMA21",
}

_CLOSE_REASON_LABELS: dict[str, str] = {
    "SCALP_TP": "Chạm TP scalp",
    "BASKET_TP": "Chạm Basket TP",
    "CLOSE_TP": "Chạm Take Profit",
    "CLOSE_SL": "Chạm Stop Loss",
    "CLOSE_TRAIL": "Quét Trailing Stop",
    "CLOSE_SIGNAL": "Tín hiệu đảo chiều",
    "CLOSE_STOP_ALL": "Stop all",
    "CLOSE_BASKET_TP": "Chạm Basket TP",
    "CLOSE_SINGLE_SCALP": "Đóng scalp đơn",
    "CLOSE_DCA_LAYER_TP": "Chạm TP lớp DCA",
    "CLOSE_HARD_STOP": "Hard stop (Black Swan)",
    "CLOSE_TREND_FLIP": "Đảo trend H1",
    "CLOSE_M5_REVERSAL": "M5 reversal",
    "CLOSE_MAX_USD_LOSS": "Vượt ngưỡng lỗ USD",
    "CLOSE_MAX_PCT_LOSS": "Vượt ngưỡng lỗ %",
    "CORE_BASKET_TP": "Core gồng — 3 lớp đầu chạm TP",
    "DCA_FULL_STACK_LOSS": "Tổng lỗ basket ≥ % balance — cắt hết",
    "SATELLITE_LAYER_TP": "DCA vệ tinh — chốt lẻ có lời",
    "CLOSE_ATR_STOP": "ATR stop",
    "CLOSE_TIME_STOP": "Time stop",
    "CLOSE_MAX_AGE": "Quá thời gian giữ lệnh",
    "CLOSE_BASKET_TRAIL": "Basket trailing stop",
    "CLOSE_PANIC_SIGNAL": "Panic signal M5",
    "POSITION_LOSS_16U": "Position loss guard 16U",
    "PANIC SIGNAL": "Panic signal — đóng toàn bộ",
    "MT5_SYNC_CLOSED": "Đã đóng trên MT5 (sync)",
    "STOP_ALL": "Stop all",
}


def order_side_to_direction(side: OrderSide) -> TradeDirection:
    return TradeDirection.LONG if side == OrderSide.BUY else TradeDirection.SHORT


def humanize_close_reason(reason: str | None) -> str:
    if not reason:
        return "Đóng lệnh"
    key = reason.strip()
    if key in _CLOSE_REASON_LABELS:
        return _CLOSE_REASON_LABELS[key]
    for code, label in _CLOSE_REASON_LABELS.items():
        if code in key:
            return label
    return key


_AI_WIN_IN_FILTER = re.compile(
    r"\s*\|\s*\[AI FILTER\]\s*Win probability\s+[\d.]+%",
    re.IGNORECASE,
)


def _strip_ai_win_from_filter_log(filter_log: str) -> str:
    return _AI_WIN_IN_FILTER.sub("", filter_log).strip()


def build_entry_reason_lines(
    trend_signal: TrendEntrySignal,
    *,
    extra: str | None = None,
) -> tuple[list[str], float | None]:
    bullets: list[str] = []
    win_prob = trend_signal.meta.get("ai_win_probability")
    ai_threshold = trend_signal.meta.get("ai_filter_threshold")

    filter_log = trend_signal.meta.get("filter_log", "")
    if filter_log:
        cleaned = _strip_ai_win_from_filter_log(str(filter_log))
        for part in cleaned.split(" | "):
            part = part.strip()
            if part:
                bullets.append(part)

    if win_prob is not None:
        threshold_val = ai_threshold if ai_threshold is not None else 55.0
        status = "PASS" if win_prob >= threshold_val else "BLOCKED"
        bullets.append(f"AI filter: {status} (ngưỡng ≥{threshold_val:.0f}%)")

    for monitor_line in format_entry_scoring_monitor(
        trend_signal.meta.get("entry_scoring")
    ):
        bullets.append(monitor_line.strip())

    for result in trend_signal.strategy_results:
        label = _STRATEGY_LABELS.get(result.name, result.name)
        bullets.append(f"{label}: {result.score:+.2f}")

    if extra:
        bullets.append(extra)

    if not bullets:
        bullets.append("Tín hiệu entry từ bot")
    return bullets, win_prob


def _price_pnl_percent(side: OrderSide, entry: float, exit_px: float) -> float:
    if entry <= 0:
        return 0.0
    if side == OrderSide.BUY:
        return round((exit_px - entry) / entry * 100.0, 2)
    return round((entry - exit_px) / entry * 100.0, 2)


def history_to_close_alert(history: TradeHistory) -> CloseTradeAlert:
    pnl = float(history.profit_loss)
    balance = resolve_account_balance()
    return CloseTradeAlert(
        symbol=history.symbol,
        direction=order_side_to_direction(history.side),
        outcome=TradeOutcome.WIN if pnl >= 0 else TradeOutcome.LOSS,
        pnl_amount=pnl,
        pnl_percent=_price_pnl_percent(
            history.side, history.entry_price, history.exit_price
        ),
        entry=history.entry_price,
        close_price=history.exit_price,
        ticket_id=history.ticket_id,
        account_balance=balance if balance > 0 else None,
        reason=humanize_close_reason(history.close_reason),
    )


def plan_and_position_to_open_alert(
    plan: OrderPlan,
    position: TradePosition,
    trend_signal: TrendEntrySignal,
    *,
    extra: str | None = None,
) -> OpenTradeAlert:
    reason_lines, win_probability = build_entry_reason_lines(
        trend_signal, extra=extra
    )
    return OpenTradeAlert(
        symbol=position.symbol,
        direction=order_side_to_direction(plan.side),
        entry=position.entry_price,
        sl=position.current_sl,
        tp=position.current_tp,
        ticket_id=position.ticket_id,
        reason_lines=tuple(reason_lines),
        win_probability=win_probability,
    )


def _safe_send(notifier: TradeAlertNotifier, send: Callable[[], object]) -> None:
    try:
        result = send()
        if hasattr(result, "ok") and not result.ok:
            logger.warning("Telegram alert failed: %s", getattr(result, "error", result))
    except Exception:
        logger.exception("Telegram alert error")


def notify_trade_opened(
    notifier: TradeAlertNotifier,
    plan: OrderPlan,
    position: TradePosition,
    trend_signal: TrendEntrySignal,
    *,
    extra: str | None = None,
) -> None:
    alert = plan_and_position_to_open_alert(
        plan, position, trend_signal, extra=extra
    )
    _safe_send(notifier, lambda: notifier.notify_open_trade(alert))


def notify_trade_closed(
    notifier: TradeAlertNotifier,
    history: TradeHistory,
) -> None:
    alert = history_to_close_alert(history)
    _safe_send(notifier, lambda: notifier.notify_close_trade(alert))
