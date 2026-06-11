"""
Genetic Algorithm (GA) Optimizer — tìm bộ tham số trading tối ưu trên dữ liệu lịch sử.

Module độc lập, không ảnh hưởng worker live. Chỉ import logic tính toán từ:
  - app.trading.aggregator
  - app.trading.signal_engine (bộ lọc đa khung)
  - app.trading.basket_manager
  - app.trading.drawdown_guard

Chạy:
  cd backend
  python -m app.trading.optimizer_ga --generations 20 --population 30
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Any

import pandas as pd

from app.models import BotConfig, BotStatus, OrderSide
from app.seed import _default_xauusd_bot
from app.trading.aggregator import aggregate_signal, atr_volatility_factor
from app.trading.basket_manager import (
    BasketContext,
    PositionBasket,
    PositionLayer,
    build_position_basket,
    calculate_net_pnl_usd,
    effective_max_layers,
    evaluate_basket,
    should_add_dca_layer,
    should_open_initial_layer,
    should_open_reversal_hedge_layer,
)
from app.trading.drawdown_guard import (
    DD_PANIC_THRESHOLD_PCT,
    DD_PARTIAL_THRESHOLD_PCT,
    current_drawdown_percent,
)
from app.trading.risk import SCALP_VOLUME_MULTIPLIER, calculate_fixed_lot_size
from app.trading.signal_engine import (
    MainTrend,
    _filter_entry_signal,
    _resolve_main_trend,
)
from app.trading.types import AggregatedSignal, BasketAction, NetSignal

# ---------------------------------------------------------------------------
# Đường dẫn mặc định (tương đối thư mục backend hoặc project root)
# ---------------------------------------------------------------------------

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent

DEFAULT_H1_CSV = "data/xauusd_h1.csv"
DEFAULT_M5_CSV = "data/xauusd_m5.csv"
DEFAULT_OUTPUT_JSON = "best_bot_config.json"
DEFAULT_WORKERS = cpu_count() or 1

# Cột chuẩn MT5 / export phổ biến → tên nội bộ
MT5_COLUMN_ALIASES: dict[str, str] = {
    "date": "date_part",
    "datetime": "time",
    "timestamp": "time",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "tick_volume": "tick_volume",
    "tickvolume": "tick_volume",
    "tick_vol": "tick_volume",
    "volume": "tick_volume",
    "vol": "tick_volume",
    "spread": "spread",
    "real_volume": "real_volume",
    "realvolume": "real_volume",
}

BASE_CONFIG_ATTRS = (
    "symbol", "timeframe", "bars_lookback", "max_layers", "max_open_positions",
    "base_equity_usd", "signal_threshold", "donchian_period", "supertrend_period",
    "supertrend_multiplier", "rsi_period", "rsi_overbought", "rsi_oversold",
    "ema_period", "rsi_swing_lookback", "basket_tp_min_usd", "single_tp_min_usd",
    "hard_stop_adverse_distance", "layer_spacing_max", "magic_number",
)

# Shared state trong worker process (set bởi pool initializer)
_MP_DF_H1: pd.DataFrame | None = None
_MP_DF_M5: pd.DataFrame | None = None
_MP_BASE_SNAPSHOT: dict[str, Any] | None = None
_MP_INITIAL_BALANCE: float = 200.0

# Giới hạn gene theo yêu cầu
SINGLE_TP_MIN = 0.5
SINGLE_TP_MAX = 3.0
LAYER_SPACING_MIN = 3.0
LAYER_SPACING_MAX = 10.0
WEIGHT_MIN = 0.05
WEIGHT_MAX = 0.60

# Ngưỡng drawdown khẩn cấp (giống drawdown_guard.py)
DD_PARTIAL_THRESHOLD_PCT = 40.0
DD_PANIC_THRESHOLD_PCT = 60.0


# ---------------------------------------------------------------------------
# 1. Load dữ liệu OHLCV từ CSV
# ---------------------------------------------------------------------------


def _resolve_data_path(relative: str) -> Path:
    """
    Tìm file CSV theo thứ tự ưu tiên:
      1. Đường dẫn tuyệt đối / tương đối cwd
      2. backend/data/… (mặc định khi chạy từ backend/)
      3. project_root/data/…
    """
    rel = Path(relative)
    candidates = [
        rel,
        Path.cwd() / rel,
        BACKEND_ROOT / rel,
        BACKEND_ROOT / "data" / rel.name,
        PROJECT_ROOT / rel,
        PROJECT_ROOT / "data" / rel.name,
    ]
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path.resolve()
    raise FileNotFoundError(
        f"Không tìm thấy {relative}. Đã thử: {[str(p) for p in candidates]}"
    )


def _normalize_column_name(name: str) -> str:
    """Chuẩn hóa tên cột MT5: <OPEN>, Tick Volume, Date → open, tick_volume, date."""
    key = str(name).strip().lower()
    key = key.replace("<", "").replace(">", "").replace(" ", "_")
    while "__" in key:
        key = key.replace("__", "_")
    return MT5_COLUMN_ALIASES.get(key, key)


def _normalize_csv_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map cột CSV MT5 (nhiều biến thể tên) về schema nội bộ thống nhất."""
    df = df.copy()
    df.columns = [_normalize_column_name(c) for c in df.columns]

    # MT5: Date + Time riêng (Time thường chỉ HH:MM:SS)
    if "date_part" in df.columns and "time" in df.columns:
        time_sample = str(df["time"].iloc[0]).strip()
        if len(time_sample) <= 8 and ":" in time_sample:
            combined = (
                df["date_part"].astype(str).str.strip()
                + " "
                + df["time"].astype(str).str.strip()
            )
            df["time"] = pd.to_datetime(combined, utc=True, errors="coerce", dayfirst=False)
        else:
            df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce", dayfirst=False)
    elif "date_part" in df.columns and "time" not in df.columns:
        df["time"] = pd.to_datetime(df["date_part"], utc=True, errors="coerce", dayfirst=False)
    elif "time" in df.columns and df["time"].dtype == object:
        cleaned = df["time"].astype(str).str.replace(",", " ", regex=False)
        df["time"] = pd.to_datetime(cleaned, utc=True, errors="coerce", dayfirst=False)

    for price_col in ("open", "high", "low", "close"):
        if price_col in df.columns:
            df[price_col] = pd.to_numeric(df[price_col], errors="coerce")

    if "tick_volume" in df.columns:
        df["tick_volume"] = pd.to_numeric(df["tick_volume"], errors="coerce").fillna(0)

    return df


