"""Order execution and DB sync for positions."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import BotConfig, OrderSide, TradeHistory, TradePosition
from app.services.mt5_client import POSITION_NOT_FOUND, CloseFillResult, get_mt5_client, symbol_candidates
from app.trading.datetime_utils import coerce_utc, utc_now
from app.trading.types import OrderPlan

logger = logging.getLogger(__name__)


def _position_matches_bot_symbol(pos_symbol: str, bot_symbol: str) -> bool:
    """True when MT5 position symbol matches configured bot symbol (incl. aliases)."""
    normalized = pos_symbol.upper().replace("+", "").rstrip(".")
    for cand in symbol_candidates(bot_symbol):
        c = cand.upper().replace("+", "").rstrip(".")
        if normalized == c or normalized.startswith(c) or c.startswith(normalized):
            return True
    return False


class OrderExecutor:
    def __init__(
        self,
        db: Session,
        client=None,
        *,
        on_trade_closed: Callable[[TradeHistory], None] | None = None,
    ) -> None:
        self.db = db
        self._client = client or get_mt5_client()
        self._on_trade_closed = on_trade_closed

    def sync_positions_with_mt5(self, bot: BotConfig) -> dict[str, int]:
        """
        P0: Đồng bộ DB ↔ MT5 — reconcile lệnh đã đóng, import lệnh mồ côi trên MT5.
        """
        try:
            import MetaTrader5 as mt5
        except ImportError:
            return {"imported": 0, "reconciled": 0}

        mt5_positions = [
            p
            for p in self._client.positions_get(symbol=None, magic=bot.magic_number)
            if _position_matches_bot_symbol(p.symbol, bot.symbol)
        ]
        db_positions = (
            self.db.query(TradePosition)
            .filter(TradePosition.bot_id == bot.id)
            .all()
        )

        mt5_by_ticket = {str(p.ticket): p for p in mt5_positions}
        imported = 0
        reconciled = 0

        for pos in list(db_positions):
            if pos.ticket_id in mt5_by_ticket:
                continue
            ticket = int(pos.ticket_id)
            if self._client.position_is_open(ticket):
                logger.debug(
                    "MT5 sync skip ticket=%s — still open on MT5",
                    pos.ticket_id,
                )
                continue
            try:
                self._reconcile_stale_position(bot, pos, "MT5_SYNC_CLOSED")
                reconciled += 1
            except Exception:
                logger.exception("sync reconcile failed ticket=%s", pos.ticket_id)

        db_tickets = {
            p.ticket_id
            for p in self.db.query(TradePosition)
            .filter(TradePosition.bot_id == bot.id)
            .all()
        }

        for ticket, mp in mt5_by_ticket.items():
            if ticket in db_tickets:
                continue
            side = (
                OrderSide.BUY
                if mp.type == mt5.POSITION_TYPE_BUY
                else OrderSide.SELL
            )
            same_side_db = [
                p
                for p in self.db.query(TradePosition)
                .filter(
                    TradePosition.bot_id == bot.id,
                    TradePosition.side == side,
                )
                .all()
            ]
            same_side_mt5 = [
                p
                for p in mt5_by_ticket.values()
                if p.type
                == (
                    mt5.POSITION_TYPE_BUY
                    if side == OrderSide.BUY
                    else mt5.POSITION_TYPE_SELL
                )
            ]
            layer_index = len(same_side_db)
            if same_side_db:
                anchor = min(
                    p.basket_anchor_price or p.entry_price for p in same_side_db
                )
            elif same_side_mt5:
                anchor = min(p.price_open for p in same_side_mt5)
            else:
                anchor = mp.price_open

            entry_price = self._client.position_entry_price(int(ticket)) or mp.price_open
            pos = TradePosition(
                bot_id=bot.id,
                ticket_id=ticket,
                symbol=bot.symbol,
                side=side,
                volume=float(mp.volume),
                entry_price=float(entry_price),
                current_sl=float(mp.sl) if mp.sl else None,
                current_tp=float(mp.tp) if mp.tp else None,
                highest_price=float(entry_price) if side == OrderSide.BUY else None,
                lowest_price=float(entry_price) if side == OrderSide.SELL else None,
                layer_index=layer_index,
                basket_anchor_price=float(anchor),
                opened_at=utc_now(),
            )
            self.db.add(pos)
            imported += 1

        if imported or reconciled:
            self.db.flush()
        return {"imported": imported, "reconciled": reconciled}

    def strip_broker_tp(self, position: TradePosition) -> bool:
        """P1: Gỡ TP/SL broker trên lớp 1 khi basket đã multi-layer."""
        if position.current_tp is None and position.current_sl is None:
            return False
        ok, _ = self._client.position_modify(int(position.ticket_id), 0.0, 0.0)
        if ok:
            position.current_tp = None
            position.current_sl = None
            self.db.flush()
        return ok

    def _mt5_open_count(self, symbol: str, magic: int, side: OrderSide) -> int:
        """Count MT5 open positions for symbol/magic on one side."""
        try:
            import MetaTrader5 as mt5
        except ImportError:
            return 0
        positions = self._client.positions_get(symbol=symbol, magic=magic)
        if side == OrderSide.BUY:
            return sum(1 for p in positions if p.type == mt5.POSITION_TYPE_BUY)
        return sum(1 for p in positions if p.type == mt5.POSITION_TYPE_SELL)

    def _db_layer_count(self, bot_id: int, side: OrderSide, layer_index: int) -> int:
        return (
            self.db.query(TradePosition)
            .filter(
                TradePosition.bot_id == bot_id,
                TradePosition.side == side,
                TradePosition.layer_index == layer_index,
            )
            .count()
        )

    def open_position(self, bot: BotConfig, plan: OrderPlan) -> TradePosition | None:
        if plan.layer_index == 0:
            if self._db_layer_count(bot.id, plan.side, 0) > 0:
                logger.warning(
                    "Skip duplicate layer 0 %s — already in DB (bot=%s)",
                    plan.side.value,
                    bot.id,
                )
                return None
            if self._mt5_open_count(plan.symbol, plan.magic, plan.side) > 0:
                logger.warning(
                    "Skip duplicate layer 0 %s — MT5 already has open position (bot=%s)",
                    plan.side.value,
                    bot.id,
                )
                return None

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
            opened_at=utc_now(),
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

    def _sort_positions_for_close(
        self, positions: list[TradePosition]
    ) -> list[TradePosition]:
        return sorted(
            positions,
            key=lambda p: (getattr(p, "layer_index", 0) or 0, p.opened_at, p.ticket_id),
        )

    def _write_closed_history(
        self,
        bot: BotConfig,
        position: TradePosition,
        reason: str,
        entry_px: float,
        exit_px: float,
        pnl: float,
        *,
        closed_at: datetime | None = None,
    ) -> TradeHistory:
        existing = (
            self.db.query(TradeHistory)
            .filter(
                TradeHistory.bot_id == bot.id,
                TradeHistory.ticket_id == position.ticket_id,
            )
            .first()
        )
        if existing is not None:
            logger.warning(
                "History already exists ticket=%s — skipping duplicate write",
                position.ticket_id,
            )
            self.db.delete(position)
            self.db.flush()
            return existing

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
            opened_at=coerce_utc(position.opened_at),
            closed_at=closed_at or utc_now(),
        )
        self.db.add(history)
        self.db.delete(position)
        self.db.flush()
        self._emit_trade_closed(history)
        return history

    def _emit_trade_closed(self, history: TradeHistory) -> None:
        if self._on_trade_closed is None:
            return
        try:
            self._on_trade_closed(history)
        except Exception:
            logger.exception(
                "on_trade_closed callback failed ticket=%s",
                history.ticket_id,
            )

    def _finalize_close_from_fill(
        self,
        bot: BotConfig,
        position: TradePosition,
        reason: str,
        fill: CloseFillResult,
        exit_price: float | None = None,
        *,
        closed_at: datetime | None = None,
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
            bot,
            position,
            reason,
            entry_px,
            exit_px,
            pnl,
            closed_at=closed_at,
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
            raise RuntimeError(
                f"Cannot reconcile ticket={position.ticket_id}: still open on MT5"
            )

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
        histories = self._close_positions_batch(
            bot, [position], reason, exit_price=exit_price
        )
        if not histories:
            raise RuntimeError(f"close failed ticket={position.ticket_id}")
        return histories[0]

    def _close_positions_batch(
        self,
        bot: BotConfig,
        positions: list[TradePosition],
        reason: str,
        exit_price: float | None = None,
    ) -> list[TradeHistory]:
        if not positions:
            return []

        ordered = self._sort_positions_for_close(positions)
        tickets = [int(pos.ticket_id) for pos in ordered]
        fills = self._client.positions_close_batch(tickets)
        closed_at = utc_now()
        histories: list[TradeHistory] = []

        for pos in ordered:
            ticket = int(pos.ticket_id)
            try:
                fill = fills.get(ticket)
                if fill is None:
                    raise RuntimeError(f"no fill for ticket={ticket}")
                if not fill.ok:
                    if fill.error == POSITION_NOT_FOUND:
                        histories.append(
                            self._reconcile_stale_position(
                                bot, pos, reason, exit_price=exit_price
                            )
                        )
                    else:
                        raise RuntimeError(fill.error or "close failed")
                    continue

                histories.append(
                    self._finalize_close_from_fill(
                        bot,
                        pos,
                        reason,
                        fill,
                        exit_price=exit_price,
                        closed_at=closed_at,
                    )
                )
            except RuntimeError:
                raise
            except Exception:
                logger.exception("batch close failed ticket=%s", pos.ticket_id)
                continue

        return histories

    def close_basket(
        self,
        bot: BotConfig,
        positions: list[TradePosition],
        reason: str,
        exit_price: float | None = None,
    ) -> list[TradeHistory]:
        """
        Joint Close — gửi toàn bộ lệnh đóng MT5 trong một batch (cùng tick/symbol).

        Dùng cho Basket TP (+1..+3 USD) và Hard Stop (Black Swan 35 giá Vàng).
        """
        return self._close_positions_batch(
            bot, positions, reason, exit_price=exit_price
        )

    def close_all_for_bot(self, bot: BotConfig, reason: str = "STOP_ALL") -> int:
        positions = (
            self.db.query(TradePosition)
            .filter(TradePosition.bot_id == bot.id)
            .all()
        )
        return len(self._close_positions_batch(bot, positions, reason))

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
