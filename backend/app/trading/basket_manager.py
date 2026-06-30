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
from app.trading.signal_engine import SCALP_ENTRY_THRESHOLD, MainTrend
from app.trading.trading_mode import (
    effective_core_hold_layers,
    effective_counter_trend_max_layers,
    effective_full_stack_loss_pct,
    effective_layer_spacing_min,
    effective_max_layers as mode_max_layers,
)
from app.trading.types import AggregatedSignal, BasketAction, BasketDecision, NetSignal

# Exit / DCA guard constants (P2)
TREND_FLIP_ADVERSE_MIN = 3.0
M5_REVERSAL_EXIT_SCORE = 0.5
BASKET_TIME_STOP_ADVERSE_MIN = 8.0

# P0/P1 guardrails
MAX_BASKET_AGE_MINUTES = 300
BASKET_TRAIL_ACTIVATE_USD = 3.0
BASKET_TRAIL_FLOOR_USD = 1.0
UNLIMITED_DCA_LAYERS = 999


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
    """DCA cap — NORMAL: không giới hạn; counter-trend / scalp vẫn bị cap."""
    base = mode_max_layers(config)
    counter_cap = effective_counter_trend_max_layers(config)
    if is_basket_counter_trend(basket, ctx.main_trend) or ctx.is_scalp_mode:
        return min(base, counter_cap)
    return base


def core_hold_layers(basket: PositionBasket, config: BotConfig) -> list[PositionLayer]:
    """Lớp 0..N-1 gồng chung — joint TP khi tổng core dương đủ ngưỡng."""
    cap = effective_core_hold_layers(config)
    return [layer for layer in basket.layers if layer.layer_index < cap]


def satellite_layers(basket: PositionBasket, config: BotConfig) -> list[PositionLayer]:
    """Lớp DCA từ index >= core_hold — chốt lẻ khi từng lệnh có lời."""
    cap = effective_core_hold_layers(config)
    return [layer for layer in basket.layers if layer.layer_index >= cap]


def _sub_basket(parent: PositionBasket, layers: list[PositionLayer]) -> PositionBasket:
    return PositionBasket(
        side=parent.side,
        layers=layers,
        anchor_price=parent.anchor_price,
    )


def calculate_core_hold_pnl_usd(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
) -> float:
    core = core_hold_layers(basket, config)
    if not core:
        return 0.0
    return calculate_net_pnl_usd(_sub_basket(basket, core), current_price)


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


def _read_basket_peak_pnl(anchor_position: TradePosition) -> float:
    """Peak floating P&L — must not reuse highest_price (that stores market price)."""
    peak = getattr(anchor_position, "basket_peak_pnl", None)
    if peak is None:
        return 0.0
    return float(peak)


def update_basket_peak_pnl(anchor_position: TradePosition, net_pnl_usd: float) -> float:
    """
    Track peak basket floating P&L on anchor layer (basket_peak_pnl field).

    Persists across worker restarts so trailing lock survives reloads.
    """
    peak = _read_basket_peak_pnl(anchor_position)
    if net_pnl_usd > peak:
        anchor_position.basket_peak_pnl = round(net_pnl_usd, 2)
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


def check_basket_profit_target(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
    account_balance: float | None = None,
) -> bool:
    """Joint close core gồng khi tổng P&L core ≥ basket_tp_min (scale theo balance)."""
    balance = account_balance or config.base_equity_usd or 200.0
    tp_min = resolve_basket_tp_min(config, balance)
    core_pnl = calculate_core_hold_pnl_usd(config, basket, current_price)
    return core_pnl >= tp_min


def check_dca_full_stack_loss(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
    account_balance: float | None = None,
) -> bool:
    """Tổng lỗ basket ≥ % balance → cắt toàn bộ (không cần đủ số lớp)."""
    net_pnl = calculate_net_pnl_usd(basket, current_price)
    if net_pnl >= 0:
        return False
    balance = account_balance or config.base_equity_usd or 200.0
    limit_pct = effective_full_stack_loss_pct(config)
    return net_pnl <= -(balance * limit_pct / 100.0)


def check_joint_take_profit(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
    account_balance: float | None = None,
) -> bool:
    """Alias — dùng check_basket_profit_target."""
    _ = account_balance
    return check_basket_profit_target(config, basket, current_price)


def check_single_layer_scalp_tp(
    config: BotConfig,
    basket: PositionBasket,
    current_price: float,
    account_balance: float | None = None,
) -> bool:
    """Lớp đơn scalp — đóng khi P&L ≥ single_tp_min (mặc định $1, scale theo balance)."""
    if basket.layer_count != 1:
        return False
    net_pnl = calculate_net_pnl_usd(basket, current_price)
    balance = account_balance or config.base_equity_usd or 200.0
    tp_min = resolve_single_tp_min(config, balance)
    return net_pnl >= tp_min


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
    """Đóng riêng lớp DCA vệ tinh (layer_index >= core_hold) khi đạt scalp TP min."""
    if layer.layer_index < effective_core_hold_layers(config):
        return False
    pnl = calculate_layer_pnl_usd(layer, current_price)
    balance = account_balance or config.base_equity_usd or 200.0
    tp_min = resolve_single_tp_min(config, balance)
    return pnl >= tp_min


