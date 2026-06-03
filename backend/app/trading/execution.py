"""Order execution and DB sync for positions."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import BotConfig, OrderSide, TradeHistory, TradePosition
from app.services.mt5_client import get_mt5_client
from app.trading.types import OrderPlan


class OrderExecutor:
    def __init__(self, db: Session, client=None) -> None:
        self.db = db
        self._client = client or get_mt5_client()

    def open_position(self, bot: BotConfig, plan: OrderPlan) -> TradePosition | None:
        ok, err, ticket = self._client.order_send_market(
            plan.symbol,
            plan.side.value,
            plan.volume,
            plan.sl_price,
            plan.tp_price,
            plan.magic,
            plan.comment,
        )
        if not ok:
            raise RuntimeError(err or "order_send failed")

        ticket_id = self._resolve_position_ticket(plan.symbol, plan.magic, ticket)
        pos = TradePosition(
            bot_id=bot.id,
            ticket_id=str(ticket_id),
            symbol=plan.symbol,
            side=plan.side,
            volume=plan.volume,
            entry_price=plan.entry_price,
            current_sl=plan.sl_price,
            current_tp=plan.tp_price,
            highest_price=plan.entry_price if plan.side == OrderSide.BUY else None,
            lowest_price=plan.entry_price if plan.side == OrderSide.SELL else None,
        )
        self.db.add(pos)
        self.db.flush()
        return pos

    def _resolve_position_ticket(
        self, symbol: str, magic: int, fallback: int | None
    ) -> int:
        positions = self._client.positions_get(symbol=symbol, magic=magic)
        if positions:
            return int(positions[-1].ticket)
        if fallback is not None:
            return int(fallback)
        raise RuntimeError("Could not resolve position ticket after open")

    def modify_sl_tp(
        self, position: TradePosition, sl: float, tp: float | None = None
    ) -> bool:
        tp = tp if tp is not None else (position.current_tp or 0.0)
        ok, err = self._client.position_modify(int(position.ticket_id), sl, tp)
        if ok:
            position.current_sl = sl
            if tp:
                position.current_tp = tp
            self.db.flush()
        return ok

    def close_position(
        self,
        bot: BotConfig,
        position: TradePosition,
        reason: str,
        exit_price: float | None = None,
    ) -> TradeHistory:
        ok, err, price = self._client.position_close(int(position.ticket_id))
        if not ok:
            raise RuntimeError(err or "close failed")

        exit_px = exit_price if exit_price is not None else (price or position.entry_price)
        if position.side == OrderSide.BUY:
            pnl = (exit_px - position.entry_price) * position.volume * 100
        else:
            pnl = (position.entry_price - exit_px) * position.volume * 100

        history = TradeHistory(
            bot_id=bot.id,
            ticket_id=position.ticket_id,
            symbol=position.symbol,
            side=position.side,
            volume=position.volume,
            entry_price=position.entry_price,
            exit_price=exit_px,
            profit_loss=pnl,
            close_reason=reason,
            opened_at=position.opened_at,
            closed_at=datetime.now(timezone.utc),
        )
        self.db.add(history)
        self.db.delete(position)
        self.db.flush()
        return history

    def close_all_for_bot(self, bot: BotConfig, reason: str = "STOP_ALL") -> int:
        positions = (
            self.db.query(TradePosition)
            .filter(TradePosition.bot_id == bot.id)
            .all()
        )
        closed = 0
        for pos in positions:
            try:
                self.close_position(bot, pos, reason)
                closed += 1
            except Exception:
                continue
        return closed

    def close_all_bots(self, reason: str = "STOP_ALL") -> int:
        bots = self.db.query(BotConfig).all()
        total = 0
        for bot in bots:
            total += self.close_all_for_bot(bot, reason)
        return total

    def sync_open_count(self, bot: BotConfig) -> int:
        return (
            self.db.query(TradePosition)
            .filter(TradePosition.bot_id == bot.id)
            .count()
        )
