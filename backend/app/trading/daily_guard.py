"""Daily PNL guard — profit lock; loss cap at 40% balance → DCA_FULL_STACK_LOSS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import OrderSide, TradeHistory, TradePosition
from app.trading.basket_manager import build_position_basket, calculate_net_pnl_usd
from app.trading.trading_mode import NORMAL_FULL_STACK_LOSS_PCT

DAILY_PROFIT_LOCK_USD = 30.0
DAILY_LOSS_CAP_PCT = NORMAL_FULL_STACK_LOSS_PCT  # 40% balance — cùng ngưỡng full-stack DCA


@dataclass
class DailyGuardStatus:
    realized_today: float
    floating_pnl: float
    total_day_pnl: float
    block_new_entries: bool
    trigger_dca_full_stack_loss: bool
    reason: str | None = None


def utc_day_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def get_today_realized_pnl(db: Session, bot_id: int) -> float:
    since = utc_day_start()
    total = (
        db.query(func.coalesce(func.sum(TradeHistory.profit_loss), 0.0))
        .filter(
            TradeHistory.bot_id == bot_id,
            TradeHistory.closed_at >= since,
        )
        .scalar()
    )
    return round(float(total or 0.0), 2)


def compute_floating_pnl(
    open_positions: list[TradePosition],
    current_price: float,
) -> float:
    if not open_positions:
        return 0.0

    total = 0.0
    for side in (OrderSide.BUY, OrderSide.SELL):
        side_positions = [p for p in open_positions if p.side == side]
        if not side_positions:
            continue
        basket = build_position_basket(side_positions)
        if basket is None:
            continue
        total += calculate_net_pnl_usd(basket, current_price)
    return round(total, 2)


def evaluate_daily_guard(
    db: Session,
    bot_id: int,
    open_positions: list[TradePosition],
    current_price: float,
    account_balance: float,
    *,
    profit_lock_usd: float = DAILY_PROFIT_LOCK_USD,
    loss_cap_pct: float = DAILY_LOSS_CAP_PCT,
) -> DailyGuardStatus:
    realized = get_today_realized_pnl(db, bot_id)
    floating = compute_floating_pnl(open_positions, current_price)
    total = round(realized + floating, 2)

    balance = account_balance if account_balance > 0 else 200.0
    loss_limit = round(balance * loss_cap_pct / 100.0, 2)
    trigger_loss = total <= -loss_limit

    block_new = total >= profit_lock_usd

    reason: str | None = None
    if trigger_loss:
        reason = (
            f"DAILY_LOSS_CAP total={total:.2f} USD "
            f"≤ -{loss_limit:.2f} ({loss_cap_pct}% balance) → DCA_FULL_STACK_LOSS"
        )
    elif block_new:
        reason = (
            f"DAILY_PROFIT_LOCK total={total:.2f} USD "
            f"(realized={realized:.2f}, floating={floating:.2f})"
        )

    return DailyGuardStatus(
        realized_today=realized,
        floating_pnl=floating,
        total_day_pnl=total,
        block_new_entries=block_new,
        trigger_dca_full_stack_loss=trigger_loss,
        reason=reason,
    )
