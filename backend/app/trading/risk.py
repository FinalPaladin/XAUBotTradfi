"""
Quản lý vốn: lot cố định theo nấc tài khoản + scale TP theo số dư thực tế.

Công thức lot: max(0.01, floor(balance / 1000) × 0.01)
Ví dụ $10,000 → 0.10 lot mỗi lệnh mới.
"""

from __future__ import annotations

import math

from app.models import BotConfig, OrderSide
from app.services.mt5_client import get_mt5_client
from app.trading.types import AggregatedSignal, NetSignal, OrderPlan


def resolve_account_balance(equity_fallback: float | None = None) -> float:
    """Số dư thực tế từ MT5; fallback equity nếu balance không có."""
    client = get_mt5_client()
    balance = client.account_balance()
    if balance > 0:
        return balance
    if equity_fallback and equity_fallback > 0:
        return equity_fallback
    equity = client.account_equity()
    return equity if equity > 0 else 200.0


def capital_scale_factor(
    account_balance: float,
    reference_equity: float,
) -> float:
    """
    Hệ số scale so với vốn gốc tham chiếu UI (mặc định $200).

    $10,000 / $200 = 50× → TP $2 UI thành $100 thực tế.
    """
    ref = reference_equity if reference_equity and reference_equity > 0 else 200.0
    bal = account_balance if account_balance and account_balance > 0 else ref
    return max(bal / ref, 1.0)


def dynamic_base_equity(account_balance: float) -> float:
    """Vốn gốc tham chiếu động = số dư tài khoản hiện tại."""
    return account_balance


def dynamic_first_layer_notional(config: BotConfig, account_balance: float) -> float:
    """
    Notional lớp 1 động — giữ tỷ lệ UI (6750/200) theo số dư thực.

    Dùng cho hiển thị / tham chiếu; volume thực tế theo fixed lot.
    """
    ref = config.base_equity_usd if config.base_equity_usd > 0 else 200.0
    ratio = config.first_layer_notional_usd / ref
    return round(account_balance * ratio, 2)


def scaled_tp_usd(
    config_tp_usd: float,
    account_balance: float,
    reference_equity: float,
) -> float:
    """Scale mục tiêu TP USD từ UI lên theo số dư thực tế."""
    scale = capital_scale_factor(account_balance, reference_equity)
    return round(config_tp_usd * scale, 2)


def scaled_tp_pct_of_balance(
    target_pct: float,
    account_balance: float,
) -> float:
    """Mục tiêu TP theo % số dư tài khoản (ví dụ 0.1% balance)."""
    return round(account_balance * (target_pct / 100.0), 2)


def resolve_basket_tp_min(
    config: BotConfig,
    account_balance: float,
) -> float:
    """Joint TP min — scale từ UI hoặc tối thiểu 0.02% balance."""
    scaled = scaled_tp_usd(
        config.basket_tp_min_usd,
        account_balance,
        config.base_equity_usd,
    )
    pct_floor = scaled_tp_pct_of_balance(0.02, account_balance)
    return max(scaled, pct_floor)


def resolve_single_tp_min(
    config: BotConfig,
    account_balance: float,
) -> float:
    """Scalp TP min — scale từ UI hoặc tối thiểu 0.01% balance."""
    scaled = scaled_tp_usd(
        config.single_tp_min_usd,
        account_balance,
        config.base_equity_usd,
    )
    pct_floor = scaled_tp_pct_of_balance(0.01, account_balance)
    return max(scaled, pct_floor)


def calculate_fixed_lot_size(account_balance: float) -> float:
    """
    Lot cố định theo nấc $1,000 vốn.

    floor(balance/1000) × 0.01, tối thiểu 0.01 lot.
    $10,000 → 0.10 lot.
    """
    tiers = math.floor(account_balance / 1000.0)
    lot = tiers * 0.01
    return max(0.01, round(lot, 2))


