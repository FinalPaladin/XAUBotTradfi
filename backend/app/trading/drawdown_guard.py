"""
Kiểm soát sụt giảm tài khoản khẩn cấp (Drawdown Emergency Control).

Mốc 1 (DD > 40%): partial_close_worst_orders — đóng lệnh lỗ nặng nhất.
Mốc 2 (DD > 60%): panic_close_all — đóng toàn bộ, hủy lệnh chờ, dừng bot.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import BotConfig, BotStatus, TradePosition
from app.services.mt5_client import MT5Client
from app.trading.execution import OrderExecutor

logger = logging.getLogger(__name__)

DD_PARTIAL_THRESHOLD_PCT = 40.0
DD_PANIC_THRESHOLD_PCT = 60.0


@dataclass
class DrawdownStatus:
    """Trạng thái drawdown hiện tại của bot."""

    floating_loss_usd: float
    account_balance: float
    drawdown_percent: float
    action: str  # NONE | PARTIAL_CLOSE | PANIC_CLOSE


def current_drawdown_percent(
    floating_loss_usd: float,
    account_balance: float,
) -> float:
    """
    Tỷ lệ sụt giảm = |tổng lỗ thả nổi| / số dư tài khoản × 100.

    Chỉ tính phần lỗ (floating_loss <= 0); lãi thả nổi → DD = 0%.
    """
    if account_balance <= 0:
        return 0.0
    loss = abs(min(floating_loss_usd, 0.0))
    return round((loss / account_balance) * 100.0, 2)


def _position_floating_pnl(
    position: TradePosition,
    mt5: MT5Client,
    current_price: float,
) -> float:
    """Lấy P&L thả nổi từ MT5; fallback công thức XAUUSD."""
    live = mt5.position_live(int(position.ticket_id))
    if live is not None:
        return float(live["profit"]) + float(live.get("swap", 0.0))

    from app.models import OrderSide

    if position.side == OrderSide.BUY:
        return (current_price - position.entry_price) * position.volume * 100
    return (position.entry_price - current_price) * position.volume * 100


def compute_total_floating_pnl(
    positions: list[TradePosition],
    mt5: MT5Client,
    current_price: float,
) -> float:
    """Tổng P&L chưa thực hiện của tất cả vị thế bot."""
    return round(
        sum(_position_floating_pnl(p, mt5, current_price) for p in positions),
        2,
    )


def evaluate_drawdown(
    positions: list[TradePosition],
    account_balance: float,
    mt5: MT5Client,
    current_price: float,
) -> DrawdownStatus:
    """Đánh giá mức drawdown và quyết định hành động khẩn cấp."""
    floating = compute_total_floating_pnl(positions, mt5, current_price)
    dd_pct = current_drawdown_percent(floating, account_balance)

    action = "NONE"
    if dd_pct >= DD_PANIC_THRESHOLD_PCT:
        action = "PANIC_CLOSE"
    elif dd_pct >= DD_PARTIAL_THRESHOLD_PCT:
        action = "PARTIAL_CLOSE"

    return DrawdownStatus(
        floating_loss_usd=floating,
        account_balance=account_balance,
        drawdown_percent=dd_pct,
        action=action,
    )


def partial_close_worst_orders(
    bot: BotConfig,
    positions: list[TradePosition],
    executor: OrderExecutor,
    mt5: MT5Client,
    current_price: float,
) -> int:
    """
    Đóng lệnh có floating loss lớn nhất để giải phóng margin.

    Gọi mỗi tick khi DD > 40%; lặp qua các tick tiếp theo cho đến khi DD hạ xuống.
    """
    if not positions:
        return 0

    ranked = sorted(
        positions,
        key=lambda p: _position_floating_pnl(p, mt5, current_price),
    )
    worst = ranked[0]
    worst_pnl = _position_floating_pnl(worst, mt5, current_price)

    if worst_pnl >= 0:
        return 0

    try:
        executor.close_position(bot, worst, "DD_PARTIAL_CLOSE")
        logger.warning(
            "DD partial close bot=%s ticket=%s pnl=%.2f",
            bot.id,
            worst.ticket_id,
            worst_pnl,
        )
        return 1
    except Exception:
        logger.exception("partial_close failed ticket=%s", worst.ticket_id)
        return 0


def panic_close_all(
    bot: BotConfig,
    positions: list[TradePosition],
    executor: OrderExecutor,
    mt5: MT5Client,
    db: Session,
) -> int:
    """
    Hard cut — đóng toàn bộ vị thế, hủy lệnh chờ, dừng bot (giữ ~40% vốn).

    Kích hoạt khi drawdown vượt 60%.
    """
    closed = executor.close_all_for_bot(bot, reason="PANIC_DD")
    cancelled = mt5.cancel_pending_orders(bot.symbol, bot.magic_number)

    bot.status = BotStatus.STOPPED
    db.flush()

    logger.critical(
        "PANIC CLOSE bot=%s closed=%s cancelled_pending=%s status=STOPPED",
        bot.id,
        closed,
        cancelled,
    )
    return closed
