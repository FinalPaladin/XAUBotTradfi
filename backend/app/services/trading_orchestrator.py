"""Single tick: position loss guard → multi-TF signal → basket DCA → execute."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import BotConfig, BotStatus, LogLevel, OrderSide, TradePosition
from app.services.logging_service import log_message
from app.services.mt5_client import get_mt5_client
from app.trading.basket_manager import (
    BasketContext,
    build_position_basket,
    calculate_net_pnl_usd,
    effective_max_layers,
    evaluate_basket,
    should_add_dca_layer,
    should_open_initial_layer,
    should_open_reversal_hedge_layer,
    update_basket_peak_pnl,
)
from app.trading.daily_guard import evaluate_daily_guard
from app.trading.drawdown_guard import (
    close_all_and_enter_super_safe,
    compute_total_floating_pnl,
    current_drawdown_percent,
    evaluate_position_loss_guard,
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
        "trading_mode": getattr(bot.trading_mode, "value", bot.trading_mode),
        "price": round(price, 2),
        "open_count": open_count,
        "balance": round(account_balance, 2),
        "floating_pnl": format_pnl(floating_pnl),
        "drawdown_pct": drawdown_percent,
        "main_trend": trend_signal.main_trend.value,
        "trend_source": trend_signal.trend_source,
        "allowed": allowed_nets_label(meta.get("allowed_nets", [])),
        "h1_score": trend_signal.h1_score,
        "h1_net": net_signal_label(meta.get("h1_net", 0)),
        "is_scalp_mode": trend_signal.is_scalp_mode,
        "filter_log": meta.get("filter_log", ""),
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

            sync_stats = self._executor.sync_positions_with_mt5(bot)
            if sync_stats["imported"] or sync_stats["reconciled"]:
                log_message(
                    self.db,
                    f"MT5 sync: imported={sync_stats['imported']} "
                    f"reconciled={sync_stats['reconciled']}",
                    bot_id=bot.id,
                    source="execution",
                )

            open_positions = (
                self.db.query(TradePosition)
                .filter(TradePosition.bot_id == bot.id)
                .all()
            )
            open_count = len(open_positions)

            trend_signal = check_trend_and_entry_signal(bot, self._market)
            signal = trend_signal.as_aggregated()

            floating_pnl = compute_total_floating_pnl(
                open_positions, self._mt5, price
            )
            dd_pct = current_drawdown_percent(floating_pnl, account_balance)

            loss_guard = evaluate_position_loss_guard(
                open_positions, account_balance, self._mt5, price
            )

            def make_summary(action: str | None = None) -> dict:
                return _build_tick_summary(
                    bot,
                    price=price,
                    open_count=open_count,
                    account_balance=account_balance,
                    drawdown_percent=dd_pct,
                    floating_pnl=floating_pnl,
                    trend_signal=trend_signal,
                    action=action,
                )

            if loss_guard.action == "CLOSE_ALL_SUPER_SAFE":
                closed = close_all_and_enter_super_safe(
                    bot,
                    open_positions,
                    self._executor,
                    self._mt5,
                    self.db,
                )
                log_message(
                    self.db,
                    f"POSITION LOSS 16U: worst={loss_guard.worst_position_pnl} "
                    f"closed={closed} → SUPER_SAFE",
                    bot_id=bot.id,
                    level=LogLevel.WARNING,
                    source="position_loss_guard",
                )
                self.db.commit()
                return {
                    "summary": make_summary(
                        action=(
                            f"LOSS GUARD 16U — đóng {closed} lệnh, "
                            f"chuyển SUPER_SAFE"
                        )
                    )
                }

            daily_guard = evaluate_daily_guard(
                self.db, bot.id, open_positions, price, account_balance
            )
            if daily_guard.trigger_dca_full_stack_loss:
                closed = close_all_and_enter_super_safe(
                    bot,
                    open_positions,
                    self._executor,
                    self._mt5,
                    self.db,
                    reason="DCA_FULL_STACK_LOSS",
                )
                log_message(
                    self.db,
                    f"DAILY LOSS CAP: {daily_guard.reason} closed={closed}",
                    bot_id=bot.id,
                    level=LogLevel.WARNING,
                    source="daily_guard",
                )
                self.db.commit()
                return {
                    "summary": make_summary(
                        action=(
                            f"DAILY LOSS 40% — đóng {closed} lệnh, "
                            f"chuyển SUPER_SAFE"
                        )
                    )
                }

            block_new_entries = daily_guard.block_new_entries
            if block_new_entries and daily_guard.reason:
                logger.info(
                    "bot_id=%s daily guard: %s (manage only)",
                    bot.id,
                    daily_guard.reason,
                )

            atr_meta = trend_signal.meta.get("atr") or {}
            atr_value = atr_meta.get("current_atr")
            if atr_value is not None:
                atr_value = float(atr_value)

            basket_ctx = BasketContext(
                main_trend=trend_signal.main_trend,
                entry_net_raw=int(trend_signal.meta.get("entry_net_raw", 0)),
                entry_score=trend_signal.entry_score,
                is_scalp_mode=trend_signal.is_scalp_mode,
                atr_value=atr_value,
            )

            for side in (OrderSide.BUY, OrderSide.SELL):
                side_positions = [p for p in open_positions if p.side == side]
                if not side_positions:
                    continue

                basket = build_position_basket(side_positions)
                if basket is None:
                    continue

                if basket.is_multi_layer:
                    for pos in side_positions:
                        if (getattr(pos, "layer_index", 0) or 0) == 0:
                            if pos.current_tp is not None:
                                self._executor.strip_broker_tp(pos)

                net_pnl = calculate_net_pnl_usd(basket, price)
                anchor_pos = next(
                    (
                        p
                        for p in side_positions
                        if (getattr(p, "layer_index", 0) or 0) == 0
                    ),
                    side_positions[0],
                )
                basket_peak_pnl = update_basket_peak_pnl(anchor_pos, net_pnl)

                decision = evaluate_basket(
                    bot,
                    basket,
                    price,
                    signal,
                    account_balance,
                    ctx=basket_ctx,
                    basket_peak_pnl=basket_peak_pnl,
                )

                if decision.action != BasketAction.HOLD:
                    reason = decision.close_reason or decision.action.value
                    pnl = decision.meta.get("net_pnl_usd")
                    if decision.action == BasketAction.CLOSE_PANIC_SIGNAL:
                        closed = self._executor.close_all_for_bot(
                            bot, reason=reason
                        )
                        log_message(
                            self.db,
                            f"PANIC SIGNAL close all — score={basket_ctx.entry_score:+.2f} "
                            f"closed={closed} pnl={pnl} USD",
                            bot_id=bot.id,
                            level=LogLevel.WARNING,
                            source="execution",
                        )
                        action_label = (
                            f"PANIC SIGNAL — đóng {closed} lệnh "
                            f"(M5={basket_ctx.entry_score:+.2f}) P&L={pnl} USD"
                        )
                    else:
                        self._executor.close_basket(bot, side_positions, reason)
                        log_message(
                            self.db,
                            f"Joint close {basket.layer_count} {side.value} layers "
                            f"reason={reason} pnl={pnl} USD",
                            bot_id=bot.id,
                            source="execution",
                        )
                        action_label = (
                            f"JOINT CLOSE {basket.layer_count} {side.value} — "
                            f"{reason} P&L={pnl} USD"
                        )
                    self.db.commit()
                    return {"summary": make_summary(action=action_label)}

                for pos in side_positions:
                    pos_decision = evaluate_position(
                        bot,
                        pos,
                        price,
                        signal,
                        account_balance=account_balance,
                        basket_is_multi_layer=basket.is_multi_layer,
                    )
                    if pos_decision.action != PositionAction.HOLD:
                        self._apply_decision(bot, pos, pos_decision, price)
                        self.db.commit()
                        return {
                            "summary": make_summary(
                                action=f"CLOSE ticket={pos.ticket_id}"
                            )
                        }

                net_pnl = calculate_net_pnl_usd(basket, price)
                side_max_layers = effective_max_layers(bot, basket, basket_ctx)

                if (
                    not block_new_entries
                    and should_add_dca_layer(
                        bot,
                        basket,
                        price,
                        ctx=basket_ctx,
                        net_pnl_usd=net_pnl,
                        account_balance=account_balance,
                    )
                    and basket.layer_count < side_max_layers
                ):
                    next_layer = basket.layer_count
                    plan = build_layer_plan(
                        bot,
                        basket.side,
                        price,
                        layer_index=next_layer,
                        basket_anchor_price=basket.anchor_price,
                        account_balance=account_balance,
                        is_scalp_mode=basket_ctx.is_scalp_mode,
                    )
                    action_msg = None
                    if plan:
                        self._executor.open_position(bot, plan)
                        log_message(
                            self.db,
                            f"DCA layer {next_layer + 1}/{side_max_layers} "
                            f"{plan.side.value} {plan.volume} @ {price}",
                            bot_id=bot.id,
                            source="execution",
                        )
                        action_msg = (
                            f"DCA lớp {next_layer + 1}/{side_max_layers} "
                            f"{plan.side.value} vol={plan.volume}"
                        )
                    self.db.commit()
                    return {"summary": make_summary(action=action_msg)}

            action_msg = None
            if not block_new_entries and should_open_reversal_hedge_layer(
                signal,
                open_positions,
                is_scalp_mode=trend_signal.is_scalp_mode,
            ):
                plan = build_order_plan(
                    bot,
                    signal,
                    price,
                    equity=account_balance,
                )
                if plan:
                    self._executor.open_position(bot, plan)
                    filter_log = trend_signal.meta.get("filter_log", "")
                    log_message(
                        self.db,
                        f"Opened REVERSAL HEDGE {plan.side.value} {plan.volume} "
                        f"@ {price} (opposite basket active)",
                        bot_id=bot.id,
                        source="execution",
                    )
                    if filter_log:
                        log_message(
                            self.db,
                            filter_log,
                            bot_id=bot.id,
                            source="signal_engine",
                        )
                    action_msg = (
                        f"MỞ HEDGE {plan.side.value} vol={plan.volume} "
                        f"@ {price:.2f} REVERSAL"
                    )
                    self.db.commit()
                    return {"summary": make_summary(action=action_msg)}

            if not block_new_entries and should_open_initial_layer(signal, open_positions):
                fresh_positions = (
                    self.db.query(TradePosition)
                    .filter(TradePosition.bot_id == bot.id)
                    .all()
                )
                if not should_open_initial_layer(signal, fresh_positions):
                    self.db.commit()
                    return {"summary": make_summary(action=None)}

                plan = build_order_plan(
                    bot,
                    signal,
                    price,
                    equity=account_balance,
                )
                if plan:
                    opened = self._executor.open_position(bot, plan)
                    if opened is None:
                        self.db.commit()
                        return {
                            "summary": make_summary(
                                action="Bỏ qua mở lớp 1 — đã có lệnh cùng chiều"
                            )
                        }
                    scalp_tag = " SCALP_MODE" if trend_signal.is_scalp_mode else ""
                    filter_log = trend_signal.meta.get("filter_log", "")
                    log_message(
                        self.db,
                        f"Opened layer 1 {plan.side.value} {plan.volume} @ {price} "
                        f"(trend={trend_signal.main_trend.value}, "
                        f"entry_tf={trend_signal.entry_timeframe}{scalp_tag})",
                        bot_id=bot.id,
                        source="execution",
                    )
                    if filter_log:
                        log_message(
                            self.db,
                            filter_log,
                            bot_id=bot.id,
                            source="signal_engine",
                        )
                    action_msg = (
                        f"MỞ LỚP 1 {plan.side.value} vol={plan.volume} @ {price:.2f}"
                        f"{scalp_tag}"
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
