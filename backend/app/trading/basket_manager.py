"""
Quản lý chiến lược Multi-layer Scalping DCA (Bybit Master Trader style).

Mảng vị thế (position tracking array) được nhóm theo cùng chiều (BUY hoặc SELL)
thành một PositionBasket. Mọi quyết định thoát lệnh / nhồi DCA đều dựa trên
metrics tổng hợp của basket, không xử lý từng ticket riêng lẻ khi có > 1 lớp.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.models import BotConfig, OrderSide, TradePosition
from app.trading.risk import resolve_basket_tp_min, resolve_single_tp_min
from app.trading.signal_engine import MainTrend
from app.trading.types import AggregatedSignal, BasketAction, BasketDecision, NetSignal

# Exit / DCA guard constants (P2)
TREND_FLIP_ADVERSE_MIN = 3.0
M5_REVERSAL_EXIT_SCORE = 0.5
BASKET_TIME_STOP_ADVERSE_MIN = 8.0

# P0/P1 guardrails
MAX_BASKET_AGE_MINUTES = 300
BASKET_TRAIL_ACTIVATE_USD = 3.0
BASKET_TRAIL_FLOOR_USD = 1.0


@dataclass
class BasketContext:
    """Market + signal context for basket evaluation."""

    main_trend: MainTrend
    entry_net_raw: int = int(NetSignal.HOLD)
    entry_score: float = 0.0
    is_scalp_mode: bool = False
    atr_value: float | None = None


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
    """
    last = basket.last_layer
    if last is None:
        return 0.0
    if basket.side == OrderSide.BUY:
        return max(0.0, last.entry_price - current_price)
    return max(0.0, current_price - last.entry_price)


def basket_age_minutes(basket: PositionBasket) -> float:
    """Tuổi basket = thời gian từ lớp mở sớm nhất."""
    now = datetime.now(timezone.utc)
    oldest: datetime | None = None
    for layer in basket.layers:
        opened = layer.opened_at
        if opened is None:
            continue
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
        if oldest is None or opened < oldest:
            oldest = opened
    if oldest is None:
        return 0.0
    return (now - oldest).total_seconds() / 60.0


def is_basket_counter_trend(
    basket: PositionBasket,
    main_trend: MainTrend,
) -> bool:
    """True khi basket ngược xu hướng H1."""
    if main_trend == MainTrend.NEUTRAL:
        return False
    if basket.side == OrderSide.BUY and main_trend == MainTrend.BEARISH:
        return True
    if basket.side == OrderSide.SELL and main_trend == MainTrend.BULLISH:
        return True
    return False


def effective_max_layers(
    config: BotConfig,
    basket: PositionBasket,
    ctx: BasketContext,
) -> int:
    """P1: counter-trend / scalp baskets capped at counter_trend_max_layers."""
    base = getattr(config, "max_layers", None) or config.max_open_positions
    counter_cap = getattr(config, "counter_trend_max_layers", 1) or 1
    if is_basket_counter_trend(basket, ctx.main_trend) or ctx.is_scalp_mode:
        return min(base, counter_cap)
    return base


def calculate_layer_pnl_usd(layer: PositionLayer, current_price: float) -> float:
    """P&L chưa thực hiện của một lớp trong basket."""
    if layer.side == OrderSide.BUY:
        return round((current_price - layer.entry_price) * layer.volume * 100, 2)
    return round((layer.entry_price - current_price) * layer.volume * 100, 2)


def resolve_max_basket_age_minutes(config: BotConfig) -> float:
    """Max basket hold time before forced close (default 5 hours)."""
    return float(getattr(config, "max_basket_age_minutes", None) or MAX_BASKET_AGE_MINUTES)


def check_max_basket_age(config: BotConfig, basket: PositionBasket) -> bool:
    """P0: close basket when held too long, regardless of P&L."""
    return basket_age_minutes(basket) >= resolve_max_basket_age_minutes(config)