def _clamp_volume(symbol: str, volume: float) -> float:
    client = get_mt5_client()
    info = client.symbol_info(symbol)
    if info is None:
        return max(0.01, round(volume, 2))
    volume = max(info.volume_min, min(info.volume_max, volume))
    if info.volume_step > 0:
        volume = round(volume / info.volume_step) * info.volume_step
    return volume


def calculate_layer_volume(
    config: BotConfig,
    entry_price: float,
    layer_index: int,
    account_balance: float | None = None,
) -> float:
    """
    Volume cố định theo nấc vốn — không dùng đòn bẩy / Martingale.

    Mọi lớp DCA dùng cùng lot size tại thời điểm mở.
    """
    _ = entry_price, layer_index
    balance = account_balance if account_balance else resolve_account_balance()
    volume = calculate_fixed_lot_size(balance)
    return _clamp_volume(config.symbol, volume)


def build_layer_plan(
    config: BotConfig,
    side: OrderSide,
    entry_price: float,
    layer_index: int = 0,
    basket_anchor_price: float | None = None,
    account_balance: float | None = None,
) -> OrderPlan | None:
    """
    Tạo OrderPlan cho một lớp.

    Lớp 0: broker TP theo scalp distance (đã scale theo balance).
    Lớp 1+: không gắn SL/TP broker — thoát bằng Joint Close basket.
    """
    balance = account_balance if account_balance else resolve_account_balance()
    volume = calculate_layer_volume(config, entry_price, layer_index, balance)
    if volume <= 0:
        return None

    anchor = basket_anchor_price if basket_anchor_price is not None else entry_price
    use_broker_sl_tp = layer_index == 0

    sl_price: float | None = None
    tp_price: float | None = None

    if use_broker_sl_tp:
        tp_min_usd = resolve_single_tp_min(config, balance)
        if volume > 0:
            scalp_dist = max(tp_min_usd / (volume * 100.0), config.single_tp_distance)
        else:
            scalp_dist = config.single_tp_distance
        if side == OrderSide.BUY:
            tp_price = round(entry_price + scalp_dist, 2)
        else:
            tp_price = round(entry_price - scalp_dist, 2)

    return OrderPlan(
        side=side,
        volume=volume,
        entry_price=entry_price,
        sl_price=sl_price,
        tp_price=tp_price,
        symbol=config.symbol,
        magic=config.magic_number,
        comment=f"XAUBot-L{layer_index + 1}",
        layer_index=layer_index,
        basket_anchor_price=anchor,
        use_broker_sl_tp=use_broker_sl_tp,
    )


def build_order_plan(
    config: BotConfig,
    signal: AggregatedSignal,
    entry_price: float,
    equity: float | None = None,
) -> OrderPlan | None:
    """Mở lớp 1 từ tín hiệu aggregator / signal engine."""
    if signal.net_signal == int(NetSignal.HOLD):
        return None
    side = OrderSide.BUY if signal.net_signal == int(NetSignal.BUY) else OrderSide.SELL
    balance = resolve_account_balance(equity)
    return build_layer_plan(
        config,
        side,
        entry_price,
        layer_index=0,
        account_balance=balance,
    )


def trailing_sl_price(
    config: BotConfig,
    side: OrderSide,
    entry_price: float,
    extreme_price: float,
    current_sl: float | None,
) -> float | None:
    """Trailing stop — tắt mặc định trong chế độ DCA scalping."""
    if not config.trailing_stop_enabled or not config.trailing_stop_pct:
        return None

    trail_dist = extreme_price * (config.trailing_stop_pct / 100.0)
    if side == OrderSide.BUY:
        new_sl = extreme_price - trail_dist
        if current_sl is not None and new_sl <= current_sl:
            return None
        return round(new_sl, 2)
    new_sl = extreme_price + trail_dist
    if current_sl is not None and new_sl >= current_sl:
        return None
    return round(new_sl, 2)
