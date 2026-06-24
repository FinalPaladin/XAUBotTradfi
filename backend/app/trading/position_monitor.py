"""
Đánh giá vị thế trong chế độ DCA Scalping.

- 1 lớp: scalp TP qua basket_manager hoặc broker TP
- Core gồng (layer 0..2): joint close qua evaluate_basket
- Lớp vệ tinh (layer >= 3): chốt lẻ khi đạt TP min
- Multi-layer core: lớp 0 không đóng qua broker TP (orchestrator gỡ TP trên MT5)
"""

from __future__ import annotations

from app.models import BotConfig, OrderSide, TradePosition
from app.trading.basket_manager import (
    check_position_dca_layer_tp,
    effective_core_hold_layers,
)
from app.trading.types import AggregatedSignal, PositionAction, PositionDecision


def evaluate_position(
    config: BotConfig,
    position: TradePosition,
    current_price: float,
    signal: AggregatedSignal,
    *,
    account_balance: float | None = None,
    basket_is_multi_layer: bool = False,
) -> PositionDecision:
    """
    Đánh giá per-ticket; basket joint close vẫn do orchestrator + evaluate_basket.
    """
    _ = signal
    ticket = position.ticket_id
    layer_index = getattr(position, "layer_index", 0) or 0
    core_cap = effective_core_hold_layers(config)

    if layer_index >= core_cap:
        if check_position_dca_layer_tp(
            config, position, current_price, account_balance
        ):
            return PositionDecision(
                PositionAction.CLOSE_DCA_LAYER_TP,
                ticket,
                close_reason="SATELLITE_LAYER_TP",
            )
        return PositionDecision(PositionAction.HOLD, ticket)

    if basket_is_multi_layer:
        return PositionDecision(PositionAction.HOLD, ticket)

    if layer_index >= 1:
        return PositionDecision(PositionAction.HOLD, ticket)

    tp = position.current_tp
    if tp is not None:
        if position.side == OrderSide.BUY and current_price >= tp:
            return PositionDecision(
                PositionAction.CLOSE_TP, ticket, close_reason="SCALP_TP"
            )
        if position.side == OrderSide.SELL and current_price <= tp:
            return PositionDecision(
                PositionAction.CLOSE_TP, ticket, close_reason="SCALP_TP"
            )

    return PositionDecision(PositionAction.HOLD, ticket)
