"""
Đánh giá vị thế trong chế độ DCA Scalping.

- 1 lớp: scalp TP qua basket_manager (logic chính) hoặc broker TP
- > 1 lớp: KHÔNG đóng từng lệnh — orchestrator gọi evaluate_basket() + close_basket()
"""

from __future__ import annotations

from app.models import BotConfig, OrderSide, TradePosition
from app.trading.types import AggregatedSignal, PositionAction, PositionDecision


def evaluate_position(
    config: BotConfig,
    position: TradePosition,
    current_price: float,
    signal: AggregatedSignal,
) -> PositionDecision:
    """
    Giữ tương thích per-ticket khi cần; DCA multi-layer được xử lý ở orchestrator.

    Với DCA scalping, trailing và signal-reversal per-ticket bị tắt
    (trailing_stop_enabled=False mặc định trong seed mới).
    """
    ticket = position.ticket_id
    layer_index = getattr(position, "layer_index", 0) or 0

    # Lớp DCA (>=1): không đóng riêng lẻ — chờ basket joint close
    if layer_index >= 1:
        return PositionDecision(PositionAction.HOLD, ticket)

    # Lớp 1: broker TP backup nếu đã gắn trên MT5
    tp = position.current_tp
    if tp is not None:
        if position.side == OrderSide.BUY and current_price >= tp:
            return PositionDecision(PositionAction.CLOSE_TP, ticket, close_reason="SCALP_TP")
        if position.side == OrderSide.SELL and current_price <= tp:
            return PositionDecision(PositionAction.CLOSE_TP, ticket, close_reason="SCALP_TP")

    return PositionDecision(PositionAction.HOLD, ticket)
