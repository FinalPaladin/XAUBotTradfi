"""Unit tests for DCA basket manager (no MT5 required)."""

from datetime import datetime, timezone

import pytest

from app.models import BotConfig, BotStatus, OrderSide
from app.trading.basket_manager import (
    PositionBasket,
    PositionLayer,
    build_position_basket,
    calculate_adverse_distance,
    calculate_breakeven_price,
    calculate_net_pnl_usd,
    check_hard_stop_loss,
    check_joint_take_profit,
    check_single_layer_scalp_tp,
    should_add_dca_layer,
)
from app.trading.types import AggregatedSignal, StrategyResult


@pytest.fixture
def dca_config() -> BotConfig:
    return BotConfig(
        id=1,
        name="test-dca",
        status=BotStatus.RUNNING,
        symbol="XAUUSD+",
        timeframe="M5",
        max_open_positions=5,
        max_layers=5,
        layer_spacing_min=5.0,
        basket_tp_min_usd=2.0,
        basket_tp_max_usd=5.0,
        single_tp_min_usd=1.0,
        single_tp_max_usd=2.0,
        single_tp_distance=1.2,
        hard_stop_adverse_distance=35.0,
        signal_threshold=0.65,
        donchian_weight=0.35,
        supertrend_weight=0.30,
        rsi_weight=0.20,
        ema_period=21,
        ema_weight=0.15,
    )


def _basket_buy(layers: list[tuple[float, float]]) -> PositionBasket:
    """Helper: (entry, volume) pairs."""
    return PositionBasket(
        side=OrderSide.BUY,
        anchor_price=layers[0][0],
        layers=[
            PositionLayer(
                ticket_id=str(i),
                side=OrderSide.BUY,
                volume=vol,
                entry_price=price,
                layer_index=i,
            )
            for i, (price, vol) in enumerate(layers)
        ],
    )


def test_calculate_breakeven_price_weighted(dca_config: BotConfig) -> None:
    basket = _basket_buy([(2650.0, 0.02), (2645.0, 0.027)])
    be = calculate_breakeven_price(basket)
    expected = (2650.0 * 0.02 + 2645.0 * 0.027) / (0.02 + 0.027)
    assert be == round(expected, 2)


def test_single_layer_scalp_tp_usd(dca_config: BotConfig) -> None:
    basket = _basket_buy([(2650.0, 0.02)])
    assert not check_single_layer_scalp_tp(dca_config, basket, 2650.2)
    assert check_single_layer_scalp_tp(dca_config, basket, 2650.5)


def test_joint_tp_requires_2_usd_for_dca(dca_config: BotConfig) -> None:
    basket = _basket_buy([(2650.0, 0.02), (2645.0, 0.027)])
    assert not check_joint_take_profit(dca_config, basket, 2647.5)
    assert check_joint_take_profit(dca_config, basket, 2650.0)


def test_check_single_layer_scalp_tp(dca_config: BotConfig) -> None:
    basket = _basket_buy([(2650.0, 0.02)])
    assert not check_single_layer_scalp_tp(dca_config, basket, 2650.2)
    assert check_single_layer_scalp_tp(dca_config, basket, 2650.5)


def test_check_hard_stop_35_gold(dca_config: BotConfig) -> None:
    basket = _basket_buy([(2650.0, 0.02), (2645.0, 0.027)])
    assert not check_hard_stop_loss(dca_config, basket, 2620.0)
    assert check_hard_stop_loss(dca_config, basket, 2614.0)


def test_should_add_dca_layer_spacing(dca_config: BotConfig) -> None:
    basket = _basket_buy([(2650.0, 0.02)])
    assert not should_add_dca_layer(dca_config, basket, 2648.0)
    assert should_add_dca_layer(dca_config, basket, 2644.0)


def test_calculate_adverse_distance_buy(dca_config: BotConfig) -> None:
    basket = _basket_buy([(2650.0, 0.02)])
    assert calculate_adverse_distance(basket, 2640.0) == 10.0


def test_build_position_basket_from_mock_positions() -> None:
    class MockPos:
        def __init__(self, ticket: str, side: OrderSide, vol: float, entry: float, idx: int):
            self.ticket_id = ticket
            self.side = side
            self.volume = vol
            self.entry_price = entry
            self.layer_index = idx
            self.basket_anchor_price = 2650.0
            self.opened_at = datetime.now(timezone.utc)

    positions = [
        MockPos("1", OrderSide.BUY, 0.02, 2650.0, 0),
        MockPos("2", OrderSide.BUY, 0.027, 2645.0, 1),
    ]
    basket = build_position_basket(positions)
    assert basket is not None
    assert basket.layer_count == 2
    assert basket.is_multi_layer
