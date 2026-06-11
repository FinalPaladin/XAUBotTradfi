"""Tests for paginated trade history."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import BotConfig, BotStatus, OrderSide, TradeHistory
from app.services.bot_service import BotService


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    bot = BotConfig(id=1, name="hist", status=BotStatus.STOPPED, symbol="XAUUSD+")
    session.add(bot)
    now = datetime.now(timezone.utc)
    session.add_all(
        [
            TradeHistory(
                bot_id=1,
                ticket_id="111",
                symbol="XAUUSD+",
                side=OrderSide.BUY,
                volume=0.01,
                entry_price=4300.0,
                exit_price=4310.0,
                profit_loss=10.0,
                close_reason="TP",
                opened_at=now - timedelta(days=2),
                closed_at=now - timedelta(days=1),
            ),
            TradeHistory(
                bot_id=1,
                ticket_id="222",
                symbol="XAUUSD+",
                side=OrderSide.SELL,
                volume=0.01,
                entry_price=4320.0,
                exit_price=4310.0,
                profit_loss=10.0,
                close_reason="TP",
                opened_at=now - timedelta(days=10),
                closed_at=now - timedelta(days=9),
            ),
            TradeHistory(
                bot_id=1,
                ticket_id="333-old",
                symbol="XAUUSD+",
                side=OrderSide.BUY,
                volume=0.01,
                entry_price=4200.0,
                exit_price=4190.0,
                profit_loss=-10.0,
                close_reason="SL",
                opened_at=now - timedelta(days=40),
                closed_at=now - timedelta(days=39),
            ),
        ]
    )
    session.commit()
    yield session
    session.close()


def test_history_page_default_filters_last_7_days(db: Session) -> None:
    result = BotService(db).list_history_page(days=7, page=1, page_size=20)
    assert result["total"] == 1
    assert result["items"][0].ticket_id == "111"
    assert result["total_pnl"] == 10.0


def test_history_page_side_filter(db: Session) -> None:
    result = BotService(db).list_history_page(days=90, side=OrderSide.SELL, page=1, page_size=20)
    assert result["total"] == 1
    assert result["items"][0].side == OrderSide.SELL


def test_history_page_pnl_filter_win(db: Session) -> None:
    result = BotService(db).list_history_page(days=90, pnl="WIN", page=1, page_size=20)
    assert result["total"] == 2
    assert all(h.profit_loss > 0 for h in result["items"])


def test_history_page_pnl_filter_loss(db: Session) -> None:
    result = BotService(db).list_history_page(days=90, pnl="LOSS", page=1, page_size=20)
    assert result["total"] == 1
    assert result["items"][0].profit_loss < 0


def test_history_page_since_today(db: Session) -> None:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    result = BotService(db).list_history_page(since=start, page=1, page_size=20)
    assert result["total"] == 0


def test_history_page_search_ticket(db: Session) -> None:
    result = BotService(db).list_history_page(days=90, search="333", page=1, page_size=20)
    assert result["total"] == 1
    assert result["items"][0].ticket_id == "333-old"


def test_history_page_pagination(db: Session) -> None:
    result = BotService(db).list_history_page(days=90, page=1, page_size=1)
    assert result["total"] == 3
    assert result["total_pages"] == 3
    assert len(result["items"]) == 1
