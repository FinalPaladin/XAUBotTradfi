"""
Gắn nhãn Win/Loss cho tín hiệu entry lớp 1 — mô phỏng TP trước SL.

Win (1): giá chạm Take Profit trước Stop Loss (hard_stop_adverse_distance).
Loss (0): chạm SL trước, hoặc timeout horizon.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.models import OrderSide
from app.trading.risk import SCALP_TP_MULTIPLIER, calculate_fixed_lot_size

DEFAULT_LABEL_HORIZON = 288  # ~24h trên M5
REFERENCE_BALANCE = 200.0


def resolve_tp_distance(
    config,
    *,
    is_scalp_mode: bool,
    balance: float = REFERENCE_BALANCE,
) -> float:
    """Khoảng cách TP (giá Vàng) — mirror build_layer_plan lớp 0."""
    base_volume = calculate_fixed_lot_size(balance)
    tp_min_usd = float(getattr(config, "single_tp_min_usd", 1.0) or 1.0)
    single_tp_distance = float(getattr(config, "single_tp_distance", 1.2) or 1.2)

    if base_volume > 0:
        tp_dist = max(tp_min_usd / (base_volume * 100.0), single_tp_distance)
    else:
        tp_dist = single_tp_distance

    if is_scalp_mode:
        tp_dist *= SCALP_TP_MULTIPLIER
    return tp_dist


def resolve_sl_distance(config) -> float:
    return float(getattr(config, "hard_stop_adverse_distance", 12.0) or 12.0)


def simulate_entry_outcome(
    df_m5: pd.DataFrame,
    entry_index: int,
    side: OrderSide,
    *,
    tp_distance: float,
    sl_distance: float,
    max_horizon: int = DEFAULT_LABEL_HORIZON,
) -> int | None:
    """
    Mô phỏng lệnh từ nến entry_index (vào tại close).

    Trả về 1 (Win), 0 (Loss), hoặc None nếu không đủ dữ liệu phía sau.
  """
    if entry_index < 0 or entry_index >= len(df_m5) - 1:
        return None

    entry_price = float(df_m5["close"].iloc[entry_index])
    end = min(entry_index + max_horizon, len(df_m5) - 1)

    if side == OrderSide.BUY:
        tp_price = entry_price + tp_distance
        sl_price = entry_price - sl_distance
    else:
        tp_price = entry_price - tp_distance
        sl_price = entry_price + sl_distance

    highs = df_m5["high"].to_numpy()
    lows = df_m5["low"].to_numpy()

    for i in range(entry_index + 1, end + 1):
        high = float(highs[i])
        low = float(lows[i])

        if side == OrderSide.BUY:
            hit_tp = high >= tp_price
            hit_sl = low <= sl_price
        else:
            hit_tp = low <= tp_price
            hit_sl = high >= sl_price

        if hit_tp and hit_sl:
            # Cùng nến — pessimistic: SL trước (conservative labeling)
            return 0
        if hit_sl:
            return 0
        if hit_tp:
            return 1

    return 0
