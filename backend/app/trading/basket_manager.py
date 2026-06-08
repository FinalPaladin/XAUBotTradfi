"""
Quản lý chiến lược Multi-layer Scalping DCA (Bybit Master Trader style).

Mảng vị thế (position tracking array) được nhóm theo cùng chiều (BUY hoặc SELL)
thành một PositionBasket. Mọi quyết định thoát lệnh / nhồi DCA đều dựa trên
metrics tổng hợp của basket, không xử lý từng ticket riêng lẻ khi có > 1 lớp.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import BotConfig, OrderSide, TradePosition
from app.trading.risk import resolve_basket_tp_min, resolve_single_tp_min
from app.trading.types import AggregatedSignal, BasketAction, BasketDecision, NetSignal


# ---------------------------------------------------------------------------
# Position tracking array — mảng chứa các lớp lệnh đang mở
# ---------------------------------------------------------------------------


@dataclass
class PositionLayer:
    """Một lớp lệnh trong basket DCA."""

    ticket_id: str
    side: OrderSide
    volume: float
    entry_price: float
    layer_index: int  # 0 = lớp đầu tiên, 1..N = các lớp DCA tiếp theo
    opened_at: object | None = None


@dataclass
class PositionBasket:
    """
    Mảng tracking tổng hợp: gom tất cả TradePosition cùng chiều của một bot.

    Chỉ hỗ trợ một basket active tại một thời điểm (một chiều BUY hoặc SELL).
    """

    side: OrderSide
    layers: list[PositionLayer] = field(default_factory=list)
    anchor_price: float = 0.0  # giá entry lớp đầu tiên — dùng tính khoảng cách adverse

    @property
    def layer_count(self) -> int:
        return len(self.layers)

    @property
    def total_volume(self) -> float:
        return sum(layer.volume for layer in self.layers)

    @property
    def last_layer(self) -> PositionLayer | None:
        return self.layers[-1] if self.layers else None

    @property
    def is_multi_layer(self) -> bool:
        """True khi đã nhồi DCA (> 1 lớp) — bật chế độ Joint Close."""
        return self.layer_count > 1


def build_position_basket(positions: list[TradePosition]) -> PositionBasket | None:
    """
    Xây dựng PositionBasket từ danh sách TradePosition trong DB.

    Trả về None nếu không có lệnh mở. Nếu có lệnh hai chiều (lỗi sync),
    ưu tiên chiều có nhiều lớp hơn.
    """
    if not positions:
        return None

    buys = [p for p in positions if p.side == OrderSide.BUY]
    sells = [p for p in positions if p.side == OrderSide.SELL]
    active = buys if len(buys) >= len(sells) else sells
    if not active:
        return None

    side = active[0].side
    sorted_positions = sorted(
        active,
        key=lambda p: (getattr(p, "layer_index", 0) or 0, p.opened_at),
    )

    layers: list[PositionLayer] = []
    for idx, pos in enumerate(sorted_positions):
        layers.append(
            PositionLayer(
                ticket_id=pos.ticket_id,
                side=pos.side,
                volume=pos.volume,
                entry_price=pos.entry_price,
                layer_index=getattr(pos, "layer_index", None) or idx,
                opened_at=pos.opened_at,
            )
        )

    anchor = getattr(sorted_positions[0], "basket_anchor_price", None)
    if anchor is None:
        anchor = sorted_positions[0].entry_price

    return PositionBasket(side=side, layers=layers, anchor_price=float(anchor))


# ---------------------------------------------------------------------------
# Giá hòa vốn tổng (Average Breakeven Price)
# ---------------------------------------------------------------------------


def calculate_breakeven_price(basket: PositionBasket) -> float:
    """
    Tính giá hòa vốn trung bình có trọng số theo volume cho toàn bộ basket.

    Công thức: BE = Σ(entry_i × volume_i) / Σ(volume_i)

    Với lệnh BUY: khi giá hiện tại >= BE → basket hòa vốn trở lên.
    Với lệnh SELL: khi giá hiện tại <= BE → basket hòa vốn trở lên.
    """
    total_vol = basket.total_volume
    if total_vol <= 0:
        return 0.0

    weighted_sum = sum(layer.entry_price * layer.volume for layer in basket.layers)
    return round(weighted_sum / total_vol, 2)


def calculate_net_pnl_usd(basket: PositionBasket, current_price: float) -> float:
    """
    Tính P&L chưa thực hiện (USD) tổng của toàn bộ các lớp trong basket.

    XAUUSD: mỗi 1 lot = 100 oz → PnL ≈ (price_diff) × volume × 100.
    """
    total = 0.0
    for layer in basket.layers:
        if layer.side == OrderSide.BUY:
            total += (current_price - layer.entry_price) * layer.volume * 100
        else:
            total += (layer.entry_price - current_price) * layer.volume * 100
    return round(total, 2)


def calculate_adverse_distance(
    basket: PositionBasket, current_price: float
) -> float:
    """
    Khoảng cách giá chạy ngược từ anchor (lớp 1) tính bằng 'giá Vàng'.

    BUY: adverse khi giá giảm → anchor - current_price
    SELL: adverse khi giá tăng → current_price - anchor
    """
    if basket.side == OrderSide.BUY:
        return max(0.0, basket.anchor_price - current_price)
    return max(0.0, current_price - basket.anchor_price)


def calculate_layer_spacing_distance(
    basket: PositionBasket, current_price: float
) -> float:
    """
    Khoảng cách adverse từ lớp cuối cùng (dùng để quyết định nhồi DCA tiếp).

    Chỉ nhồi lớp mới khi khoảng cách này >= layer_spacing_min (5 giá Vàng).
    """
    last = basket.last_layer
    if last is None:
        return 0.0
    if basket.side == OrderSide.BUY:
        return max(0.0, last.entry_price - current_price)
    return max(0.0, current_price - last.entry_price)


# ---------------------------------------------------------------------------
# Joint Take Profit — đóng đồng thời toàn bộ lớp
# ---------------------------------------------------------------------------


def check_joint_take_profit(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
    account_balance: float | None = None,
) -> bool:
    """
    Kiểm tra điều kiện thoát hiểm tổng (Basket Take Profit / Joint Close).

    Chỉ áp dụng khi basket có > 1 lớp (is_multi_layer / gồng DCA).
    Ngưỡng TP scale theo số dư thực ($2 UI @ $200 → $100 @ $10,000).
    """
    if not basket.is_multi_layer:
        return False

    net_pnl = calculate_net_pnl_usd(basket, current_price)
    balance = account_balance or config.base_equity_usd or 200.0
    tp_min = resolve_basket_tp_min(config, balance)

    return net_pnl >= tp_min


def check_single_layer_scalp_tp(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
    account_balance: float | None = None,
) -> bool:
    """
    Take Profit lớp đơn (thuận xu thế, chưa DCA).

    Ngưỡng USD scale theo số dư; fallback khoảng cách giá Vàng.
    """
    if basket.layer_count != 1:
        return False

    net_pnl = calculate_net_pnl_usd(basket, current_price)
    balance = account_balance or config.base_equity_usd or 200.0
    tp_min = resolve_single_tp_min(config, balance)

    if net_pnl >= tp_min:
        return True

    layer = basket.layers[0]
    scalp_dist = config.single_tp_distance or 1.2

    if layer.side == OrderSide.BUY:
        return current_price >= layer.entry_price + scalp_dist
    return current_price <= layer.entry_price - scalp_dist


def check_hard_stop_loss(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
) -> bool:
    """
    Black Swan Protection — cắt lỗ khẩn cấp toàn basket.

    Nếu giá chạy ngược từ anchor vượt hard_stop_adverse_distance (mặc định 35 giá Vàng)
    mà chưa hồi, đóng toàn bộ lệnh để bảo vệ số dư isolated (~200U).
    """
    adverse = calculate_adverse_distance(basket, current_price)
    limit = getattr(config, "hard_stop_adverse_distance", 35.0) or 35.0
    return adverse >= limit


def should_add_dca_layer(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
) -> bool:
    """
    Logic DCA Martingale nén: nhồi lớp tiếp theo khi giá chạy ngược đủ xa.

    Điều kiện:
    - Chưa đạt max_layers (mặc định 5)
    - Khoảng cách từ lớp cuối >= layer_spacing_min (5 giá Vàng, tối đa 7)
    - Không vượt hard stop (35 giá) — nếu vượt thì cắt lỗ, không nhồi thêm
    """
    max_layers = getattr(config, "max_layers", None) or config.max_open_positions
    if basket.layer_count >= max_layers:
        return False

    if check_hard_stop_loss(config, basket, current_price):
        return False

    spacing = calculate_layer_spacing_distance(basket, current_price)
    spacing_min = getattr(config, "layer_spacing_min", 5.0) or 5.0
    return spacing >= spacing_min


def evaluate_basket(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
    signal: AggregatedSignal,
    account_balance: float | None = None,
) -> BasketDecision:
    """
    Đánh giá basket tổng hợp — thay thế evaluate_position per-ticket khi DCA.

    Thứ tự ưu tiên:
    1. Hard Stop (Black Swan) → CLOSE_HARD_STOP
    2. Joint TP (multi-layer) → CLOSE_BASKET_TP
    3. Single scalp TP (1 lớp) → CLOSE_SINGLE_SCALP
    4. Giữ lệnh → HOLD
    """
    breakeven = calculate_breakeven_price(basket)
    net_pnl = calculate_net_pnl_usd(basket, current_price)
    adverse = calculate_adverse_distance(basket, current_price)

    meta = {
        "layer_count": basket.layer_count,
        "breakeven_price": breakeven,
        "net_pnl_usd": net_pnl,
        "adverse_distance": round(adverse, 2),
        "total_volume": basket.total_volume,
    }

    if check_hard_stop_loss(config, basket, current_price):
        return BasketDecision(
            BasketAction.CLOSE_HARD_STOP,
            close_reason="HARD_STOP",
            meta=meta,
        )

    if check_joint_take_profit(config, basket, current_price, account_balance):
        return BasketDecision(
            BasketAction.CLOSE_BASKET_TP,
            close_reason="BASKET_TP",
            meta=meta,
        )

    if check_single_layer_scalp_tp(config, basket, current_price, account_balance):
        return BasketDecision(
            BasketAction.CLOSE_SINGLE_SCALP,
            close_reason="SCALP_TP",
            meta=meta,
        )

    return BasketDecision(BasketAction.HOLD, meta=meta)


def should_open_initial_layer(
    signal: AggregatedSignal,
    open_count: int,
) -> bool:
    """Mở lớp 1 khi flat và có tín hiệu BUY/SELL từ aggregator."""
    return open_count == 0 and signal.net_signal != int(NetSignal.HOLD)


def basket_side_from_signal(signal: AggregatedSignal) -> OrderSide | None:
    if signal.net_signal == int(NetSignal.BUY):
        return OrderSide.BUY
    if signal.net_signal == int(NetSignal.SELL):
        return OrderSide.SELL
    return None
