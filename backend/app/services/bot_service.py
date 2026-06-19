"""Bot configuration and control business logic."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    BotConfig,
    BotStatus,
    LogLevel,
    OrderSide,
    SystemLog,
    TradeHistory,
    TradePosition,
    TradingMode,
)
from app.schemas import AggregatedSignalRead, BotConfigUpdate, StrategyResultRead
from app.services.logging_service import log_message
from app.services.mt5_client import check_mt5_status, get_mt5_client
from app.trading.aggregator import aggregate_signal
from app.trading.execution import OrderExecutor
from app.trading.market_data import MarketDataProvider

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # type: ignore[assignment]


WEIGHT_TOLERANCE = 1e-6


def validate_weights(
    donchian: float,
    supertrend: float,
    rsi: float,
    ema: float,
) -> None:
    total = donchian + supertrend + rsi + ema
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
        prev_mode = bot.trading_mode

        if "trading_mode" in data:
            if data["trading_mode"] == TradingMode.NORMAL:
                bot.trading_mode_manual = True
            elif data["trading_mode"] == TradingMode.SUPER_SAFE:
                bot.trading_mode_manual = False

        for key, value in data.items():
            setattr(bot, key, value)

        if "trading_mode" in data and prev_mode != bot.trading_mode:
            log_message(
                self.db,
                f"Chế độ giao dịch: {prev_mode.value} → {bot.trading_mode.value}"
                + (" (chọn thủ công)" if bot.trading_mode_manual else ""),
                bot_id=bot.id,
                source="api",
            )

        validate_weights(
            bot.donchian_weight,
            bot.supertrend_weight,
            bot.rsi_weight,
            bot.ema_weight,
        )

        self.db.commit()
        self.db.refresh(bot)
        return bot

    def get_status_meta(self, *, quick: bool = True) -> dict[str, Any]:
        status = check_mt5_status(quick=quick)
        return {
            "mt5_connected": status.connected,
            "mt5_error": status.error,
            "account": status.account,
            "last_check": datetime.now(timezone.utc).isoformat(),
        }

    def list_history(self, limit: int = 500) -> list[TradeHistory]:
        return list(
            self.db.query(TradeHistory)
            .order_by(TradeHistory.closed_at.desc())
            .limit(limit)
            .all()
        )

    def list_history_page(
        self,
        *,
        days: int | None = None,
        since: datetime | None = None,
        side: OrderSide | None = None,
        pnl: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """Filtered + paginated history (date range, side, P&L, ticket search)."""
        query = self.db.query(TradeHistory)

        if since is not None:
            since_utc = since
            if since_utc.tzinfo is None:
                since_utc = since_utc.replace(tzinfo=timezone.utc)
            else:
                since_utc = since_utc.astimezone(timezone.utc)
            query = query.filter(TradeHistory.closed_at >= since_utc)
        elif days is not None and days > 0:
            since_dt = datetime.now(timezone.utc) - timedelta(days=days)
            query = query.filter(TradeHistory.closed_at >= since_dt)

        if side is not None:
            query = query.filter(TradeHistory.side == side)

        pnl_key = (pnl or "").strip().upper()
        if pnl_key == "WIN":
            query = query.filter(TradeHistory.profit_loss > 0)
        elif pnl_key == "LOSS":
            query = query.filter(TradeHistory.profit_loss < 0)

        term = (search or "").strip()
        if term:
            like = f"%{term}%"
            query = query.filter(
                or_(
                    TradeHistory.ticket_id.like(like),
                    TradeHistory.symbol.like(like),
                    TradeHistory.close_reason.like(like),
                )
            )

        total = query.count()
        total_pnl = (
            query.with_entities(func.coalesce(func.sum(TradeHistory.profit_loss), 0.0))
            .scalar()
        )

        page = max(1, page)
        page_size = min(max(page_size, 1), 100)
        offset = (page - 1) * page_size
        items = list(
            query.order_by(TradeHistory.closed_at.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )
        total_pages = math.ceil(total / page_size) if total else 0

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "total_pnl": round(float(total_pnl or 0.0), 2),
        }

    def list_logs(
        self,
        *,
        level: LogLevel | None = None,
        limit: int = 200,
    ) -> list[SystemLog]:
        q = self.db.query(SystemLog).order_by(SystemLog.created_at.desc())
        if level is not None:
            q = q.filter(SystemLog.level == level)
        return list(q.limit(limit).all())

    def list_exchanges(self, *, live: bool = False) -> list[dict[str, Any]]:
        settings = get_settings()
        if live:
            meta = self.get_status_meta(quick=True)
        else:
            from app.services.mt5_client import _status_cache

            if _status_cache is not None:
                meta = {
                    "mt5_connected": _status_cache.connected,
                    "mt5_error": _status_cache.error,
                    "account": _status_cache.account,
                    "last_check": datetime.now(timezone.utc).isoformat(),
                }
            else:
                meta = {
                    "mt5_connected": False,
                    "mt5_error": "Chưa kiểm tra MT5 — dùng ?live=true để test kết nối",
                    "account": None,
                    "last_check": datetime.now(timezone.utc).isoformat(),
                }
        login_display = (
            str(settings.mt5_login) if settings.mt5_login is not None else None
        )
        server = settings.mt5_server or "MT5"
        return [
            {
                "id": "mt5-primary",
                "name": f"{server} (MT5)",
                "platform": "MetaTrader 5",
                "server": server,
                "login": login_display,
                "connected": bool(meta.get("mt5_connected")),
                "error": meta.get("mt5_error"),
                "extra": {
                    "mt5_path": settings.mt5_path,
                    "account": meta.get("account"),
                },
            }
        ]

    def get_dashboard(
        self,
        history_limit: int = 20,
    ) -> tuple[list[BotConfig], list[TradePosition], list[TradeHistory], dict]:
        bots = self.list_configs()
        positions = list(self.db.query(TradePosition).all())
        history = self.list_history(limit=history_limit)
        meta = self.get_status_meta()
        symbols = {p.symbol for p in positions}
        meta["symbol_ticks"] = self._fetch_symbol_ticks(symbols)
        meta["position_live"] = self._fetch_position_live(positions)
        return bots, positions, history, meta

    def _fetch_position_live(
        self, positions: list[TradePosition]
    ) -> dict[str, dict[str, float]]:
        if not positions:
            return {}
        client = get_mt5_client()
        status = client.initialize(quick=True)
        if not status.connected:
            return {}
        live: dict[str, dict[str, float]] = {}
        for pos in positions:
            data = client.position_live(int(pos.ticket_id))
            if data:
                live[pos.ticket_id] = data
        return live

    def _fetch_symbol_ticks(self, symbols: set[str]) -> dict[str, float | None]:
        if not symbols:
            return {}
        client = get_mt5_client()
        status = client.initialize(quick=True)
        if not status.connected:
            return {s: None for s in symbols}
        ticks: dict[str, float | None] = {}
        for symbol in symbols:
            tick = client.tick(symbol)
            if tick is None:
                ticks[symbol] = None
            else:
                ticks[symbol] = (float(tick.bid) + float(tick.ask)) / 2
        return ticks

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

    def close_position_by_id(self, position_id: int) -> dict[str, Any]:
        """Đóng một lệnh tại giá market (không dừng bot)."""
        position = (
            self.db.query(TradePosition)
            .filter(TradePosition.id == position_id)
            .first()
        )
        if not position:
            raise ValueError(f"Position {position_id} not found")

        bot = self.get_config(position.bot_id)
        if not bot:
            raise ValueError(f"Bot {position.bot_id} not found")

        client = get_mt5_client()
        status = client.initialize()
        if not status.connected:
            raise RuntimeError(status.error or "MT5 not connected")

        executor = OrderExecutor(self.db)
        executor.close_position(bot, position, "MANUAL_MARKET")
        log_message(
            self.db,
            f"Manual market close ticket={position.ticket_id}",
            bot_id=bot.id,
            source="api",
        )
        self.db.commit()
        return {"position_id": position_id, "ticket_id": position.ticket_id}

    def close_all_open_positions(self) -> dict[str, Any]:
        """Đóng toàn bộ lệnh đang mở tại giá market (không dừng bot)."""
        positions = list(self.db.query(TradePosition).all())
        if not positions:
            return {"positions_closed": 0}

        client = get_mt5_client()
        status = client.initialize()
        if not status.connected:
            raise RuntimeError(status.error or "MT5 not connected")

        executor = OrderExecutor(self.db)
        closed = 0
        for position in positions:
            bot = self.get_config(position.bot_id)
            if not bot:
                continue
            try:
                executor.close_position(bot, position, "MANUAL_MARKET_ALL")
                log_message(
                    self.db,
                    f"Manual market close-all ticket={position.ticket_id}",
                    bot_id=bot.id,
                    source="api",
                )
                closed += 1
            except Exception:
                continue

        self.db.commit()
        return {"positions_closed": closed}

    def resync_history_pnl_from_mt5(self, limit: int = 500) -> dict[str, Any]:
        """Cập nhật P&L / giá vào-ra từ deal history MT5 (sửa bản ghi lệch Exness)."""
        if mt5 is None:
            raise RuntimeError("MetaTrader5 not available")

        client = get_mt5_client()
        status = client.initialize(quick=True)
        if not status.connected:
            raise RuntimeError(status.error or "MT5 not connected")

        rows = self.list_history(limit=limit)
        updated = 0
        skipped = 0

        for h in rows:
            try:
                ticket = int(h.ticket_id)
            except ValueError:
                skipped += 1
                continue

            try:
                deals = mt5.history_deals_get(position=ticket)
            except TypeError:
                deals = None

            if not deals:
                from datetime import timedelta

                start = h.opened_at - timedelta(hours=2)
                end = h.closed_at + timedelta(hours=2)
                deals = mt5.history_deals_get(start, end)
                if deals:
                    deals = [d for d in deals if int(d.position_id) == ticket]

            if not deals:
                skipped += 1
                continue

            in_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_IN]
            out_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
            if not out_deals:
                skipped += 1
                continue

            entry_deal = in_deals[0] if in_deals else None
            exit_deal = sorted(out_deals, key=lambda d: d.time)[-1]

            if entry_deal is not None:
                h.entry_price = round(float(entry_deal.price), 3)
                h.opened_at = datetime.fromtimestamp(
                    int(entry_deal.time), tz=timezone.utc
                )
            h.exit_price = round(float(exit_deal.price), 3)
            h.profit_loss = round(float(exit_deal.profit), 2)
            h.closed_at = datetime.fromtimestamp(
                int(exit_deal.time), tz=timezone.utc
            )
            updated += 1

        self.db.commit()
        return {"updated": updated, "skipped": skipped, "total": len(rows)}
