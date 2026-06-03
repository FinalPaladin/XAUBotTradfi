"""Evaluate open positions: HOLD, trailing modify, or close."""

from __future__ import annotations

from app.models import BotConfig, OrderSide, TradePosition
from app.trading.risk import trailing_sl_price
from app.trading.types import AggregatedSignal, NetSignal, PositionAction, PositionDecision


def evaluate_position(
    config: BotConfig,
    position: TradePosition,
    current_price: float,
    signal: AggregatedSignal,
) -> PositionDecision:
    ticket = position.ticket_id

    if position.side == OrderSide.BUY:
        position.highest_price = max(
            position.highest_price or position.entry_price, current_price
        )
        extreme = position.highest_price
    else:
        position.lowest_price = min(
            position.lowest_price or position.entry_price, current_price
        )
        extreme = position.lowest_price

    sl = position.current_sl
    tp = position.current_tp

    if sl is not None:
        if position.side == OrderSide.BUY and current_price <= sl:
            return PositionDecision(PositionAction.CLOSE_SL, ticket, close_reason="SL")
        if position.side == OrderSide.SELL and current_price >= sl:
            return PositionDecision(PositionAction.CLOSE_SL, ticket, close_reason="SL")

    if tp is not None:
        if position.side == OrderSide.BUY and current_price >= tp:
            return PositionDecision(PositionAction.CLOSE_TP, ticket, close_reason="TP")
        if position.side == OrderSide.SELL and current_price <= tp:
            return PositionDecision(PositionAction.CLOSE_TP, ticket, close_reason="TP")

    if config.trailing_stop_enabled:
        new_sl = trailing_sl_price(
            config, position.side, position.entry_price, extreme, sl
        )
        if new_sl is not None:
            if sl is not None:
                if position.side == OrderSide.BUY and current_price <= new_sl:
                    return PositionDecision(
                        PositionAction.CLOSE_TRAIL, ticket, close_reason="TRAIL"
                    )
                if position.side == OrderSide.SELL and current_price >= new_sl:
                    return PositionDecision(
                        PositionAction.CLOSE_TRAIL, ticket, close_reason="TRAIL"
                    )
            return PositionDecision(
                PositionAction.MODIFY_TRAIL, ticket, new_sl=new_sl
            )

    opposite = (
        position.side == OrderSide.BUY
        and signal.net_signal == int(NetSignal.SELL)
    ) or (
        position.side == OrderSide.SELL
        and signal.net_signal == int(NetSignal.BUY)
    )
    if opposite and abs(signal.weighted_score) >= config.signal_threshold:
        return PositionDecision(
            PositionAction.CLOSE_SIGNAL, ticket, close_reason="SIGNAL"
        )

    return PositionDecision(PositionAction.HOLD, ticket)