def check_satellite_layer_tp(
    config: BotConfig,
    layer: PositionLayer,
    current_price: float,
    account_balance: float | None = None,
) -> bool:
    """Alias — lớp DCA sau core gồng."""
    return check_per_layer_dca_tp(config, layer, current_price, account_balance)


def check_position_dca_layer_tp(
    config: BotConfig,
    position: TradePosition,
    current_price: float,
    account_balance: float | None = None,
) -> bool:
    """Wrapper per-ticket — chỉ lớp vệ tinh (index >= core_hold)."""
    layer_index = getattr(position, "layer_index", 0) or 0
    if layer_index < effective_core_hold_layers(config):
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


def check_panic_signal_exit(
    basket: PositionBasket,
    ctx: BasketContext,
    *,
    threshold: float = SCALP_ENTRY_THRESHOLD,
) -> bool:
    """
    Tín hiệu M5 panic ngược chiều basket — đóng hết mọi lớp ngay.

    Long basket + score <= -0.8 (panic sell) hoặc Short + score >= 0.8 (panic buy).
    """
    if basket.side == OrderSide.BUY:
        return ctx.entry_score <= -threshold
    if basket.side == OrderSide.SELL:
        return ctx.entry_score >= threshold
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

    Không giới hạn số lớp (NORMAL). Hủy DCA khi lỗ > 50% max basket loss limit.
    """
    max_layers = (
        effective_max_layers(config, basket, ctx)
        if ctx
        else mode_max_layers(config)
    )

    if basket.layer_count >= max_layers:
        return False

    if net_pnl_usd is not None:
        max_loss = resolve_max_basket_loss_limit(config, account_balance)
        if net_pnl_usd <= -max_loss * 0.5:
            return False

    spacing = calculate_layer_spacing_distance(basket, current_price)
    spacing_min = effective_layer_spacing_min(config)

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
    Đánh giá basket — 3 rule thoát:

    1. Tổng lỗ basket ≥ % balance (40%) → đóng hết
    2. Core gồng (≤3 lớp đầu) P&L ≥ basket TP → đóng core (giữ vệ tinh nếu có)
    3. Lớp vệ tinh (index ≥ 3) — chốt lẻ qua position_monitor
    """
    _ = signal
    if ctx is None:
        ctx = BasketContext(main_trend=MainTrend.NEUTRAL)

    breakeven = calculate_breakeven_price(basket)
    net_pnl = calculate_net_pnl_usd(basket, current_price)
    core_pnl = calculate_core_hold_pnl_usd(config, basket, current_price)
    adverse = calculate_adverse_distance(basket, current_price)
    core = core_hold_layers(basket, config)

    meta = {
        "layer_count": basket.layer_count,
        "core_layer_count": len(core),
        "satellite_layer_count": len(satellite_layers(basket, config)),
        "breakeven_price": breakeven,
        "net_pnl_usd": net_pnl,
        "core_pnl_usd": core_pnl,
        "adverse_distance": round(adverse, 2),
        "total_volume": basket.total_volume,
        "basket_age_min": round(basket_age_minutes(basket), 1),
    }

    if check_dca_full_stack_loss(config, basket, current_price, account_balance):
        meta["full_stack_loss_pct"] = effective_full_stack_loss_pct(config)
        return BasketDecision(
            BasketAction.CLOSE_DCA_FULL_STACK_LOSS,
            close_reason="DCA_FULL_STACK_LOSS",
            meta=meta,
        )

    balance = account_balance or config.base_equity_usd or 200.0
    scalp_single = ctx.is_scalp_mode and basket.layer_count == 1
    tp_hit = (
        check_single_layer_scalp_tp(config, basket, current_price, balance)
        if scalp_single
        else check_basket_profit_target(config, basket, current_price, balance)
    )
    if core and tp_hit:
        tp_min = (
            resolve_single_tp_min(config, balance)
            if scalp_single
            else resolve_basket_tp_min(config, balance)
        )
        core_tickets = [layer.ticket_id for layer in core]
        meta["core_pnl_usd"] = core_pnl
        meta["basket_tp_min_usd"] = tp_min
        close_reason = "CLOSE_SINGLE_SCALP" if scalp_single else "CORE_BASKET_TP"
        return BasketDecision(
            BasketAction.CLOSE_BASKET_TP,
            close_reason=close_reason,
            meta=meta,
            close_ticket_ids=core_tickets,
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
