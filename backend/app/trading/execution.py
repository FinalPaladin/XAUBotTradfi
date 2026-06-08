"""Order execution and DB sync for positions."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import BotConfig, OrderSide, TradeHistory, TradePosition
from app.services.mt5_client import POSITION_NOT_FOUND, CloseFillResult, get_mt5_client
from app.trading.types import OrderPlan

logger = logging.getLogger(__name__)


class OrderExecutor:
    def __init__(self, db: Session, client=None) -> None:
        self.db = db
        self._client = client or get_mt5_client()

    def open_position(self, bot: BotConfig, plan: OrderPlan) -> TradePosition | None:
        sl = plan.sl_price if plan.use_broker_sl_tp and plan.sl_price else 0.0
        tp = plan.tp_price if plan.use_broker_sl_tp and plan.tp_price else 0.0

        ok, err, ticket = self._client.order_send_market(
            plan.symbol,
            plan.side.value,
            plan.volume,
            sl,
            tp,
            plan.magic,
            plan.comment,
        )
        if not ok:
            raise RuntimeError(err or "order_send failed")

        ticket_id = self._resolve_position_ticket(plan.symbol, plan.magic, ticket)
        entry_price = self._client.position_entry_price(ticket_id) or plan.entry_price
        pos = TradePosition(
            bot_id=bot.id,
            ticket_id=str(ticket_id),
            symbol=plan.symbol,
            side=plan.side,
            volume=plan.volume,
            entry_price=entry_price,
            current_sl=plan.sl_price if plan.use_broker_sl_tp else None,
            current_tp=plan.tp_price if plan.use_broker_sl_tp else None,
            highest_price=entry_price if plan.side == OrderSide.BUY else None,
            lowest_price=entry_price if plan.side == OrderSide.SELL else None,
            layer_index=plan.layer_index,
            basket_anchor_price=plan.basket_anchor_price or entry_price,
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

    def _estimate_pnl(
        self,
        position: TradePosition,
        entry_px: float,
        exit_px: float,
    ) -> float:
        if position.side == OrderSide.BUY:
            return round((exit_px - entry_px) * position.volume * 100, 2)
        return round((entry_px - exit_px) * position.volume * 100, 2)

    def _write_closed_history(
        self,
        bot: BotConfig,
        position: TradePosition,
        reason: str,
        entry_px: float,
        exit_px: float,
        pnl: float,
    ) -> TradeHistory:
        history = TradeHistory(
            bot_id=bot.id,
            ticket_id=position.ticket_id,
            symbol=position.symbol,
            side=position.side,
            volume=position.volume,
            entry_price=round(entry_px, 3),
            exit_price=round(exit_px, 3),
            profit_loss=pnl,
            close_reason=reason,
            opened_at=position.opened_at,
            closed_at=datetime.now(timezone.utc),
        )
        self.db.add(history)
        self.db.delete(position)
        self.db.flush()
        return history

    def _finalize_close_from_fill(
        self,
        bot: BotConfig,
        position: TradePosition,
        reason: str,
        fill: CloseFillResult,
        exit_price: float | None = None,
    ) -> TradeHistory:
        entry_px = fill.entry_price or position.entry_price
        exit_px = fill.fill_price or exit_price or entry_px

        if fill.net_pnl is not None:
            pnl = round(fill.net_pnl, 2)
        else:
            logger.warning(
                "MT5 deal P&L unavailable ticket=%s — fallback formula",
                position.ticket_id,
            )
            pnl = self._estimate_pnl(position, entry_px, exit_px)

        return self._write_closed_history(
            bot, position, reason, entry_px, exit_px, pnl
        )

    def _reconcile_stale_position(
        self,
        bot: BotConfig,
        position: TradePosition,
        reason: str,
        exit_price: float | None = None,
    ) -> TradeHistory:
        """Remove DB row when MT5 no longer has the position (manual close on terminal)."""
        ticket = int(position.ticket_id)
        if self._client.position_is_open(ticket):
            raise RuntimeError(POSITION_NOT_FOUND)

        logger.warning(
            "MT5 ticket=%s already closed — reconciling DB (reason=%s)",
            position.ticket_id,
            reason,
        )

        entry_px = position.entry_price
        hist_exit, hist_pnl = self._client.position_exit_from_history(ticket)
        exit_px = hist_exit or exit_price or entry_px
        if hist_pnl is not None:
            pnl = round(hist_pnl, 2)
        else:
            pnl = self._estimate_pnl(position, entry_px, exit_px)

        return self._write_closed_history(
            bot, position, reason, entry_px, exit_px, pnl
        )

    def close_position(
        self,
        bot: BotConfig,
        position: TradePosition,
        reason: str,
        exit_price: float | None = None,
    ) -> TradeHistory:
        fill = self._client.position_close(int(position.ticket_id))
        if not fill.ok:
            if fill.error == POSITION_NOT_FOUND:
                return self._reconcile_stale_position(
                    bot, position, reason, exit_price=exit_price
                )
            raise RuntimeError(fill.error or "close failed")

        return self._finalize_close_from_fill(
            bot, position, reason, fill, exit_price=exit_price
        )

    def close_basket(
        self,
        bot: BotConfig,
        positions: list[TradePosition],
        reason: str,
        exit_price: float | None = None,
    ) -> list[TradeHistory]:
        """
        Joint Close — đóng TOÀN BỘ lớp lệnh trong basket cùng một tick.

        Dùng cho Basket TP (+1..+3 USD) và Hard Stop (Black Swan 35 giá Vàng).
        """
        histories: list[TradeHistory] = []
        for pos in positions:
            try:
                histories.append(
                    self.close_position(bot, pos, reason, exit_price=exit_price)
                )
            except Exception:
                continue
        return histories

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
