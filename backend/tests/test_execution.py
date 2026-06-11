"""OrderExecutor tests (mock MT5 client, no terminal)."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import BotConfig, BotStatus, OrderSide, TradeHistory, TradePosition
from app.services.mt5_client import POSITION_NOT_FOUND, CloseFillResult
from app.trading.execution import OrderExecutor


class FakeMT5Position:
    POSITION_TYPE_BUY = 0
    POSITION_TYPE_SELL = 1

    def __init__(
        self,
        ticket: int,
        symbol: str = "XAUUSD+",
        *,
        side_buy: bool = True,
        volume: float = 0.01,
        price_open: float = 4300.0,
        sl: float = 0.0,
        tp: float = 0.0,
        magic: int = 202501,
    ) -> None:
        self.ticket = ticket
        self.symbol = symbol
        self.type = self.POSITION_TYPE_BUY if side_buy else self.POSITION_TYPE_SELL
        self.volume = volume
        self.price_open = price_open
        self.sl = sl
        self.tp = tp
        self.magic = magic


class FakeMT5Client:
    def __init__(
        self,
        *,
        close_result: CloseFillResult | None = None,
        is_open: bool = False,
        history_exit: float | None = None,
        history_pnl: float | None = None,
        open_positions: list[FakeMT5Position] | None = None,
        open_tickets: set[int] | None = None,
    ) -> None:
        self.close_result = close_result or CloseFillResult(
            ok=False, error=POSITION_NOT_FOUND
        )
        self.is_open = is_open
        self.history_exit = history_exit
        self.history_pnl = history_pnl
        self.open_positions = open_positions or []
        self.open_tickets = open_tickets or set()

    def positions_get(self, symbol: str | None = None, magic: int | None = None) -> list:
        positions = list(self.open_positions)
        if magic is not None:
            positions = [p for p in positions if p.magic == magic]
        if symbol is not None:
            positions = [p for p in positions if p.symbol == symbol]
        return positions

    def position_entry_price(self, ticket: int) -> float | None:
        for p in self.open_positions:
            if p.ticket == ticket:
                return p.price_open
        return None

    def position_close(self, ticket: int) -> CloseFillResult:
        return self.close_result

    def position_is_open(self, ticket: int) -> bool:
        if ticket in self.open_tickets:
            return True
        return self.is_open

    def position_exit_from_history(
        self, ticket: int
    ) -> tuple[float | None, float | None]:
        return self.history_exit, self.history_pnl


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    bot = BotConfig(id=1, name="test-bot", status=BotStatus.STOPPED, symbol="XAUUSD+")
    session.add(bot)
    session.commit()
    yield session
    session.close()


def _add_position(db: Session) -> TradePosition:
    pos = TradePosition(
        bot_id=1,
        ticket_id="12345",
        symbol="XAUUSD+",
        side=OrderSide.BUY,
        volume=0.02,
        entry_price=4300.0,
        opened_at=datetime.now(timezone.utc),
    )
    db.add(pos)
    db.commit()
    db.refresh(pos)
    return pos


def test_close_reconciles_when_mt5_position_missing(db: Session) -> None:
    pos = _add_position(db)
    bot = db.get(BotConfig, 1)
    assert bot is not None

    client = FakeMT5Client(
        history_exit=4295.0,
        history_pnl=-10.0,
    )
    executor = OrderExecutor(db, client=client)

    history = executor.close_position(bot, pos, "MANUAL_MARKET_ALL")

    assert db.query(TradePosition).count() == 0
    assert db.query(TradeHistory).count() == 1
    assert history.exit_price == 4295.0
    assert history.profit_loss == -10.0
    assert history.close_reason == "MANUAL_MARKET_ALL"


def test_close_still_raises_when_mt5_reports_missing_but_position_open(
    db: Session,
) -> None:
    pos = _add_position(db)
    bot = db.get(BotConfig, 1)
    assert bot is not None

    client = FakeMT5Client(is_open=True)
    executor = OrderExecutor(db, client=client)

    with pytest.raises(RuntimeError, match="still open on MT5"):
        executor.close_position(bot, pos, "MANUAL_MARKET")

    assert db.query(TradePosition).count() == 1


def test_write_closed_history_skips_duplicate_ticket(db: Session) -> None:
    pos = _add_position(db)
    bot = db.get(BotConfig, 1)
    assert bot is not None

    existing = TradeHistory(
        bot_id=bot.id,
        ticket_id=pos.ticket_id,
        symbol=pos.symbol,
        side=pos.side,
        volume=pos.volume,
        entry_price=4300.0,
        exit_price=4290.0,
        profit_loss=-20.0,
        close_reason="BASKET_TP",
        opened_at=pos.opened_at,
        closed_at=datetime.now(timezone.utc),
    )
    db.add(existing)
    db.commit()

    client = FakeMT5Client(
        history_exit=4295.0,
        history_pnl=-10.0,
    )
    executor = OrderExecutor(db, client=client)
    history = executor.close_position(bot, pos, "BASKET_TP")

    assert db.query(TradeHistory).count() == 1
    assert db.query(TradePosition).count() == 0
    assert history.id == existing.id
    assert history.profit_loss == -20.0


def test_close_uses_fill_when_mt5_close_succeeds(db: Session) -> None:
    pos = _add_position(db)
    bot = db.get(BotConfig, 1)
    assert bot is not None

    client = FakeMT5Client(
        close_result=CloseFillResult(
            ok=True,
            fill_price=4310.0,
            net_pnl=20.0,
            entry_price=4300.0,
        )
    )
    executor = OrderExecutor(db, client=client)

    history = executor.close_position(bot, pos, "MANUAL_MARKET")

    assert db.query(TradePosition).count() == 0
    assert history.exit_price == 4310.0
    assert history.profit_loss == 20.0


def test_sync_skips_reconcile_when_ticket_still_open(db: Session) -> None:
    pos = _add_position(db)
    bot = db.get(BotConfig, 1)
    assert bot is not None

    client = FakeMT5Client(open_tickets={12345})
    executor = OrderExecutor(db, client=client)

    stats = executor.sync_positions_with_mt5(bot)

    assert stats == {"imported": 0, "reconciled": 0}
    assert db.query(TradePosition).count() == 1


def test_sync_reconciles_closed_ticket(db: Session) -> None:
    pos = _add_position(db)
    bot = db.get(BotConfig, 1)
    assert bot is not None

    client = FakeMT5Client(history_exit=4295.0, history_pnl=-10.0)
    executor = OrderExecutor(db, client=client)

    stats = executor.sync_positions_with_mt5(bot)

    assert stats == {"imported": 0, "reconciled": 1}
    assert db.query(TradePosition).count() == 0
    assert db.query(TradeHistory).count() == 1
