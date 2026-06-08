"""Single tick: drawdown guard → multi-TF signal → basket DCA → execute."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import BotConfig, BotStatus, LogLevel, TradePosition
from app.services.logging_service import log_message
from app.services.mt5_client import get_mt5_client
from app.trading.basket_manager import (
    build_position_basket,
    evaluate_basket,
    should_add_dca_layer,
    should_open_initial_layer,
)
from app.trading.drawdown_guard import (
    evaluate_drawdown,
    panic_close_all,
    partial_close_worst_orders,
)
from app.trading.execution import OrderExecutor
from app.trading.market_data import MarketDataProvider
from app.trading.position_monitor import evaluate_position
from app.trading.risk import (
    build_layer_plan,
    build_order_plan,
    resolve_account_balance,
)
from app.trading.signal_engine import check_trend_and_entry_signal
from app.trading.signal_format import (
    allowed_nets_label,
    breakdown_weighted_score,
    format_pnl,
    net_signal_label,
)
from app.trading.types import BasketAction, PositionAction

logger = logging.getLogger(__name__)


def _build_tick_summary(
    bot: BotConfig,
    *,
    price: float,
    open_count: int,
    account_balance: float,
    drawdown_percent: float,
    floating_pnl: float,
    trend_signal,
    action: str | None = None,
) -> dict:
    meta = trend_signal.meta
    entry_bd = breakdown_weighted_score(
        bot,
        trend_signal.strategy_results,
        include_rsi=True,
        atr_factor=meta.get("atr_factor", 1.0),
    )
    return {
        "bot_id": bot.id,
        "price": round(price, 2),
        "open_count": open_count,
        "balance": round(account_balance, 2),
        "floating_pnl": format_pnl(floating_pnl),
        "drawdown_pct": drawdown_percent,
        "main_trend": trend_signal.main_trend.value,
        "trend_source": trend_signal.trend_source,
        "allowed": allowed_nets_label(meta.get("allowed_nets", [])),
        "h4_score": trend_signal.h4_score,
        "h1_score": trend_signal.h1_score,
        "h4_net": net_signal_label(meta.get("h4_net", 0)),
        "h1_net": net_signal_label(meta.get("h1_net", 0)),
        "entry_tf": trend_signal.entry_timeframe,
        "entry_score": trend_signal.entry_score,
        "entry_threshold": entry_bd["threshold"],
        "entry_net_raw": net_signal_label(meta.get("entry_net_raw", 0)),
        "net_signal": net_signal_label(trend_signal.net_signal),
        "donchian": entry_bd["donchian"],
        "supertrend": entry_bd["supertrend"],
        "rsi": entry_bd["rsi"],
        "ema21": entry_bd["ema21"],
        "atr_factor": entry_bd["atr_factor"],
        "formula": entry_bd["formula"],
        "action": action,
    }


class TradingOrchestrator:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._market = MarketDataProvider()
        self._executor = OrderExecutor(db)
        self._mt5 = get_mt5_client()

    def run_tick(self, bot: BotConfig) -> dict:
        if bot.status != BotStatus.RUNNING:
            return {"skipped": True, "reason": "not_running", "bot_id": bot.id}

        try:
            status = self._mt5.initialize()
            if not status.connected:
                log_message(
                    self.db,
                    status.error or "MT5 disconnected",
                    bot_id=bot.id,
                    level=LogLevel.ERROR,
                    source="mt5",
                )
                return {
                    "bot_id": bot.id,
                    "error": status.error or "MT5 disconnected",
                }

            account_balance = resolve_account_balance(self._mt5.account_equity())
            price = self._market.current_price(bot.symbol)
            open_positions = (
                self.db.query(TradePosition)
                .filter(TradePosition.bot_id == bot.id)
                .all()
            )
            open_count = len(open_positions)

            trend_signal = check_trend_and_entry_signal(bot, self._market)
            signal = trend_signal.as_aggregated()

            dd_status = evaluate_drawdown(
                open_positions, account_balance, self._mt5, price
            )

            def make_summary(action: str | None = None) -> dict:
                return _build_tick_summary(
                    bot,
                    price=price,
                    open_count=open_count,
                    account_balance=account_balance,
                    drawdown_percent=dd_status.drawdown_percent,
                    floating_pnl=dd_status.floating_loss_usd,
                    trend_signal=trend_signal,
                    action=action,
                )

            if dd_status.action == "PANIC_CLOSE":
                closed = panic_close_all(
                    bot, open_positions, self._executor, self._mt5, self.db
                )
                log_message(
                    self.db,
                    f"PANIC CLOSE: DD={dd_status.drawdown_percent}% "
                    f"closed={closed} bot STOPPED",
                    bot_id=bot.id,
                    level=LogLevel.ERROR,
                    source="drawdown_guard",
                )
                self.db.commit()
                return {
                    "summary": make_summary(
                        action=f"PANIC CLOSE — đóng {closed} lệnh, bot STOPPED"
                    )
                }

            if dd_status.action == "PARTIAL_CLOSE":
                n = partial_close_worst_orders(
                    bot, open_positions, self._executor, self._mt5, price
                )
                if n:
                    log_message(
                        self.db,
                        f"DD partial close: DD={dd_status.drawdown_percent}% "
                        f"closed_worst={n}",
                        bot_id=bot.id,
                        level=LogLevel.WARNING,
                        source="drawdown_guard",
                    )
                    self.db.commit()
                    return {
                        "summary": make_summary(
                            action=f"DD PARTIAL — đóng {n} lệnh lỗ nặng nhất"
                        )
                    }

            basket = build_position_basket(open_positions)

            if basket is not None:
                decision = evaluate_basket(
                    bot, basket, price, signal, account_balance
                )

                if decision.action != BasketAction.HOLD:
                    reason = decision.close_reason or decision.action.value
                    self._executor.close_basket(bot, open_positions, reason)
                    pnl = decision.meta.get("net_pnl_usd")
                    log_message(
                        self.db,
                        f"Joint close {basket.layer_count} layers reason={reason} "
                        f"pnl={pnl} USD",
                        bot_id=bot.id,
                        source="execution",
                    )
                    self.db.commit()
                    return {
                        "summary": make_summary(
                            action=(
                                f"JOINT CLOSE {basket.layer_count} lớp — "
                                f"{reason} P&L={pnl} USD"
                            )
                        )
                    }

                for pos in open_positions:
                    pos_decision = evaluate_position(bot, pos, price, signal)
                    if pos_decision.action != PositionAction.HOLD:
                        self._apply_decision(bot, pos, pos_decision, price)
                        self.db.commit()
                        return {
                            "summary": make_summary(
                                action=f"CLOSE ticket={pos.ticket_id}"
                            )
                        }

                max_layers = bot.max_layers or bot.max_open_positions
                if should_add_dca_layer(bot, basket, price) and basket.layer_count < max_layers:
                    next_layer = basket.layer_count
                    plan = build_layer_plan(
                        bot,
                        basket.side,
                        price,
                        layer_index=next_layer,
                        basket_anchor_price=basket.anchor_price,
                        account_balance=account_balance,
                    )
                    action_msg = None
                    if plan:
                        self._executor.open_position(bot, plan)
                        log_message(
                            self.db,
                            f"DCA layer {next_layer + 1}/{max_layers} "
                            f"{plan.side.value} {plan.volume} @ {price}",
                            bot_id=bot.id,
                            source="execution",
                        )
                        action_msg = (
                            f"DCA lớp {next_layer + 1}/{max_layers} "
                            f"{plan.side.value} vol={plan.volume}"
                        )
                    self.db.commit()
                    return {"summary": make_summary(action=action_msg)}

                self.db.commit()
                return {"summary": make_summary()}

            action_msg = None
            if should_open_initial_layer(signal, open_count):
                plan = build_order_plan(
                    bot,
                    signal,
                    price,
                    equity=account_balance,
                )
                if plan:
                    self._executor.open_position(bot, plan)
                    log_message(
                        self.db,
                        f"Opened layer 1 {plan.side.value} {plan.volume} @ {price} "
                        f"(trend={trend_signal.main_trend.value}, "
                        f"entry_tf={trend_signal.entry_timeframe})",
                        bot_id=bot.id,
                        source="execution",
                    )
                    action_msg = (
                        f"MỞ LỚP 1 {plan.side.value} vol={plan.volume} @ {price:.2f}"
                    )

            self.db.commit()
            return {"summary": make_summary(action=action_msg)}

        except Exception as exc:
            logger.exception("run_tick failed bot_id=%s", bot.id)
            log_message(
                self.db,
                str(exc),
                bot_id=bot.id,
                level=LogLevel.ERROR,
                source="orchestrator",
            )
            self.db.commit()
            return {"bot_id": bot.id, "error": str(exc)}

    def _apply_decision(
        self,
        bot: BotConfig,
        position: TradePosition,
        decision,
        price: float,
    ) -> None:
        action = decision.action
        if action == PositionAction.HOLD:
            return
        if action == PositionAction.MODIFY_TRAIL and decision.new_sl is not None:
            self._executor.modify_sl_tp(position, decision.new_sl)
            return
        if action.value.startswith("CLOSE"):
            reason = decision.close_reason or action.value
            self._executor.close_position(bot, position, reason)
            log_message(
                self.db,
                f"Closed {position.ticket_id} reason={reason}",
                bot_id=bot.id,
                source="execution",
            )
