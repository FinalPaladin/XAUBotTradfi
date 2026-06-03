"""Bot configuration and control business logic."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import BotConfig, BotStatus, LogLevel, SystemLog, TradeHistory, TradePosition
from app.schemas import AggregatedSignalRead, BotConfigUpdate, StrategyResultRead
from app.services.logging_service import log_message
from app.services.mt5_client import get_mt5_client
from app.trading.aggregator import aggregate_signal
from app.trading.execution import OrderExecutor
from app.trading.market_data import MarketDataProvider


WEIGHT_TOLERANCE = 1e-6


def validate_weights(
    donchian: float,
    supertrend: float,
    rsi: float,
) -> None:
    total = donchian + supertrend + rsi
    if abs(total - 1.0) > WEIGHT_TOLERANCE:
        raise ValueError(
            f"Strategy weights must sum to 1.0 (got {total:.4f})"
        )


class BotService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_configs(self) -> list[BotConfig]:
        return list(self.db.query(BotConfig).order_by(BotConfig.id).all())

    def get_config(self, bot_id: int) -> BotConfig | None:
        return self.db.query(BotConfig).filter(BotConfig.id == bot_id).first()

    def update_config(self, payload: BotConfigUpdate) -> BotConfig:
        bot: BotConfig | None = None
        if payload.id is not None:
            bot = self.get_config(payload.id)
        elif payload.name:
            bot = self.db.query(BotConfig).filter(BotConfig.name == payload.name).first()

        if bot is None:
            if not payload.name:
                raise ValueError("name is required for new bot config")
            from app.seed import _default_xauusd_bot

            bot = _default_xauusd_bot()
            bot.name = payload.name
            self.db.add(bot)

        data = payload.model_dump(exclude_unset=True, exclude={"id"})
        for key, value in data.items():
            setattr(bot, key, value)

        validate_weights(
            bot.donchian_weight,
            bot.supertrend_weight,
            bot.rsi_weight,
        )

        self.db.commit()
        self.db.refresh(bot)
        return bot

    def get_status_meta(self) -> dict[str, Any]:
        mt5 = get_mt5_client()
        status = mt5.initialize()
        return {
            "mt5_connected": status.connected,
            "mt5_error": status.error,
            "account": status.account,
            "last_check": datetime.now(timezone.utc).isoformat(),
        }

    def get_dashboard(
        self,
        history_limit: int = 20,
    ) -> tuple[list[BotConfig], list[TradePosition], list[TradeHistory], dict]:
        bots = self.list_configs()
        positions = list(self.db.query(TradePosition).all())
        history = (
            self.db.query(TradeHistory)
            .order_by(TradeHistory.closed_at.desc())
            .limit(history_limit)
            .all()
        )
        meta = self.get_status_meta()
        return bots, positions, history, meta

    def compute_signals(self, bot_id: int) -> AggregatedSignalRead:
        bot = self.get_config(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found")
        df = MarketDataProvider().fetch(bot)
        agg = aggregate_signal(df, bot)
        return AggregatedSignalRead(
            strategy_results=[
                StrategyResultRead(name=r.name, score=r.score, raw=r.raw)
                for r in agg.strategy_results
            ],
            weighted_score=agg.weighted_score,
            net_signal=agg.net_signal,
        )

    def stop_all(self) -> dict[str, Any]:
        bots = self.list_configs()
        executor = OrderExecutor(self.db)
        closed = 0
        for bot in bots:
            bot.status = BotStatus.STOPPED
            closed += executor.close_all_for_bot(bot, "STOP_ALL")
            log_message(
                self.db,
                "Bot stopped via stop-all",
                bot_id=bot.id,
                source="api",
            )
        self.db.commit()
        return {"bots_stopped": len(bots), "positions_closed": closed}

    def set_status(self, bot_id: int, status: BotStatus) -> BotConfig:
        bot = self.get_config(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found")
        bot.status = status
        log_message(
            self.db,
            f"Status set to {status.value}",
            bot_id=bot.id,
            source="api",
        )
        self.db.commit()
        self.db.refresh(bot)
        return bot
