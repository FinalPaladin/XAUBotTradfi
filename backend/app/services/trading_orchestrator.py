"""Single tick: market data → signals → monitor → execute."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import BotConfig, BotStatus, LogLevel, TradePosition
from app.services.logging_service import log_message
from app.services.mt5_client import get_mt5_client
from app.trading.aggregator import aggregate_signal
from app.trading.execution import OrderExecutor
from app.trading.market_data import MarketDataProvider
from app.trading.position_monitor import evaluate_position
from app.trading.risk import build_order_plan
from app.trading.types import NetSignal, PositionAction

logger = logging.getLogger(__name__)


class TradingOrchestrator:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._market = MarketDataProvider()
        self._executor = OrderExecutor(db)
        self._mt5 = get_mt5_client()

    def run_tick(self, bot: BotConfig) -> dict:
        if bot.status != BotStatus.RUNNING:
            return {"skipped": True, "reason": "not_running"}

        meta: dict = {"bot_id": bot.id, "at": datetime.now(timezone.utc).isoformat()}

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
                return {**meta, "error": status.error}

            df = self._market.fetch(bot)
            signal = aggregate_signal(df, bot)
            meta["weighted_score"] = signal.weighted_score
            meta["net_signal"] = signal.net_signal

            price = self._market.current_price(bot.symbol)
            open_positions = (
                self.db.query(TradePosition)
                .filter(TradePosition.bot_id == bot.id)
                .all()
            )

            for pos in open_positions:
                decision = evaluate_position(bot, pos, price, signal)
                meta.setdefault("position_actions", []).append(
                    {"ticket": pos.ticket_id, "action": decision.action.value}
                )
                self._apply_decision(bot, pos, decision, price)

            open_count = self._executor.sync_open_count(bot)
            if open_count >= bot.max_open_positions:
                self.db.commit()
                return {**meta, "opened": False, "reason": "max_positions"}

            if signal.net_signal != int(NetSignal.HOLD) and open_count == 0:
                plan = build_order_plan(
                    bot,
                    signal,
                    price,
                    equity=self._mt5.account_equity(),
                )
                if plan:
                    self._executor.open_position(bot, plan)
                    log_message(
                        self.db,
                        f"Opened {plan.side.value} {plan.volume} @ {price}",
                        bot_id=bot.id,
                        source="execution",
                    )
                    meta["opened"] = True
                else:
                    meta["opened"] = False

            self.db.commit()
            return meta

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
            return {**meta, "error": str(exc)}

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
            self._executor.close_position(bot, position, reason, exit_price=price)
            log_message(
                self.db,
                f"Closed {position.ticket_id} reason={reason}",
                bot_id=bot.id,
                source="execution",
            )