def resolve_basket_trail_activate_usd(config: BotConfig) -> float:
    return float(
        getattr(config, "basket_trail_activate_usd", None) or BASKET_TRAIL_ACTIVATE_USD
    )


def resolve_basket_trail_floor_usd(config: BotConfig) -> float:
    return float(
        getattr(config, "basket_trail_floor_usd", None) or BASKET_TRAIL_FLOOR_USD
    )


def update_basket_peak_pnl(anchor_position: TradePosition, net_pnl_usd: float) -> float:
    """
    Track peak basket floating P&L on anchor layer (highest_price field).

    Persists across worker restarts so trailing lock survives reloads.
    """
    peak = float(anchor_position.highest_price or 0.0)
    if net_pnl_usd > peak:
        anchor_position.highest_price = round(net_pnl_usd, 2)
        return net_pnl_usd
    return peak


def check_basket_pnl_trail(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
    peak_pnl_usd: float,
) -> bool:
    """P1: lock basket profit — close when P&L retraces to floor after reaching activate."""
    if peak_pnl_usd < resolve_basket_trail_activate_usd(config):
        return False
    net_pnl = calculate_net_pnl_usd(basket, current_price)
    return net_pnl <= resolve_basket_trail_floor_usd(config)


def resolve_max_basket_loss_limit(
    config: BotConfig,
    account_balance: float | None = None,
) -> float:
    """
    Ngưỡng lỗ tối đa basket — ưu tiên % balance (max_basket_loss_pct),
    fallback legacy USD scaled theo vốn.
    """
    balance = account_balance or getattr(config, "base_equity_usd", None) or 200.0
    pct = getattr(config, "max_basket_loss_pct", None)
    if pct is not None and pct > 0:
        return round(balance * pct / 100.0, 2)

    base = getattr(config, "max_basket_loss_usd", 10.0) or 10.0
    ref_raw = getattr(config, "base_equity_usd", None)
    ref = ref_raw if ref_raw and ref_raw > 0 else 200.0
    scale = max(balance / ref, 1.0)
    return round(base * scale, 2)


def resolve_max_basket_loss_usd(
    config: BotConfig,
    account_balance: float | None = None,
) -> float:
    """Alias — dùng resolve_max_basket_loss_limit."""
    return resolve_max_basket_loss_limit(config, account_balance)


# ---------------------------------------------------------------------------
# Joint Take Profit — đóng đồng thời toàn bộ lớp
# ---------------------------------------------------------------------------


def check_joint_take_profit(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
    account_balance: float | None = None,
) -> bool:
    """Joint TP khi basket multi-layer đạt ngưỡng USD."""
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
    """Take Profit lớp đơn (thuận xu thế, chưa DCA)."""
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
    """Black Swan — cắt lỗ khẩn cấp toàn basket (mặc định 12 giá Vàng)."""
    adverse = calculate_adverse_distance(basket, current_price)
    limit = getattr(config, "hard_stop_adverse_distance", 12.0) or 12.0
    return adverse >= limit


def check_per_layer_dca_tp(
    config: BotConfig,
    layer: PositionLayer,
    current_price: float,
    account_balance: float | None = None,
) -> bool:
    """P1: đóng riêng lớp DCA (layer_index >= 1) khi đạt scalp TP min."""
    if layer.layer_index < 1:
        return False
    pnl = calculate_layer_pnl_usd(layer, current_price)
    balance = account_balance or config.base_equity_usd or 200.0
    tp_min = resolve_single_tp_min(config, balance)
    return pnl >= tp_min


def check_position_dca_layer_tp(
    config: BotConfig,
    position: TradePosition,
    current_price: float,
    account_balance: float | None = None,
) -> bool:
    """Wrapper per-ticket cho orchestrator."""
    layer_index = getattr(position, "layer_index", 0) or 0
    if layer_index < 1:
        return False
    layer = PositionLayer(
        ticket_id=position.ticket_id,
        side=position.side,
        volume=position.volume,
        entry_price=position.entry_price,
        layer_index=layer_index,
        opened_at=position.opened_at,
    )
    return check_per_layer_dca_tp(config, layer, current_price, account_balance)


