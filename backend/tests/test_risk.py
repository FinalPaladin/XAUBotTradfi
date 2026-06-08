"""Unit tests for capital management (no MT5)."""

import math

import pytest

from app.models import BotConfig, BotStatus
from app.trading.risk import (
    calculate_fixed_lot_size,
    capital_scale_factor,
    dynamic_first_layer_notional,
    resolve_basket_tp_min,
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
