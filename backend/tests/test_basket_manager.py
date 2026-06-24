"""Unit tests for DCA basket manager (no MT5 required)."""

from datetime import datetime, timezone

import pytest

from app.models import BotConfig, BotStatus, OrderSide
from app.trading.basket_manager import (
    BasketContext,
    PositionBasket,
    PositionLayer,
    build_position_basket,
    calculate_adverse_distance,
    calculate_breakeven_price,
    calculate_net_pnl_usd,
    check_basket_profit_target,
    check_hard_stop_loss,
    check_joint_take_profit,
    check_max_basket_loss_usd,
    check_m5_reversal_exit,
    check_panic_signal_exit,
    check_single_layer_scalp_tp,
    check_trend_flip_exit,
    effective_max_layers,
    evaluate_basket,
    should_add_dca_layer,
    should_open_initial_layer,
    should_open_reversal_hedge_layer,
)
from app.trading.signal_engine import MainTrend
from app.trading.types import AggregatedSignal, BasketAction, NetSignal, StrategyResult


@pytest.fixture
def dca_config() -> BotConfig:
    return BotConfig(
        id=1,
        name="test-dca",
        status=BotStatus.RUNNING,
        symbol="XAUUSD+",
        timeframe="M5",
        max_open_positions=4,
        max_layers=4,
        layer_spacing_min=4.0,
        layer_spacing_max=4.0,
        basket_tp_min_usd=1.0,
        basket_tp_max_usd=5.0,
        single_tp_min_usd=1.0,
        single_tp_max_usd=2.0,
        single_tp_distance=1.2,
        base_equity_usd=200.0,
        hard_stop_adverse_distance=12.0,
        max_basket_loss_usd=10.0,
        max_basket_loss_pct=0.0,
        counter_trend_max_layers=1,
        atr_stop_multiplier=2.0,
        basket_time_stop_minutes=60,
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


def _basket_sell(layers: list[tuple[float, float]]) -> PositionBasket:
    return PositionBasket(
        side=OrderSide.SELL,
        anchor_price=layers[0][0],
        layers=[
            PositionLayer(
                ticket_id=str(i),
                side=OrderSide.SELL,
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


def test_joint_tp_requires_1_usd_for_dca(dca_config: BotConfig) -> None:
    basket = _basket_buy([(2650.0, 0.02), (2645.0, 0.027)])
    assert not check_joint_take_profit(dca_config, basket, 2647.3)
    assert check_joint_take_profit(dca_config, basket, 2647.4)


def test_check_hard_stop_12_gold(dca_config: BotConfig) -> None:
    basket = _basket_buy([(2650.0, 0.02), (2645.0, 0.027)])
    assert not check_hard_stop_loss(dca_config, basket, 2639.0)
    assert check_hard_stop_loss(dca_config, basket, 2637.0)


def test_should_add_dca_layer_spacing(dca_config: BotConfig) -> None:
    basket = _basket_buy([(2650.0, 0.02)])
    ctx = BasketContext(main_trend=MainTrend.BULLISH)
    assert not should_add_dca_layer(
        dca_config, basket, 2648.0, ctx=ctx, net_pnl_usd=0.0
    )
    assert should_add_dca_layer(
        dca_config, basket, 2644.0, ctx=ctx, net_pnl_usd=0.0
    )


def test_dca_blocked_counter_trend(dca_config: BotConfig) -> None:
    basket = _basket_sell([(2650.0, 0.02)])
    ctx = BasketContext(main_trend=MainTrend.BULLISH)
    assert not should_add_dca_layer(
        dca_config, basket, 2656.0, ctx=ctx, net_pnl_usd=-1.0
    )


def test_dca_catch_up_when_spacing_exceeds_max(dca_config: BotConfig) -> None:
    """P0: spacing > layer_spacing_max vẫn nhồi DCA khi >= min."""
    basket = _basket_buy([(2650.0, 0.02)])
    ctx = BasketContext(main_trend=MainTrend.BULLISH)
    assert should_add_dca_layer(
        dca_config, basket, 2640.0, ctx=ctx, net_pnl_usd=0.0
    )


def test_max_basket_loss_pct(dca_config: BotConfig) -> None:
    dca_config.max_basket_loss_pct = 20.0
    basket = _basket_buy([(2650.0, 0.02)])
    assert not check_max_basket_loss_usd(
        dca_config, basket, 2640.0, account_balance=200.0
    )
    assert check_max_basket_loss_usd(
        dca_config, basket, 2630.0, account_balance=200.0
    )


def test_per_layer_dca_tp(dca_config: BotConfig) -> None:
    from app.trading.basket_manager import check_per_layer_dca_tp

    core_layer = PositionLayer(
        ticket_id="1",
        side=OrderSide.SELL,
        volume=0.02,
        entry_price=2650.0,
        layer_index=1,
    )
    assert not check_per_layer_dca_tp(dca_config, core_layer, 2648.5, 200.0)

    satellite = PositionLayer(
        ticket_id="3",
        side=OrderSide.SELL,
        volume=0.02,
        entry_price=2650.0,
        layer_index=3,
    )
    assert not check_per_layer_dca_tp(dca_config, satellite, 2649.6, 200.0)
    assert check_per_layer_dca_tp(dca_config, satellite, 2648.5, 200.0)


def test_max_basket_loss_usd(dca_config: BotConfig) -> None:
    basket = _basket_buy([(2650.0, 0.02)])
    assert not check_max_basket_loss_usd(dca_config, basket, 2649.0)
    assert check_max_basket_loss_usd(dca_config, basket, 2644.0)


def test_trend_flip_exit_short_in_bullish() -> None:
    basket = _basket_sell([(2650.0, 0.02)])
    ctx = BasketContext(main_trend=MainTrend.BULLISH)
    adverse = calculate_adverse_distance(basket, 2654.0)
    assert check_trend_flip_exit(basket, ctx, adverse)


def test_m5_reversal_exit_short_underwater() -> None:
    basket = _basket_sell([(2650.0, 0.02)])
    ctx = BasketContext(
        main_trend=MainTrend.BEARISH,
        entry_net_raw=int(NetSignal.BUY),
        entry_score=0.6,
    )
    assert check_m5_reversal_exit(basket, ctx, net_pnl=-2.0)


def test_panic_signal_exit_long_basket_strong_sell() -> None:
    basket = _basket_buy([(2650.0, 0.02)])
    ctx = BasketContext(main_trend=MainTrend.BULLISH, entry_score=-0.85)
    assert check_panic_signal_exit(basket, ctx)
    assert not check_panic_signal_exit(
        basket, BasketContext(main_trend=MainTrend.BULLISH, entry_score=-0.7)
    )


def test_panic_signal_exit_short_basket_strong_buy() -> None:
    basket = _basket_sell([(2650.0, 0.02)])
    ctx = BasketContext(main_trend=MainTrend.BEARISH, entry_score=0.85)
    assert check_panic_signal_exit(basket, ctx)


def test_evaluate_basket_panic_signal_disabled(dca_config: BotConfig) -> None:
    """PANIC_SIGNAL tắt — DCA gồng, không cắt theo M5 panic."""
    basket = _basket_buy([(2650.0, 0.02), (2645.0, 0.027)])
    ctx = BasketContext(main_trend=MainTrend.BULLISH, entry_score=-0.9)
    decision = evaluate_basket(
        dca_config,
        basket,
        2648.0,
        AggregatedSignal([], 0.0, int(NetSignal.HOLD)),
        ctx=ctx,
    )
    assert decision.action != BasketAction.CLOSE_PANIC_SIGNAL


def test_evaluate_basket_m5_reversal_disabled(dca_config: BotConfig) -> None:
    """M5_REVERSAL tắt — basket lỗ + M5 flip vẫn HOLD để DCA."""
    basket = _basket_sell([(2650.0, 0.02), (2654.0, 0.027)])
    ctx = BasketContext(
        main_trend=MainTrend.BEARISH,
        entry_net_raw=int(NetSignal.BUY),
        entry_score=0.6,
    )
    decision = evaluate_basket(
        dca_config,
        basket,
        2655.0,
        AggregatedSignal([], 0.0, int(NetSignal.HOLD)),
        ctx=ctx,
    )
    assert decision.action != BasketAction.CLOSE_M5_REVERSAL
    assert decision.action == BasketAction.HOLD


def test_effective_max_layers_counter_trend(dca_config: BotConfig) -> None:
    basket = _basket_sell([(2650.0, 0.02)])
    ctx = BasketContext(main_trend=MainTrend.BULLISH, is_scalp_mode=True)
    assert effective_max_layers(dca_config, basket, ctx) == 1


def test_calculate_adverse_distance_buy(dca_config: BotConfig) -> None:
    basket = _basket_buy([(2650.0, 0.02)])
    assert calculate_adverse_distance(basket, 2640.0) == 10.0


def test_should_open_initial_layer_blocks_same_side() -> None:
    class MockPos:
        def __init__(self, side: OrderSide):
            self.side = side

    signal = AggregatedSignal(
        strategy_results=[],
        weighted_score=-0.9,
        net_signal=int(NetSignal.SELL),
    )
    assert should_open_initial_layer(signal, [])
    assert not should_open_initial_layer(signal, [MockPos(OrderSide.SELL)])


def test_reversal_hedge_disabled() -> None:
    class MockPos:
        def __init__(self, side: OrderSide):
            self.side = side

    signal = AggregatedSignal(
        strategy_results=[],
        weighted_score=0.85,
        net_signal=int(NetSignal.BUY),
        is_scalp_mode=True,
    )
    positions = [MockPos(OrderSide.SELL)]
    assert not should_open_reversal_hedge_layer(
        signal, positions, is_scalp_mode=True
    )


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


def test_core_tp_requires_bid_not_mid(dca_config: BotConfig) -> None:
    """Regression: mid ~1.57 USD ảo nhưng bid thực < $1 — không chốt core."""
    basket = _basket_buy(
        [(4083.61, 0.01), (4079.67, 0.01), (4075.75, 0.01)],
    )
    assert check_basket_profit_target(dca_config, basket, 4080.85, 100.0)
    assert not check_basket_profit_target(dca_config, basket, 4079.70, 100.0)


def test_core_basket_tp_closes_only_core_layers(dca_config: BotConfig) -> None:
    """4 lớp: core 3 lớp đủ TP → chỉ đóng ticket 0,1,2."""
    basket = _basket_buy(
        [
            (2650.0, 0.01),
            (2645.0, 0.01),
            (2640.0, 0.01),
            (2635.0, 0.01),
        ]
    )
    decision = evaluate_basket(
        dca_config,
        basket,
        2647.5,
        AggregatedSignal([], 0.0, int(NetSignal.HOLD)),
        account_balance=200.0,
    )
    assert decision.action == BasketAction.CLOSE_BASKET_TP
    assert decision.close_reason == "CORE_BASKET_TP"
    assert decision.close_ticket_ids == ["0", "1", "2"]


def test_total_loss_cut_without_full_stack(dca_config: BotConfig) -> None:
    """Cắt all khi tổng lỗ ≥ 40% balance — không cần đủ 4 lớp."""
    dca_config.max_basket_loss_pct = 40.0
    basket = _basket_sell([(4100.0, 0.01), (4105.0, 0.01)])
    decision = evaluate_basket(
        dca_config,
        basket,
        4150.0,
        AggregatedSignal([], 0.0, int(NetSignal.HOLD)),
        account_balance=150.0,
    )
    assert decision.action == BasketAction.CLOSE_DCA_FULL_STACK_LOSS


def test_unlimited_dca_layers_normal(dca_config: BotConfig) -> None:
    ctx = BasketContext(main_trend=MainTrend.BULLISH)
    layers = [(2650.0 - i * 5, 0.01) for i in range(6)]
    basket = _basket_buy(layers)
    assert effective_max_layers(dca_config, basket, ctx) == 999
    assert should_add_dca_layer(
        dca_config, basket, 2615.0, ctx=ctx, net_pnl_usd=-4.0
    )
