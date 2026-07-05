"""Replay bot signal + PnL at a specific M5 candle (e.g. news spike)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import MetaTrader5 as mt5
import pandas as pd
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import BotConfig, OrderSide
from app.services.mt5_client import get_mt5_client, TIMEFRAME_MAP
from app.trading.market_data import rates_to_dataframe
from app.trading.ai.ai_filter import get_meta_labeling_filter
from app.trading.ai.features import _atr_ratio, build_entry_features
from app.trading.ai.labeler import resolve_sl_distance, resolve_tp_distance, simulate_entry_outcome
from app.trading.aggregator import aggregate_signal, atr_volatility_factor
from app.trading.risk import calculate_fixed_lot_size
from app.trading.signal_engine import (
    ENTRY_TIMEFRAME,
    _filter_entry_signal,
    _resolve_main_trend,
)
from app.trading.trading_mode import (
    effective_scalp_entry_threshold,
    effective_signal_threshold,
    is_super_safe,
)
from app.trading.types import NetSignal
from app.trading.signal_format import net_signal_label


@dataclass
class ReplayMarket:
    df_h1: pd.DataFrame
    df_m5: pd.DataFrame

    def fetch_timeframe(self, symbol: str, timeframe: str, bars_lookback: int) -> pd.DataFrame:
        df = self.df_h1 if timeframe.upper() == "H1" else self.df_m5
        return df.tail(bars_lookback).reset_index(drop=True)


def fetch_history(symbol: str, days_back: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    client = get_mt5_client()
    status = client.initialize()
    if not status.connected:
        raise RuntimeError(status.error or "MT5 not connected")
    resolved = client.resolve_symbol(symbol)
    if not resolved:
        raise RuntimeError(f"Symbol not found: {symbol}")

    date_to = datetime.utcnow() + timedelta(hours=1)
    date_from = date_to - timedelta(days=days_back)
    m5_rates = mt5.copy_rates_range(resolved, TIMEFRAME_MAP["M5"], date_from, date_to)
    h1_rates = mt5.copy_rates_range(resolved, TIMEFRAME_MAP["H1"], date_from, date_to)
    df_m5 = rates_to_dataframe(m5_rates)
    df_h1 = rates_to_dataframe(h1_rates)

    # copy_rates_range có thể lag — bổ sung nến gần nhất từ copy_rates_from_pos
    recent_m5 = rates_to_dataframe(
        mt5.copy_rates_from_pos(resolved, TIMEFRAME_MAP["M5"], 0, 500)
    )
    recent_h1 = rates_to_dataframe(
        mt5.copy_rates_from_pos(resolved, TIMEFRAME_MAP["H1"], 0, 200)
    )
    if not recent_m5.empty:
        df_m5 = (
            pd.concat([df_m5, recent_m5])
            .drop_duplicates(subset=["time"])
            .sort_values("time")
            .reset_index(drop=True)
        )
    if not recent_h1.empty:
        df_h1 = (
            pd.concat([df_h1, recent_h1])
            .drop_duplicates(subset=["time"])
            .sort_values("time")
            .reset_index(drop=True)
        )

    if df_m5.empty or df_h1.empty:
        raise RuntimeError("No historical rates from MT5")
    return df_h1, df_m5


def evaluate_at_time(
    config: BotConfig,
    df_h1: pd.DataFrame,
    df_m5: pd.DataFrame,
    target: pd.Timestamp,
    ai_filter,
) -> dict | None:
    h1_slice = df_h1[df_h1["time"] <= target].copy()
    m5_slice = df_m5[df_m5["time"] <= target].copy()
    if len(m5_slice) < 50 or len(h1_slice) < 30:
        return None

    market = ReplayMarket(h1_slice, m5_slice)
    d_h1 = market.fetch_timeframe(config.symbol, "H1", config.bars_lookback)
    d_m5 = market.fetch_timeframe(config.symbol, ENTRY_TIMEFRAME, config.bars_lookback)

    h1_signal = aggregate_signal(d_h1, config, include_rsi=False)
    main_trend, _, _ = _resolve_main_trend(h1_signal.net_signal)
    entry_signal = aggregate_signal(
        d_m5, config, apply_atr_filter=True, h1_trend=main_trend.value
    )
    atr_ratio_value, _ = _atr_ratio(d_m5)

    ai_features = None
    if ai_filter.is_active:
        ai_features = build_entry_features(
            df_m5=d_m5,
            df_h1=d_h1,
            config=config,
            main_trend=main_trend,
            entry_score=entry_signal.weighted_score,
            h1_score=h1_signal.weighted_score,
            entry_net=entry_signal.net_signal,
            is_scalp_mode=False,
            bar_time=target,
        )

    final_net, is_scalp_mode, filter_log, ai_win_prob = _filter_entry_signal(
        entry_signal.net_signal,
        entry_signal.weighted_score,
        main_trend,
        entry_threshold=effective_signal_threshold(config),
        scalp_threshold=effective_scalp_entry_threshold(config),
        super_safe=is_super_safe(config),
        atr_ratio=atr_ratio_value,
        ai_filter=ai_filter,
        ai_features=ai_features,
    )

    bar = m5_slice.iloc[-1]
    pos = int(m5_slice.index.get_loc(bar.name))
    return {
        "target": target,
        "bar": bar,
        "m5_pos": pos,
        "main_trend": main_trend.value,
        "h1_score": h1_signal.weighted_score,
        "h1_net": net_signal_label(h1_signal.net_signal),
        "entry_score": entry_signal.weighted_score,
        "entry_raw": net_signal_label(entry_signal.net_signal),
        "final_net": net_signal_label(final_net),
        "is_scalp": is_scalp_mode,
        "filter_log": filter_log,
        "ai_win_prob": ai_win_prob,
        "atr_ratio": atr_ratio_value,
        "would_enter": final_net in (int(NetSignal.BUY), int(NetSignal.SELL)),
        "side": (
            OrderSide.BUY
            if final_net == int(NetSignal.BUY)
            else (OrderSide.SELL if final_net == int(NetSignal.SELL) else None)
        ),
    }


def simulate_trade(
    config: BotConfig,
    df_m5: pd.DataFrame,
    m5_pos: int,
    side: OrderSide,
    *,
    balance: float,
    is_scalp: bool,
) -> dict:
    tp_dist = resolve_tp_distance(config, is_scalp_mode=is_scalp, balance=balance)
    sl_dist = resolve_sl_distance(config)
    lot = calculate_fixed_lot_size(balance)
    if is_scalp:
        lot = max(0.01, round(lot * 0.5, 2))

    outcome = simulate_entry_outcome(
        df_m5.reset_index(drop=True),
        m5_pos,
        side,
        tp_distance=tp_dist,
        sl_distance=sl_dist,
    )

    entry_price = float(df_m5.iloc[m5_pos]["close"])
    usd_per_price = lot * 100.0
    if outcome == 1:
        pnl = tp_dist * usd_per_price
        result = "WIN (TP)"
    elif outcome == 0:
        pnl = -sl_dist * usd_per_price
        result = "LOSS (SL hoặc timeout)"
    else:
        pnl = 0.0
        result = "NO DATA"

    # Track max adverse / favorable after entry
    fwd = df_m5.iloc[m5_pos + 1 : m5_pos + 49]
    if side == OrderSide.BUY:
        max_fav = float(fwd["high"].max() - entry_price) if len(fwd) else 0.0
        max_adv = float(entry_price - fwd["low"].min()) if len(fwd) else 0.0
    else:
        max_fav = float(entry_price - fwd["low"].min()) if len(fwd) else 0.0
        max_adv = float(fwd["high"].max() - entry_price) if len(fwd) else 0.0

    return {
        "entry_price": entry_price,
        "lot": lot,
        "tp_dist": tp_dist,
        "sl_dist": sl_dist,
        "outcome": result,
        "pnl_usd": round(pnl, 2),
        "max_favorable_gold": round(max_fav, 2),
        "max_adverse_gold": round(max_adv, 2),
        "max_favorable_usd": round(max_fav * usd_per_price, 2),
        "max_adverse_usd": round(max_adv * usd_per_price, 2),
    }


def find_bar(df_m5: pd.DataFrame, hour: int, minute: int, day: str) -> pd.Timestamp | None:
    day_ts = pd.Timestamp(day).date()
    hits = df_m5[
        (df_m5["time"].dt.date == day_ts)
        & (df_m5["time"].dt.hour == hour)
        & (df_m5["time"].dt.minute == minute)
    ]
    if hits.empty:
        return None
    return hits.iloc[0]["time"]


def counterfactual_long(
    config: BotConfig,
    df_m5: pd.DataFrame,
    target: pd.Timestamp,
    *,
    balance: float,
) -> None:
    """Gia dinh vao LONG thu cong tai close cua nen."""
    hits = df_m5.index[df_m5["time"] == target]
    if len(hits) == 0:
        print("  (khong tim thay nen)")
        return
    idx = int(hits[0])
    entry = float(df_m5.iloc[idx]["close"])
    lot = calculate_fixed_lot_size(balance)
    tp = resolve_tp_distance(config, is_scalp_mode=False, balance=balance)
    sl = resolve_sl_distance(config)
    out = simulate_entry_outcome(
        df_m5.reset_index(drop=True),
        idx,
        OrderSide.BUY,
        tp_distance=tp,
        sl_distance=sl,
        max_horizon=48,
    )
    fwd = df_m5.iloc[idx + 1 : idx + 49]
    label_out = "WIN (TP)" if out == 1 else ("LOSS (SL)" if out == 0 else "timeout")
    pnl = tp * lot * 100 if out == 1 else (-sl * lot * 100 if out == 0 else 0.0)
    print(f"  Gia dinh LONG thu cong @ {entry:.2f}: {label_out} -> PnL ~ ${pnl:+.2f}")
    if len(fwd):
        print(
            f"  4h sau: max +{fwd['high'].max() - entry:.1f}g "
            f"| drawdown -{entry - fwd['low'].min():.1f}g"
        )


def main() -> None:
    db: Session = SessionLocal()
    try:
        config = db.query(BotConfig).order_by(BotConfig.id).first()
        if not config:
            raise RuntimeError("No bot config in DB")
    finally:
        db.close()

    ai_filter = get_meta_labeling_filter()
    df_h1, df_m5 = fetch_history(config.symbol)
    balance = 120.0  # match live account from worker logs

    # MT5 timestamps = UTC. 19:30 VN (UTC+7) = 12:30 UTC.
    day = "2026-07-02"
    targets = [
        (f"19:30 VN 2/7 (=12:30 UTC) — NEWS SPIKE", find_bar(df_m5, 12, 30, day)),
        ("12:25 UTC (1 nến trước news)", find_bar(df_m5, 12, 25, day)),
        ("12:35 UTC (nến sau spike)", find_bar(df_m5, 12, 35, day)),
        ("13:30 UTC (nhịp hồi 2)", find_bar(df_m5, 13, 30, day)),
    ]

    print("=" * 72)
    print(f"REPLAY — {config.name} | mode={config.trading_mode.value} | balance=${balance}")
    print(f"AI filter active: {ai_filter.is_active}")
    print("=" * 72)

    for label, target in targets:
        print(f"\n### {label}")
        if target is None:
            print("  (không tìm thấy nến)")
            continue

        ev = evaluate_at_time(config, df_h1, df_m5, target, ai_filter)
        if not ev:
            print("  (không đủ dữ liệu lookback)")
            continue

        bar = ev["bar"]
        print(
            f"  Nến: {bar['time']} | O={bar['open']:.2f} H={bar['high']:.2f} "
            f"L={bar['low']:.2f} C={bar['close']:.2f}"
        )
        print(
            f"  H1: {ev['main_trend']} (score={ev['h1_score']:+.2f}, net={ev['h1_net']})"
        )
        print(
            f"  M5: raw={ev['entry_raw']} score={ev['entry_score']:+.2f} "
            f"→ final={ev['final_net']} scalp={ev['is_scalp']}"
        )
        print(f"  ATR ratio: {ev['atr_ratio']:.2f}")
        if ev["ai_win_prob"] is not None:
            print(f"  AI win prob: {ev['ai_win_prob']:.1f}%")
        print(f"  Filter: {ev['filter_log']}")

        if ev["would_enter"]:
            sim = simulate_trade(
                config,
                df_m5[df_m5["time"] <= target].copy(),
                ev["m5_pos"],
                ev["side"],
                balance=balance,
                is_scalp=ev["is_scalp"],
            )
            print(f"  >> BOT SẼ VÀO {ev['side'].value} @ {sim['entry_price']:.2f}")
            print(
                f"     lot={sim['lot']} | TP={sim['tp_dist']:.2f}giá (${sim['pnl_usd'] if sim['outcome'].startswith('WIN') else sim['tp_dist']*sim['lot']*100:.2f}) "
                f"| SL={sim['sl_dist']:.2f}giá"
            )
            print(f"     Kết quả mô phỏng 4h sau: {sim['outcome']} → PnL ≈ ${sim['pnl_usd']:+.2f}")
            print(
                f"     Max thuận/bất lợi 4h: +{sim['max_favorable_gold']:.1f}giá (${sim['max_favorable_usd']:+.2f}) "
                f"/ -{sim['max_adverse_gold']:.1f}giá (${sim['max_adverse_usd']:+.2f})"
            )
        else:
            print("  >> BOT KHÔNG VÀO LỆNH tại thời điểm này")
            counterfactual_long(config, df_m5, target, balance=balance)


if __name__ == "__main__":
    main()