def check_max_basket_loss(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
    account_balance: float | None = None,
) -> bool:
    """Đóng basket khi floating loss vượt cap (% balance hoặc legacy USD)."""
    net_pnl = calculate_net_pnl_usd(basket, current_price)
    limit = resolve_max_basket_loss_limit(config, account_balance)
    return net_pnl <= -limit


# Backward-compatible alias for tests / legacy imports
check_max_basket_loss_usd = check_max_basket_loss


def check_atr_stop(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
    atr_value: float | None,
) -> bool:
    """P2: ATR-based adverse stop from anchor."""
    if atr_value is None or atr_value <= 0:
        return False
    multiplier = getattr(config, "atr_stop_multiplier", 2.0) or 2.0
    adverse = calculate_adverse_distance(basket, current_price)
    return adverse >= atr_value * multiplier


def check_trend_flip_exit(
    basket: PositionBasket,
    ctx: BasketContext,
    adverse: float,
) -> bool:
    """P1/P2: thoát sớm khi H1 đảo ngược basket và đã adverse đủ."""
    if adverse < TREND_FLIP_ADVERSE_MIN:
        return False
    if basket.side == OrderSide.SELL and ctx.main_trend == MainTrend.BULLISH:
        return True
    if basket.side == OrderSide.BUY and ctx.main_trend == MainTrend.BEARISH:
        return True
    return False


def check_m5_reversal_exit(
    basket: PositionBasket,
    ctx: BasketContext,
    net_pnl: float,
) -> bool:
    """P2: M5 momentum flip against open basket while underwater."""
    if net_pnl >= 0:
        return False
    if basket.side == OrderSide.SELL:
        return (
            ctx.entry_net_raw == int(NetSignal.BUY)
            and ctx.entry_score >= M5_REVERSAL_EXIT_SCORE
        )
    if basket.side == OrderSide.BUY:
        return (
            ctx.entry_net_raw == int(NetSignal.SELL)
            and ctx.entry_score <= -M5_REVERSAL_EXIT_SCORE
        )
    return False


def check_time_stop(
    config: BotConfig,
    basket: PositionBasket,
    adverse: float,
    net_pnl: float,
) -> bool:
    """P2: time stop — giữ lệnh lỗ quá lâu với adverse lớn."""
    if net_pnl >= 0:
        return False
    minutes = getattr(config, "basket_time_stop_minutes", 60) or 60
    if basket_age_minutes(basket) < minutes:
        return False
    return adverse >= BASKET_TIME_STOP_ADVERSE_MIN


def should_add_dca_layer(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
    *,
    ctx: BasketContext | None = None,
    net_pnl_usd: float | None = None,
    account_balance: float | None = None,
) -> bool:
    """
    Logic DCA: nhồi lớp tiếp theo khi giá chạy ngược đủ xa.

    P0 catch-up: spacing >= min là đủ (bỏ chặn spacing > max khi giá nhảy nhanh).
    Hủy DCA khi lỗ > 50% max basket loss limit.
    """
    max_layers = (
        effective_max_layers(config, basket, ctx)
        if ctx
        else getattr(config, "max_layers", None) or config.max_open_positions
    )

    if basket.layer_count >= max_layers:
        return False

    if check_hard_stop_loss(config, basket, current_price):
        return False

    if net_pnl_usd is not None:
        max_loss = resolve_max_basket_loss_limit(config, account_balance)
        if net_pnl_usd <= -max_loss * 0.5:
            return False

    spacing = calculate_layer_spacing_distance(basket, current_price)
    spacing_min = getattr(config, "layer_spacing_min", 6.0) or 6.0

    if spacing < spacing_min:
        return False

    return True


