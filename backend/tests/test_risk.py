"""Unit tests for capital management (no MT5)."""

import math

import pytest

from app.models import BotConfig, BotStatus
from app.models import OrderSide
from app.trading.risk import (
    SCALP_VOLUME_MULTIPLIER,
    build_layer_plan,
    calculate_fixed_lot_size,
    calculate_layer_volume,
    capital_scale_factor,
    dynamic_first_layer_notional,
    resolve_basket_tp_min,
    resolve_single_tp_min,
    scaled_tp_usd,
)


@pytest.fixture
def config() -> BotConfig:
    return BotConfig(
        id=1,
        name="risk-test",
        status=BotStatus.RUNNING,
        symbol="XAUUSD+",
        base_equity_usd=200.0,
        first_layer_notional_usd=6750.0,
        basket_tp_min_usd=2.0,
        single_tp_min_usd=1.0,
        single_tp_distance=1.2,
    )


def test_fixed_lot_10k() -> None:
    assert calculate_fixed_lot_size(10_000) == 0.10


def test_fixed_lot_under_1k() -> None:
    assert calculate_fixed_lot_size(500) == 0.01


def test_capital_scale_10k(config: BotConfig) -> None:
    assert capital_scale_factor(10_000, config.base_equity_usd) == 50.0


def test_scaled_tp_10k(config: BotConfig) -> None:
    assert scaled_tp_usd(2.0, 10_000, config.base_equity_usd) == 100.0


def test_dynamic_notional_10k(config: BotConfig) -> None:
    # 6750/200 × 10000 = 337500
    assert dynamic_first_layer_notional(config, 10_000) == 337_500.0


def test_basket_tp_min_scales(config: BotConfig) -> None:
    assert resolve_basket_tp_min(config, 10_000) == 100.0


def test_dca_multiplier_one_keeps_flat_volume(config: BotConfig) -> None:
    config.dca_volume_multiplier = 1.0
    for layer in range(4):
        vol = calculate_layer_volume(config, 2400.0, layer, 500.0)
        assert vol == pytest.approx(0.01)


def test_dca_multiplier_scales_higher_layers(config: BotConfig) -> None:
    config.dca_volume_multiplier = 1.35
    assert calculate_layer_volume(config, 2400.0, 0, 500.0) == pytest.approx(0.01)
    assert calculate_layer_volume(config, 2400.0, 2, 500.0) == pytest.approx(0.02)


def test_scalp_mode_halves_volume(config: BotConfig) -> None:
    normal = calculate_layer_volume(config, 2400.0, 0, 10_000)
    scalp = calculate_layer_volume(config, 2400.0, 0, 10_000, is_scalp_mode=True)
    assert scalp == pytest.approx(normal * SCALP_VOLUME_MULTIPLIER)


def test_scalp_mode_sets_broker_tp(config: BotConfig, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.trading.risk._clamp_volume",
        lambda _symbol, volume: volume,
    )
    normal = build_layer_plan(
        config,
        OrderSide.BUY,
        2400.0,
        layer_index=0,
        account_balance=10_000,
        is_scalp_mode=False,
    )
    scalp = build_layer_plan(
        config,
        OrderSide.BUY,
        2400.0,
        layer_index=0,
        account_balance=10_000,
        is_scalp_mode=True,
    )
    assert normal is not None and scalp is not None
    assert normal.tp_price is None
    assert scalp.tp_price is not None
    assert scalp.use_broker_sl_tp is False
    scalp_dist = scalp.tp_price - scalp.entry_price
    expected_min_dist = max(
        resolve_single_tp_min(config, 10_000) / (scalp.volume * 100.0),
        config.single_tp_distance,
    )
    assert scalp_dist >= expected_min_dist - 0.01
    assert "SCALP" in scalp.comment
