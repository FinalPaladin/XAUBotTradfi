"""Position sizing and SL/TP/trailing price calculation."""

from __future__ import annotations

from app.models import BotConfig, OrderSide
from app.trading.types import AggregatedSignal, NetSignal, OrderPlan
from app.services.mt5_client import get_mt5_client


def _pct_distance(price: float, pct: float) -> float:
    return price * (pct / 100.0)


def build_order_plan(
    config: BotConfig,
    signal: AggregatedSignal,
    entry_price: float,
    equity: float | None = None,
) -> OrderPlan | None:
    if signal.net_signal == int(NetSignal.HOLD):
        return None

    side = OrderSide.BUY if signal.net_signal == int(NetSignal.BUY) else OrderSide.SELL
    sl_dist = _pct_distance(entry_price, config.stop_loss_pct)
    tp_dist = _pct_distance(entry_price, config.take_profit_pct)

    if side == OrderSide.BUY:
        sl_price = entry_price - sl_dist
        tp_price = entry_price + tp_dist
    else:
        sl_price = entry_price + sl_dist
        tp_price = entry_price - tp_dist

    volume = _calculate_volume(config, entry_price, sl_dist, equity)
    if volume <= 0:
        return None

    return OrderPlan(
        side=side,
        volume=volume,
        entry_price=entry_price,
        sl_price=round(sl_price, 2),
        tp_price=round(tp_price, 2),
        symbol=config.symbol,
        magic=config.magic_number,
        comment=f"XAUBot-{config.name}",
    )


def _calculate_volume(
    config: BotConfig,
    entry_price: float,
    stop_distance: float,
    equity: float | None,
) -> float:
    client = get_mt5_client()
    info = client.symbol_info(config.symbol)
    eq = equity if equity is not None else client.account_equity()
    if eq <= 0 or stop_distance <= 0:
        return 0.01

    risk_amount = eq * (config.risk_per_trade_pct / 100.0)
    if info is not None and info.trade_tick_size and info.trade_tick_value:
        ticks = stop_distance / info.trade_tick_size
        tick_value = info.trade_tick_value
        if ticks > 0 and tick_value > 0:
            volume = risk_amount / (ticks * tick_value)
        else:
            volume = risk_amount / (stop_distance * 100)
    else:
        volume = risk_amount / (stop_distance * 100)

    if info is not None:
        volume = max(info.volume_min, min(info.volume_max, volume))
        if info.volume_step > 0:
            volume = round(volume / info.volume_step) * info.volume_step
    else:
        volume = max(0.01, round(volume, 2))
    return volume


def trailing_sl_price(
    config: BotConfig,
    side: OrderSide,
    entry_price: float,
    extreme_price: float,
    current_sl: float | None,
) -> float | None:
    if not config.trailing_stop_enabled or not config.trailing_stop_pct:
        return None

    trail_dist = _pct_distance(extreme_price, config.trailing_stop_pct)
    if side == OrderSide.BUY:
        new_sl = extreme_price - trail_dist
        if current_sl is not None and new_sl <= current_sl:
            return None
        return round(new_sl, 2)
    new_sl = extreme_price + trail_dist
    if current_sl is not None and new_sl >= current_sl:
        return None
    return round(new_sl, 2)
