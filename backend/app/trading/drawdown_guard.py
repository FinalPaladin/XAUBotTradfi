"""
Position loss guard — đóng toàn bộ khi một lệnh lỗ ≥ ngưỡng USD, chuyển SUPER_SAFE.

Thay thế drawdown % cũ (15% partial / 20% panic).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import BotConfig, TradePosition, TradingMode
from app.services.mt5_client import MT5Client
from app.trading.execution import OrderExecutor

logger = logging.getLogger(__name__)

POSITION_LOSS_CLOSE_ALL_USD = 16.0


@dataclass
class PositionLossStatus:
    worst_position_pnl: float
    account_balance: float
    action: str  # NONE | CLOSE_ALL_SUPER_SAFE


def _position_floating_pnl(
    position: TradePosition,
    mt5: MT5Client,
    current_price: float,
) -> float:
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
    return round(
        sum(_position_floating_pnl(p, mt5, current_price) for p in positions),
        2,
    )


def current_drawdown_percent(
    floating_loss_usd: float,
    account_balance: float,
) -> float:
    """Giữ cho tick summary — % lỗ thả nổi / balance."""
    if account_balance <= 0:
        return 0.0
    loss = abs(min(floating_loss_usd, 0.0))
    return round((loss / account_balance) * 100.0, 2)


def evaluate_position_loss_guard(
    positions: list[TradePosition],
    account_balance: float,
    mt5: MT5Client,
    current_price: float,
    *,
    loss_limit_usd: float = POSITION_LOSS_CLOSE_ALL_USD,
) -> PositionLossStatus:
    """Kích hoạt khi bất kỳ lệnh nào có floating loss ≤ -loss_limit_usd."""
    floating = compute_total_floating_pnl(positions, mt5, current_price)
    worst = 0.0
    if positions:
        worst = min(_position_floating_pnl(p, mt5, current_price) for p in positions)

    action = "NONE"
    if worst <= -loss_limit_usd:
        action = "CLOSE_ALL_SUPER_SAFE"

    return PositionLossStatus(
        worst_position_pnl=round(worst, 2),
        account_balance=account_balance,
        action=action,
    )


def close_all_and_enter_super_safe(
    bot: BotConfig,
    positions: list[TradePosition],
    executor: OrderExecutor,
    mt5: MT5Client,
    db: Session,
    *,
    reason: str = "POSITION_LOSS_16U",
) -> int:
    """Đóng toàn bộ vị thế, hủy pending, chuyển SUPER_SAFE (bot vẫn RUNNING)."""
    closed = executor.close_all_for_bot(bot, reason=reason)
    cancelled = mt5.cancel_pending_orders(bot.symbol, bot.magic_number)

    bot.trading_mode = TradingMode.SUPER_SAFE
    bot.trading_mode_manual = False
    db.flush()

    logger.warning(
        "Position loss guard bot=%s closed=%s cancelled=%s mode=SUPER_SAFE",
        bot.id,
        closed,
        cancelled,
    )
    return closed


# Backward-compatible aliases for orchestrator imports
evaluate_drawdown = evaluate_position_loss_guard
