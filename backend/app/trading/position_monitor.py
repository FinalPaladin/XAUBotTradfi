"""
Đánh giá vị thế trong chế độ DCA Scalping.

- 1 lớp: scalp TP qua basket_manager hoặc broker TP
- Lớp DCA (>=1): đóng riêng khi đạt DCA layer TP (P1)
- Multi-layer: lớp 0 không đóng qua broker TP (orchestrator gỡ TP trên MT5)
"""

from __future__ import annotations

from app.models import BotConfig, OrderSide, TradePosition
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
