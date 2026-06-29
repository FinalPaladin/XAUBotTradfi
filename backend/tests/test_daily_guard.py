"""Tests for daily PNL guard and P0/P1 basket guardrails."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import BotConfig, BotStatus, OrderSide, TradeHistory
from app.trading.basket_manager import (
    PositionBasket,
    PositionLayer,
    check_basket_pnl_trail,
    check_max_basket_age,
    evaluate_basket,
    update_basket_peak_pnl,
)
from app.trading.daily_guard import evaluate_daily_guard, get_today_realized_pnl
from app.trading.types import AggregatedSignal, BasketAction, NetSignal


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def guard_config(db: Session) -> BotConfig:
    bot = BotConfig(
        id=1,
        name="guard-test",
        status=BotStatus.RUNNING,
        symbol="XAUUSD+",
        timeframe="M5",
        max_open_positions=2,
        max_layers=2,
        hard_stop_adverse_distance=9.0,
        max_basket_loss_pct=4.0,
        basket_time_stop_minutes=60,
        signal_threshold=0.65,
        donchian_weight=0.35,
        supertrend_weight=0.30,
        rsi_weight=0.20,
        ema_weight=0.15,
    )
    db.add(bot)
    db.commit()
    return bot


class MockPos:
    def __init__(
        self,
        ticket: str,
        side: OrderSide,
        vol: float,
        entry: float,
        idx: int = 0,
        opened_at: datetime | None = None,
    ):
        self.ticket_id = ticket
        self.side = side
        self.volume = vol
        self.entry_price = entry
        self.layer_index = idx
        self.basket_anchor_price = entry
        self.opened_at = opened_at or datetime.now(timezone.utc)
        self.highest_price = None
        self.basket_peak_pnl = None


def test_get_today_realized_pnl(db, guard_config) -> None:
    now = datetime.now(timezone.utc)
    db.add(
        TradeHistory(
            bot_id=guard_config.id,
            ticket_id="t1",
            side=OrderSide.BUY,
            volume=0.01,
            entry_price=4300.0,
            exit_price=4301.0,
            profit_loss=5.0,
            opened_at=now - timedelta(hours=1),
            closed_at=now - timedelta(minutes=30),
        )
    )
    db.add(
        TradeHistory(
            bot_id=guard_config.id,
            ticket_id="t2",
            side=OrderSide.BUY,
            volume=0.01,
            entry_price=4300.0,
            exit_price=4299.0,
            profit_loss=-20.0,
            opened_at=now - timedelta(days=2),
            closed_at=now - timedelta(days=1),
        )
    )
    db.commit()
    assert get_today_realized_pnl(db, guard_config.id) == 5.0


def test_daily_profit_lock_switches_super_safe(db, guard_config) -> None:
    now = datetime.now(timezone.utc)
    db.add(
        TradeHistory(
            bot_id=guard_config.id,
            ticket_id="win1",
            side=OrderSide.BUY,
            volume=0.01,
            entry_price=4300.0,
            exit_price=4301.0,
            profit_loss=36.0,
            opened_at=now - timedelta(hours=2),
            closed_at=now - timedelta(hours=1),
        )
    )
    db.commit()
    status = evaluate_daily_guard(db, guard_config.id, [], 4300.0, 200.0)
    assert status.switch_to_super_safe is True
    assert status.trigger_dca_full_stack_loss is False
    assert "SUPER_SAFE" in (status.reason or "")


def test_daily_loss_cap_triggers_at_40pct_balance(db, guard_config) -> None:
    """Daily loss cap = 40% balance — không còn cắt sớm ở -15 USD."""
    now = datetime.now(timezone.utc)
    db.add(
        TradeHistory(
            bot_id=guard_config.id,
            ticket_id="smallloss",
            side=OrderSide.BUY,
            volume=0.01,
            entry_price=4300.0,
            exit_price=4290.0,
            profit_loss=-16.0,
            opened_at=now - timedelta(hours=2),
            closed_at=now - timedelta(hours=1),
        )
    )
    db.commit()
    status_small = evaluate_daily_guard(
        db, guard_config.id, [], 4300.0, account_balance=100.0
    )
    assert status_small.trigger_dca_full_stack_loss is False
    assert status_small.switch_to_super_safe is False

    db.add(
        TradeHistory(
            bot_id=guard_config.id,
            ticket_id="bigloss",
            side=OrderSide.BUY,
            volume=0.01,
            entry_price=4300.0,
            exit_price=4250.0,
            profit_loss=-25.0,
            opened_at=now - timedelta(hours=1),
            closed_at=now - timedelta(minutes=30),
        )
    )
    db.commit()
    status_hit = evaluate_daily_guard(
        db, guard_config.id, [], 4300.0, account_balance=100.0
    )
    assert status_hit.trigger_dca_full_stack_loss is True
    assert "SUPER_SAFE" in (status_hit.reason or "")
    assert status_hit.switch_to_super_safe is False


def test_max_basket_age_forces_close(guard_config: BotConfig) -> None:
    old = datetime.now(timezone.utc) - timedelta(hours=6)
    basket = PositionBasket(
        side=OrderSide.BUY,
        anchor_price=4300.0,
        layers=[
            PositionLayer(
                ticket_id="1",
                side=OrderSide.BUY,
                volume=0.01,
                entry_price=4300.0,
                layer_index=0,
                opened_at=old,
            )
        ],
    )
    assert check_max_basket_age(guard_config, basket)


def test_basket_pnl_trail(guard_config: BotConfig) -> None:
    basket = PositionBasket(
        side=OrderSide.BUY,
        anchor_price=4300.0,
        layers=[
            PositionLayer(
                ticket_id="1",
                side=OrderSide.BUY,
                volume=0.01,
                entry_price=4300.0,
                layer_index=0,
            )
        ],
    )
    assert not check_basket_pnl_trail(guard_config, basket, 4300.5, peak_pnl_usd=2.0)
    assert check_basket_pnl_trail(guard_config, basket, 4300.5, peak_pnl_usd=4.0)


def test_update_basket_peak_pnl_persists_on_anchor() -> None:
    pos = MockPos("1", OrderSide.BUY, 0.01, 4300.0)
    assert update_basket_peak_pnl(pos, 2.5) == 2.5
    assert pos.basket_peak_pnl == 2.5
    assert pos.highest_price is None
    assert update_basket_peak_pnl(pos, 1.0) == 2.5


def test_basket_pnl_trail_ignores_highest_price_entry_collision(
    guard_config: BotConfig,
) -> None:
    """Regression: highest_price stores entry/market price, not P&L peak."""
    pos = MockPos("1", OrderSide.BUY, 0.01, 4320.28)
    pos.highest_price = 4320.28
    basket = PositionBasket(
        side=OrderSide.BUY,
        anchor_price=4320.28,
        layers=[
            PositionLayer(
                ticket_id="1",
                side=OrderSide.BUY,
                volume=0.01,
                entry_price=4320.28,
                layer_index=0,
            )
        ],
    )
    peak = update_basket_peak_pnl(pos, -0.52)
    assert peak == 0.0
    assert not check_basket_pnl_trail(guard_config, basket, 4315.0, peak_pnl_usd=peak)


def test_evaluate_basket_max_age_disabled(guard_config: BotConfig) -> None:
    """MAX_BASKET_AGE tắt — basket già vẫn HOLD nếu chưa đủ rule DCA."""
    old = datetime.now(timezone.utc) - timedelta(hours=6)
    basket = PositionBasket(
        side=OrderSide.BUY,
        anchor_price=4300.0,
        layers=[
            PositionLayer(
                ticket_id="1",
                side=OrderSide.BUY,
                volume=0.01,
                entry_price=4300.0,
                layer_index=0,
                opened_at=old,
            )
        ],
    )
    decision = evaluate_basket(
        guard_config,
        basket,
        4305.0,
        AggregatedSignal([], 0.0, int(NetSignal.HOLD)),
    )
    assert decision.action != BasketAction.CLOSE_MAX_AGE