def evaluate_basket(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
    signal: AggregatedSignal,
    account_balance: float | None = None,
    *,
    ctx: BasketContext | None = None,
    basket_peak_pnl: float | None = None,
) -> BasketDecision:
    """
    Đánh giá basket tổng hợp — thay thế evaluate_position per-ticket khi DCA.

    Thứ tự ưu tiên (P0–P2):
    1. Trend flip exit
    2. M5 reversal exit
    3. Max USD loss cap
    4. ATR stop
    5. Time stop
    6. Hard stop
    7. Joint TP / Single scalp TP
    8. HOLD
    """
    _ = signal
    if ctx is None:
        ctx = BasketContext(main_trend=MainTrend.NEUTRAL)

    breakeven = calculate_breakeven_price(basket)
    net_pnl = calculate_net_pnl_usd(basket, current_price)
    adverse = calculate_adverse_distance(basket, current_price)

    meta = {
        "layer_count": basket.layer_count,
        "breakeven_price": breakeven,
        "net_pnl_usd": net_pnl,
        "adverse_distance": round(adverse, 2),
        "total_volume": basket.total_volume,
        "basket_age_min": round(basket_age_minutes(basket), 1),
    }

    if check_trend_flip_exit(basket, ctx, adverse):
        return BasketDecision(
            BasketAction.CLOSE_TREND_FLIP,
            close_reason="TREND_FLIP",
            meta=meta,
        )

    if check_max_basket_age(config, basket):
        return BasketDecision(
            BasketAction.CLOSE_MAX_AGE,
            close_reason="MAX_BASKET_AGE",
            meta=meta,
        )

    if check_m5_reversal_exit(basket, ctx, net_pnl):
        return BasketDecision(
            BasketAction.CLOSE_M5_REVERSAL,
            close_reason="M5_REVERSAL",
            meta=meta,
        )

    if check_max_basket_loss(config, basket, current_price, account_balance):
        pct = getattr(config, "max_basket_loss_pct", None)
        reason = (
            BasketAction.CLOSE_MAX_PCT_LOSS
            if pct is not None and pct > 0
            else BasketAction.CLOSE_MAX_USD_LOSS
        )
        return BasketDecision(
            reason,
            close_reason="MAX_BASKET_LOSS",
            meta=meta,
        )

    if basket_peak_pnl is not None and check_basket_pnl_trail(
        config, basket, current_price, basket_peak_pnl
    ):
        meta["basket_peak_pnl"] = round(basket_peak_pnl, 2)
        return BasketDecision(
            BasketAction.CLOSE_BASKET_TRAIL,
            close_reason="BASKET_PNL_TRAIL",
            meta=meta,
        )

    if check_atr_stop(config, basket, current_price, ctx.atr_value):
        return BasketDecision(
            BasketAction.CLOSE_ATR_STOP,
            close_reason="ATR_STOP",
            meta=meta,
        )

    if check_time_stop(config, basket, adverse, net_pnl):
        return BasketDecision(
            BasketAction.CLOSE_TIME_STOP,
            close_reason="TIME_STOP",
            meta=meta,
        )

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
    open_positions: list[TradePosition],
) -> bool:
    """Mở lớp 1 chỉ khi chưa có lệnh cùng chiều (flat basket trên side đó)."""
    if signal.net_signal == int(NetSignal.HOLD):
        return False
    target_side = (
        OrderSide.BUY
        if signal.net_signal == int(NetSignal.BUY)
        else OrderSide.SELL
    )
    if any(p.side == target_side for p in open_positions):
        return False
    return True


def should_open_reversal_hedge_layer(
    signal: AggregatedSignal,
    positions: list[TradePosition],
    *,
    is_scalp_mode: bool,
) -> bool:
    """
    Mở lệnh ngược chiều basket đang giữ khi reversal đạt ngưỡng (scalp).

    Disabled in trend-only mode — hedge adds counter-trend exposure.
    """
    return False


def basket_side_from_signal(signal: AggregatedSignal) -> OrderSide | None:
    if signal.net_signal == int(NetSignal.BUY):
        return OrderSide.BUY
    if signal.net_signal == int(NetSignal.SELL):
        return OrderSide.SELL
    return None