def load_ohlcv_csv(path: str | Path) -> pd.DataFrame:
    """
    Đọc CSV OHLCV (MT5 export hoặc tương đương).

    Hỗ trợ tên cột: time/datetime/date+time, open/high/low/close,
    tick_volume/volume/vol, spread, real_volume (hoặc <OPEN>, <TICK_VOLUME>, …).
    """
    raw_path = Path(path)
    file_path = raw_path if raw_path.is_file() else _resolve_data_path(str(path))

    # MT5 export có thể dùng tab hoặc semicolon
    df = pd.read_csv(file_path, sep=None, engine="python")
    df = _normalize_csv_columns(df)

    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"CSV thiếu cột OHLC {missing}: {file_path}. "
            f"Cột hiện có: {list(df.columns)}"
        )

    if "time" not in df.columns:
        raise ValueError(
            f"CSV cần cột thời gian (time/datetime hoặc date+time): {file_path}. "
            f"Cột hiện có: {list(df.columns)}"
        )

    if not pd.api.types.is_datetime64_any_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")

    df = df.dropna(subset=["time", "open", "high", "low", "close"])
    df = df.sort_values("time").reset_index(drop=True)

    for col in ("tick_volume", "spread", "real_volume"):
        if col not in df.columns:
            df[col] = 0.0
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df[["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]]


def load_backtest_environment(
    h1_path: str = DEFAULT_H1_CSV,
    m5_path: str = DEFAULT_M5_CSV,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load cặp dữ liệu H1 (xu hướng) + M5 (entry) cho backtest."""
    df_h1 = load_ohlcv_csv(h1_path)
    df_m5 = load_ohlcv_csv(m5_path)
    return df_h1, df_m5


def resolve_backtest_csv_paths(h1_path: str, m5_path: str) -> tuple[str, str]:
    """
    Chuẩn hóa đường dẫn CSV thành absolute path (pickle-safe, ổn định trên Windows spawn).
    """
    h1 = Path(h1_path)
    m5 = Path(m5_path)
    h1_resolved = h1 if h1.is_file() else _resolve_data_path(h1_path)
    m5_resolved = m5 if m5.is_file() else _resolve_data_path(m5_path)
    return str(h1_resolved.resolve()), str(m5_resolved.resolve())


# ---------------------------------------------------------------------------
# 2. Giả lập trading — tái dựng signal_engine + basket_manager + drawdown_guard
# ---------------------------------------------------------------------------


@dataclass
class SimPosition:
    """Vị thế in-memory thay cho TradePosition (không cần DB/MT5)."""

    ticket_id: str
    side: OrderSide
    volume: float
    entry_price: float
    layer_index: int = 0
    basket_anchor_price: float | None = None
    opened_at: datetime | None = None


@dataclass
class BacktestResult:
    """Kết quả một lần chạy backtest."""

    total_pnl_usd: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    trade_count: int = 0
    win_count: int = 0


@dataclass
class BacktestState:
    """Trạng thái mô phỏng trong quá trình duyệt nến."""

    balance: float
    equity_peak: float
    max_drawdown_pct: float = 0.0
    realized_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    trade_count: int = 0
    win_count: int = 0
    positions: list[SimPosition] = field(default_factory=list)
    _ticket_seq: int = 0

    def next_ticket(self) -> str:
        self._ticket_seq += 1
        return f"SIM-{self._ticket_seq}"


def _position_floating_pnl(position: SimPosition, price: float) -> float:
    if position.side == OrderSide.BUY:
        return (price - position.entry_price) * position.volume * 100
    return (position.entry_price - price) * position.volume * 100


def _total_floating_pnl(positions: list[SimPosition], price: float) -> float:
    return round(sum(_position_floating_pnl(p, price) for p in positions), 2)


def _update_equity_metrics(state: BacktestState, price: float) -> None:
    floating = _total_floating_pnl(state.positions, price)
    equity = state.balance + state.realized_pnl + floating
    state.equity_peak = max(state.equity_peak, equity)
    if state.equity_peak > 0:
        dd = (state.equity_peak - equity) / state.equity_peak * 100.0
        state.max_drawdown_pct = max(state.max_drawdown_pct, dd)


def _close_positions(
    state: BacktestState,
    to_close: list[SimPosition],
    price: float,
) -> float:
    """Đóng danh sách vị thế, cập nhật PnL và metrics."""
    closed_pnl = 0.0
    close_ids = {p.ticket_id for p in to_close}
    remaining: list[SimPosition] = []

    for pos in state.positions:
        if pos.ticket_id not in close_ids:
            remaining.append(pos)
            continue
        pnl = round(_position_floating_pnl(pos, price), 2)
        closed_pnl += pnl
        state.trade_count += 1
        if pnl >= 0:
            state.gross_profit += pnl
            state.win_count += 1
        else:
            state.gross_loss += abs(pnl)

    state.positions = remaining
    state.realized_pnl = round(state.realized_pnl + closed_pnl, 2)
    return closed_pnl


def _sim_layer_volume(
    balance: float,
    *,
    is_scalp_mode: bool,
) -> float:
    """Volume cố định theo nấc vốn — mirror risk.calculate_layer_volume (không MT5)."""
    volume = calculate_fixed_lot_size(balance)
    if is_scalp_mode:
        volume *= SCALP_VOLUME_MULTIPLIER
    return max(0.01, round(volume, 2))


def _open_layer(
    state: BacktestState,
    config: BotConfig,
    side: OrderSide,
    price: float,
    *,
    layer_index: int,
    anchor_price: float | None,
    is_scalp_mode: bool,
    opened_at: datetime,
) -> None:
    volume = _sim_layer_volume(state.balance, is_scalp_mode=is_scalp_mode and layer_index == 0)
    anchor = anchor_price if anchor_price is not None else price
    state.positions.append(
        SimPosition(
            ticket_id=state.next_ticket(),
            side=side,
            volume=volume,
            entry_price=price,
            layer_index=layer_index,
            basket_anchor_price=anchor,
            opened_at=opened_at,
        )
    )


def compute_backtest_signal(
    df_h1: pd.DataFrame,
    df_m5: pd.DataFrame,
    config: BotConfig,
) -> tuple[AggregatedSignal, BasketContext]:
    """
    Tính tín hiệu đa khung H1 + M5 — logic giống signal_engine.check_trend_and_entry_signal
    nhưng dùng slice DataFrame thay vì MarketDataProvider.
    """
    h1_signal = aggregate_signal(df_h1, config, include_rsi=False)
    main_trend, _, _ = _resolve_main_trend(h1_signal.net_signal)

    atr_factor, atr_meta = atr_volatility_factor(df_m5)
    entry_signal = aggregate_signal(df_m5, config, apply_atr_filter=True)

    final_net, is_scalp_mode, _ = _filter_entry_signal(
        entry_signal.net_signal,
        entry_signal.weighted_score,
        main_trend,
        entry_threshold=config.signal_threshold,
    )

    signal = AggregatedSignal(
        strategy_results=entry_signal.strategy_results,
        weighted_score=entry_signal.weighted_score,
        net_signal=final_net,
        is_scalp_mode=is_scalp_mode,
    )
    atr_value = atr_meta.get("current_atr")
    ctx = BasketContext(
        main_trend=main_trend,
        entry_net_raw=entry_signal.net_signal,
        entry_score=entry_signal.weighted_score,
        is_scalp_mode=is_scalp_mode,
        atr_value=float(atr_value) if atr_value is not None else None,
    )
    return signal, ctx


def _slice_bars(df: pd.DataFrame, end_time: pd.Timestamp, lookback: int) -> pd.DataFrame:
    subset = df[df["time"] <= end_time]
    if subset.empty:
        return subset
    return subset.tail(lookback).reset_index(drop=True)


def _apply_drawdown_guard(state: BacktestState, price: float) -> bool:
    """
    Mô phỏng drawdown_guard: partial close @ 15%, panic close @ 20%.
    Trả về True nếu panic (dừng mở lệnh mới trong tick đó — xử lý bên ngoài).
    """
    floating = _total_floating_pnl(state.positions, price)
    dd_pct = current_drawdown_percent(floating, state.balance)

    if dd_pct >= DD_PANIC_THRESHOLD_PCT and state.positions:
        _close_positions(state, list(state.positions), price)
        return True

    if dd_pct >= DD_PARTIAL_THRESHOLD_PCT and state.positions:
        worst = min(state.positions, key=lambda p: _position_floating_pnl(p, price))
        worst_pnl = _position_floating_pnl(worst, price)
        if worst_pnl < 0:
            _close_positions(state, [worst], price)

    return False


def _process_basket_side(
    state: BacktestState,
    config: BotConfig,
    side: OrderSide,
    price: float,
    signal: AggregatedSignal,
    ctx: BasketContext,
    bar_time: datetime,
) -> None:
    """Xử lý basket một chiều — mirror trading_orchestrator.run_tick."""
    side_positions = [p for p in state.positions if p.side == side]
    if not side_positions:
        return

    basket = build_position_basket(_positions_as_trade_like(side_positions))
    if basket is None:
        return

    decision = evaluate_basket(config, basket, price, signal, state.balance, ctx=ctx)

    if decision.action != BasketAction.HOLD:
        _close_positions(state, side_positions, price)
        return

    net_pnl = calculate_net_pnl_usd(basket, price)
    side_max_layers = effective_max_layers(config, basket, ctx)
    if (
        should_add_dca_layer(
            config,
            basket,
            price,
            ctx=ctx,
            net_pnl_usd=net_pnl,
            account_balance=state.balance,
        )
        and basket.layer_count < side_max_layers
    ):
        _open_layer(
            state,
            config,
            basket.side,
            price,
            layer_index=basket.layer_count,
            anchor_price=basket.anchor_price,
            is_scalp_mode=False,
            opened_at=bar_time,
        )


def _positions_as_trade_like(positions: list[SimPosition]) -> list[Any]:
    """Adapter để build_position_basket nhận object giống TradePosition."""
    return positions


def run_backtest(
    df_h1: pd.DataFrame,
    df_m5: pd.DataFrame,
    config: BotConfig,
    *,
    initial_balance: float = 200.0,
    lookback: int | None = None,
) -> BacktestResult:
    """
    Duyệt từng nến M5, mô phỏng vào lệnh / DCA / thoát / drawdown guard.

    Fitness đánh giá dựa trên PnL, Profit Factor và Max Drawdown thu được.
    """
    lookback = lookback or config.bars_lookback
    min_bars = max(lookback, 50)
    if len(df_m5) < min_bars:
        return BacktestResult()

    state = BacktestState(balance=initial_balance, equity_peak=initial_balance)

    for i in range(min_bars, len(df_m5)):
        row = df_m5.iloc[i]
        bar_time = row["time"].to_pydatetime()
        price = float(row["close"])

        df_h1_slice = _slice_bars(df_h1, row["time"], lookback)
        df_m5_slice = df_m5.iloc[max(0, i - lookback + 1) : i + 1].reset_index(drop=True)

        if len(df_h1_slice) < 30 or len(df_m5_slice) < 30:
            continue

        signal, ctx = compute_backtest_signal(df_h1_slice, df_m5_slice, config)
        open_count_at_bar = len(state.positions)

        if _apply_drawdown_guard(state, price):
            _update_equity_metrics(state, price)
            continue

        for side in (OrderSide.BUY, OrderSide.SELL):
            _process_basket_side(state, config, side, price, signal, ctx, bar_time)

        if should_open_reversal_hedge_layer(
            signal,
            _positions_as_trade_like(state.positions),
            is_scalp_mode=signal.is_scalp_mode,
        ):
            side = OrderSide.BUY if signal.net_signal == int(NetSignal.BUY) else OrderSide.SELL
            _open_layer(
                state,
                config,
                side,
                price,
                layer_index=0,
                anchor_price=None,
                is_scalp_mode=signal.is_scalp_mode,
                opened_at=bar_time,
            )
        elif should_open_initial_layer(signal, state.positions):
            side = OrderSide.BUY if signal.net_signal == int(NetSignal.BUY) else OrderSide.SELL
            _open_layer(
                state,
                config,
                side,
                price,
                layer_index=0,
                anchor_price=None,
                is_scalp_mode=signal.is_scalp_mode,
                opened_at=bar_time,
            )

        _update_equity_metrics(state, price)

    # Đóng vị thế còn lại ở giá cuối (mark-to-market → realized)
    if state.positions:
        final_price = float(df_m5.iloc[-1]["close"])
        _close_positions(state, list(state.positions), final_price)

    pf = state.gross_profit / state.gross_loss if state.gross_loss > 0 else (
        state.gross_profit if state.gross_profit > 0 else 0.0
    )

    return BacktestResult(
        total_pnl_usd=round(state.realized_pnl, 2),
        gross_profit=round(state.gross_profit, 2),
        gross_loss=round(state.gross_loss, 2),
        profit_factor=round(pf, 4),
        max_drawdown_pct=round(state.max_drawdown_pct, 2),
        trade_count=state.trade_count,
        win_count=state.win_count,
    )


# ---------------------------------------------------------------------------
# 3. Genetic Algorithm — cá thể, fitness, chọn lọc, lai ghép, đột biến
# ---------------------------------------------------------------------------


@dataclass
class Individual:
    """
    Chromosome = 6 gene:
      [donchian_w, supertrend_w, rsi_w, ema_w, single_tp_distance, layer_spacing_min]

    4 trọng số đầu được chuẩn hóa tổng = 1.0 sau decode.
    """

    genes: list[float]
    fitness: float = float("-inf")
    backtest: BacktestResult | None = None

    def copy(self) -> Individual:
        return Individual(genes=self.genes.copy(), fitness=self.fitness, backtest=self.backtest)


def _normalize_weights(w_d: float, w_st: float, w_rsi: float, w_ema: float) -> tuple[float, float, float, float]:
    """Chuẩn hóa 4 trọng số về tổng 1.0."""
    raw = [max(WEIGHT_MIN, min(WEIGHT_MAX, w)) for w in (w_d, w_st, w_rsi, w_ema)]
    total = sum(raw)
    if total <= 0:
        return 0.25, 0.25, 0.25, 0.25
    return tuple(round(w / total, 4) for w in raw)  # type: ignore[return-value]


def clone_base_config(base: BotConfig | None = None) -> BotConfig:
    """Tạo BotConfig mới từ mẫu seed (tránh deepcopy SQLAlchemy model)."""
    src = base or _default_xauusd_bot()
    config = _default_xauusd_bot()
    for attr in BASE_CONFIG_ATTRS:
        setattr(config, attr, getattr(src, attr))
    return config


def base_config_to_snapshot(config: BotConfig) -> dict[str, Any]:
    """Serialize BotConfig → dict (pickle-safe cho multiprocessing workers)."""
    return {attr: getattr(config, attr) for attr in BASE_CONFIG_ATTRS}


def config_from_snapshot(snapshot: dict[str, Any]) -> BotConfig:
    """Khôi phục BotConfig từ snapshot trong worker process."""
    config = _default_xauusd_bot()
    for attr, value in snapshot.items():
        setattr(config, attr, value)
    return config


def individual_to_config(
    ind: Individual,
    base: BotConfig | None = None,
    *,
    base_snapshot: dict[str, Any] | None = None,
) -> BotConfig:
    """Ánh xạ chromosome → BotConfig (chỉ thay gene được tối ưu)."""
    if base_snapshot is not None:
        config = config_from_snapshot(base_snapshot)
    else:
        config = clone_base_config(base)
    w_d, w_st, w_rsi, w_ema = _normalize_weights(*ind.genes[:4])
    config.donchian_weight = w_d
    config.supertrend_weight = w_st
    config.rsi_weight = w_rsi
    config.ema_weight = w_ema
    config.single_tp_distance = max(SINGLE_TP_MIN, min(SINGLE_TP_MAX, ind.genes[4]))
    config.layer_spacing_min = max(LAYER_SPACING_MIN, min(LAYER_SPACING_MAX, ind.genes[5]))
    return config


def random_individual(rng: random.Random) -> Individual:
    """Sinh cá thể ngẫu nhiên trong không gian tìm kiếm."""
    weights = [rng.uniform(WEIGHT_MIN, WEIGHT_MAX) for _ in range(4)]
    genes = weights + [
        rng.uniform(SINGLE_TP_MIN, SINGLE_TP_MAX),
        rng.uniform(LAYER_SPACING_MIN, LAYER_SPACING_MAX),
    ]
    return Individual(genes=genes)


def compute_fitness(result: BacktestResult, initial_balance: float) -> float:
    """
    Hàm fitness đa mục tiêu (scalarized):
      - Tối đa hóa Profit Factor và PnL_USD
      - Tối thiểu hóa Max_Drawdown (%)

    fitness = PF × 10 + (PnL / balance) × 5 − max_dd × 0.3
    Cá thể không giao dịch → fitness rất thấp.
    """
    if result.trade_count == 0:
        return -100.0

    pnl_ratio = result.total_pnl_usd / max(initial_balance, 1.0)
    return (
        result.profit_factor * 10.0
        + pnl_ratio * 5.0
        - result.max_drawdown_pct * 0.3
    )


def evaluate_individual(
    ind: Individual,
    df_h1: pd.DataFrame,
    df_m5: pd.DataFrame,
    base_config: BotConfig,
    *,
    initial_balance: float,
    base_snapshot: dict[str, Any] | None = None,
) -> float:
    snapshot = base_snapshot or base_config_to_snapshot(base_config)
    config = individual_to_config(ind, base_snapshot=snapshot)
    result = run_backtest(df_h1, df_m5, config, initial_balance=initial_balance)
    ind.backtest = result
    ind.fitness = compute_fitness(result, initial_balance)
    return ind.fitness


# ---------------------------------------------------------------------------
# Multiprocessing — đánh giá fitness song song trên nhiều CPU
# ---------------------------------------------------------------------------


def _init_eval_worker(
    h1_path: str,
    m5_path: str,
    base_snapshot: dict[str, Any],
    initial_balance: float,
) -> None:
    """
    Khởi tạo worker process: tự load CSV từ đường dẫn (không pickle DataFrame).

    Trên Windows (spawn), truyền DataFrame qua initargs gây treo/deadlock với dataset lớn.
    Mỗi worker đọc file một lần khi khởi động và giữ trong global _MP_DF_*.
    """
    global _MP_DF_H1, _MP_DF_M5, _MP_BASE_SNAPSHOT, _MP_INITIAL_BALANCE
    _MP_DF_H1, _MP_DF_M5 = load_backtest_environment(h1_path, m5_path)
    _MP_BASE_SNAPSHOT = base_snapshot
    _MP_INITIAL_BALANCE = initial_balance


def _evaluate_genes_worker(genes: list[float]) -> tuple[list[float], float, dict[str, Any]]:
    """
    Worker target — chạy backtest cho một chromosome, trả kết quả pickle-safe.
    Gọi qua Pool.map / imap_unordered để song song hóa fitness evaluation.
    """
    assert _MP_DF_H1 is not None and _MP_DF_M5 is not None
    assert _MP_BASE_SNAPSHOT is not None

    ind = Individual(genes=genes)
    config = individual_to_config(ind, base_snapshot=_MP_BASE_SNAPSHOT)
    result = run_backtest(
        _MP_DF_H1,
        _MP_DF_M5,
        config,
        initial_balance=_MP_INITIAL_BALANCE,
    )
    fitness = compute_fitness(result, _MP_INITIAL_BALANCE)
    return genes, fitness, asdict(result)


def _apply_eval_results(population: list[Individual], eval_outputs: list[tuple]) -> None:
    """Gán fitness + backtest từ kết quả worker vào quần thể."""
    by_genes = {tuple(genes): (fitness, bt_dict) for genes, fitness, bt_dict in eval_outputs}
    for ind in population:
        key = tuple(ind.genes)
        if key not in by_genes:
            continue
        fitness, bt_dict = by_genes[key]
        ind.fitness = fitness
        ind.backtest = BacktestResult(**bt_dict)


def evaluate_population_parallel(
    population: list[Individual],
    h1_path: str,
    m5_path: str,
    base_config: BotConfig,
    *,
    initial_balance: float,
    workers: int,
    pool: Pool | None = None,
) -> None:
    """
    Chia quần thể cho Pool xử lý song song.

    initargs chỉ truyền đường dẫn CSV (vài byte) — worker tự load dữ liệu,
    tránh pickle DataFrame 71k+ nến qua IPC trên Windows.

    Nếu truyền `pool` sẵn có, tái sử dụng worker đã load CSV (không spawn lại mỗi thế hệ).
    """
    workers = max(1, min(workers, len(population)))
    base_snapshot = base_config_to_snapshot(base_config)
    gene_lists = [ind.genes for ind in population]
    h1_resolved, m5_resolved = resolve_backtest_csv_paths(h1_path, m5_path)
    initargs = (h1_resolved, m5_resolved, base_snapshot, initial_balance)
    chunksize = max(1, len(gene_lists) // workers)

    if workers == 1:
        _init_eval_worker(*initargs)
        outputs = [_evaluate_genes_worker(genes) for genes in gene_lists]
    elif pool is not None:
        outputs = pool.map(_evaluate_genes_worker, gene_lists, chunksize=chunksize)
    else:
        with Pool(
            processes=workers,
            initializer=_init_eval_worker,
            initargs=initargs,
        ) as owned_pool:
            outputs = owned_pool.map(_evaluate_genes_worker, gene_lists, chunksize=chunksize)

    _apply_eval_results(population, outputs)


def evaluate_population_sequential(
    population: list[Individual],
    h1_path: str,
    m5_path: str,
    base_config: BotConfig,
    *,
    initial_balance: float,
) -> None:
    """Fallback tuần tự (workers=1 hoặc debug)."""
    evaluate_population_parallel(
        population,
        h1_path,
        m5_path,
        base_config,
        initial_balance=initial_balance,
        workers=1,
    )


def tournament_select(
    population: list[Individual],
    rng: random.Random,
    k: int = 3,
) -> Individual:
    """Chọn lọc tournament — chọn k cá thể ngẫu nhiên, giữ cá thể fitness cao nhất."""
    contenders = rng.sample(population, min(k, len(population)))
    return max(contenders, key=lambda x: x.fitness)


def crossover(parent_a: Individual, parent_b: Individual, rng: random.Random) -> Individual:
    """
    Lai ghép uniform — mỗi gene 50% từ cha A hoặc cha B.
    Giữ đa dạng quần thể giữa các thế hệ.
    """
    child_genes = [
        parent_a.genes[i] if rng.random() < 0.5 else parent_b.genes[i]
        for i in range(len(parent_a.genes))
    ]
    return Individual(genes=child_genes)


def mutate(ind: Individual, rng: random.Random, rate: float = 0.2) -> Individual:
    """
    Đột biến Gaussian cho trọng số / TP / spacing.
    Trọng số được clamp trước khi normalize ở bước decode config.
    """
    genes = ind.genes.copy()
    for i in range(len(genes)):
        if rng.random() > rate:
            continue
        if i < 4:
            genes[i] += rng.gauss(0, 0.05)
            genes[i] = max(WEIGHT_MIN, min(WEIGHT_MAX, genes[i]))
        elif i == 4:
            genes[i] += rng.gauss(0, 0.15)
            genes[i] = max(SINGLE_TP_MIN, min(SINGLE_TP_MAX, genes[i]))
        else:
            genes[i] += rng.gauss(0, 0.5)
            genes[i] = max(LAYER_SPACING_MIN, min(LAYER_SPACING_MAX, genes[i]))
    return Individual(genes=genes)


def run_genetic_algorithm(
    h1_path: str,
    m5_path: str,
    *,
    population_size: int = 30,
    generations: int = 20,
    mutation_rate: float = 0.2,
    elite_count: int = 2,
    seed: int = 42,
    initial_balance: float = 200.0,
    base_config: BotConfig | None = None,
    workers: int | None = None,
) -> Individual:
    """
    Vòng lặp tiến hóa GA thuần Python với fitness evaluation song song (multiprocessing).

    Truyền đường dẫn CSV (không DataFrame) để worker tự load — an toàn trên Windows spawn.

    Mỗi thế hệ:
      1. Pool.map đánh giá song song toàn bộ quần thể (tận dụng N logical CPU)
      2. Giữ elite (cá thể tốt nhất) sang thế hệ sau — elitism
      3. Sinh con bằng tournament selection + crossover + mutation
    """
    rng = random.Random(seed)
    base_config = base_config or _default_xauusd_bot()
    n_workers = workers if workers is not None else DEFAULT_WORKERS
    n_workers = max(1, n_workers)
    h1_resolved, m5_resolved = resolve_backtest_csv_paths(h1_path, m5_path)

    population = [random_individual(rng) for _ in range(population_size)]
    best: Individual | None = None

    print(
        f"  Song song hóa: {n_workers} worker(s) "
        f"(CPU logical cores detected: {DEFAULT_WORKERS})"
    )
    print(f"  Worker CSV: H1={h1_resolved}")
    print(f"              M5={m5_resolved}")

    pool_initargs = (
        h1_resolved,
        m5_resolved,
        base_config_to_snapshot(base_config),
        initial_balance,
    )

    def _run_generation_loop(mp_pool: Pool | None) -> None:
        nonlocal population, best
        if mp_pool is None:
            _init_eval_worker(*pool_initargs)

        for gen in range(generations):
            evaluate_population_parallel(
                population,
                h1_resolved,
                m5_resolved,
                base_config,
                initial_balance=initial_balance,
                workers=n_workers,
                pool=mp_pool,
            )

            population.sort(key=lambda x: x.fitness, reverse=True)
            gen_best = population[0]
            if best is None or gen_best.fitness > best.fitness:
                best = gen_best.copy()
                best.backtest = gen_best.backtest

            bt = gen_best.backtest
            print(
                f"[Gen {gen + 1}/{generations}] "
                f"fitness={gen_best.fitness:.3f} "
                f"PF={bt.profit_factor if bt else 0:.2f} "
                f"PnL=${bt.total_pnl_usd if bt else 0:.2f} "
                f"DD={bt.max_drawdown_pct if bt else 0:.1f}% "
                f"trades={bt.trade_count if bt else 0}"
            )

            if gen == generations - 1:
                break

            next_gen: list[Individual] = [population[i].copy() for i in range(elite_count)]
            while len(next_gen) < population_size:
                parent_a = tournament_select(population, rng)
                parent_b = tournament_select(population, rng)
                child = crossover(parent_a, parent_b, rng)
                child = mutate(child, rng, rate=mutation_rate)
                next_gen.append(child)
            population = next_gen

    if n_workers == 1:
        _run_generation_loop(None)
    else:
        with Pool(
            processes=n_workers,
            initializer=_init_eval_worker,
            initargs=pool_initargs,
        ) as mp_pool:
            _run_generation_loop(mp_pool)

    assert best is not None
    return best


# ---------------------------------------------------------------------------
# 4. Output — in kết quả và xuất best_bot_config.json
# ---------------------------------------------------------------------------


def export_best_config(best: Individual, output_path: str | Path = DEFAULT_OUTPUT_JSON) -> Path:
    """Xuất bộ tham số tối ưu ra JSON."""
    config = individual_to_config(best)
    w_d, w_st, w_rsi, w_ema = _normalize_weights(*best.genes[:4])
    bt = best.backtest or BacktestResult()

    payload = {
        "optimized_at": datetime.now(timezone.utc).isoformat(),
        "fitness": round(best.fitness, 4),
        "backtest_metrics": {
            "total_pnl_usd": bt.total_pnl_usd,
            "profit_factor": bt.profit_factor,
            "max_drawdown_pct": bt.max_drawdown_pct,
            "trade_count": bt.trade_count,
            "win_count": bt.win_count,
            "gross_profit": bt.gross_profit,
            "gross_loss": bt.gross_loss,
        },
        "donchian_weight": w_d,
        "supertrend_weight": w_st,
        "rsi_weight": w_rsi,
        "ema_weight": w_ema,
        "single_tp_distance": round(config.single_tp_distance, 4),
        "layer_spacing_min": round(config.layer_spacing_min, 4),
        "weights_sum": round(w_d + w_st + w_rsi + w_ema, 4),
    }

    out = Path(output_path)
    if not out.is_absolute():
        for base in (Path.cwd(), BACKEND_ROOT, PROJECT_ROOT):
            candidate = base / out
            if candidate.parent.exists() or base == Path.cwd():
                out = candidate
                break

    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out.resolve()


def print_best_summary(best: Individual) -> None:
    """In bộ tham số tối ưu ra console."""
    w_d, w_st, w_rsi, w_ema = _normalize_weights(*best.genes[:4])
    bt = best.backtest or BacktestResult()

    print("\n" + "=" * 60)
    print("  BỘ THÔNG SỐ TỐI ƯU (Genetic Algorithm)")
    print("=" * 60)
    print(f"  Fitness:           {best.fitness:.4f}")
    print(f"  Profit Factor:     {bt.profit_factor:.4f}")
    print(f"  Total PnL (USD):   {bt.total_pnl_usd:.2f}")
    print(f"  Max Drawdown (%):  {bt.max_drawdown_pct:.2f}")
    print(f"  Trades / Wins:     {bt.trade_count} / {bt.win_count}")
    print("-" * 60)
    print(f"  donchian_weight:   {w_d:.4f}")
    print(f"  supertrend_weight: {w_st:.4f}")
    print(f"  rsi_weight:        {w_rsi:.4f}")
    print(f"  ema_weight:        {w_ema:.4f}")
    print(f"  (weights sum)      {w_d + w_st + w_rsi + w_ema:.4f}")
    print(f"  single_tp_distance:{best.genes[4]:.4f}")
    print(f"  layer_spacing_min: {best.genes[5]:.4f}")
    print("=" * 60 + "\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="GA Optimizer — tìm trọng số chiến lược và tham số DCA tối ưu"
    )
    parser.add_argument("--h1-csv", default=DEFAULT_H1_CSV, help="Đường dẫn CSV H1")
    parser.add_argument("--m5-csv", default=DEFAULT_M5_CSV, help="Đường dẫn CSV M5")
    parser.add_argument("--generations", type=int, default=20, help="Số thế hệ GA")
    parser.add_argument("--population", type=int, default=30, help="Quy mô quần thể")
    parser.add_argument("--mutation-rate", type=float, default=0.2, help="Xác suất đột biến")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--balance", type=float, default=200.0, help="Vốn ban đầu backtest")
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Số process song song cho fitness eval (mặc định: {DEFAULT_WORKERS} CPU)",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_JSON,
        help="File JSON đầu ra",
    )
    args = parser.parse_args(argv)

    h1_csv = args.h1_csv or DEFAULT_H1_CSV
    m5_csv = args.m5_csv or DEFAULT_M5_CSV

    print("Đang load dữ liệu backtest...")
    print(f"  H1 CSV: {h1_csv}")
    print(f"  M5 CSV: {m5_csv}")
    df_h1, df_m5 = load_backtest_environment(h1_csv, m5_csv)
    print(f"  H1: {len(df_h1)} nến | M5: {len(df_m5)} nến")

    workers = max(1, min(args.workers, args.population))

    print(
        f"\nBắt đầu GA: population={args.population}, "
        f"generations={args.generations}, workers={workers}, seed={args.seed}\n"
    )

    best = run_genetic_algorithm(
        h1_csv,
        m5_csv,
        population_size=args.population,
        generations=args.generations,
        mutation_rate=args.mutation_rate,
        seed=args.seed,
        initial_balance=args.balance,
        workers=workers,
    )

    print_best_summary(best)
    out_path = export_best_config(best, args.output)
    print(f"Đã xuất cấu hình tối ưu → {out_path}")


if __name__ == "__main__":
    # Bắt buộc trên Windows khi dùng multiprocessing (spawn)
    from multiprocessing import freeze_support

    freeze_support()
    main()
