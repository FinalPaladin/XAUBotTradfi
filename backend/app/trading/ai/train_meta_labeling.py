#!/usr/bin/env python3
"""
Huấn luyện Meta-Labeling XGBoost (offline).

Usage (từ thư mục backend/):
    python -m app.trading.ai.train_meta_labeling
    python -m app.trading.ai.train_meta_labeling --m5-csv data/xauusd_m5.csv --h1-csv data/xauusd_h1.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split

from app.config import BACKEND_ROOT
from app.models import BotConfig, BotStatus, OrderSide
from app.trading.ai.features import FEATURE_NAMES, build_features_from_precomputed
from app.trading.ai.labeler import resolve_sl_distance, resolve_tp_distance, simulate_entry_outcome
from app.trading.ai.precompute import precompute_training_data
from app.trading.ai.data_loader import (
    DEFAULT_H1_CSV,
    DEFAULT_M5_CSV,
    load_backtest_environment,
)
from app.trading.signal_engine import _filter_entry_signal, _resolve_main_trend
from app.trading.trading_mode import (
    effective_scalp_entry_threshold,
    effective_signal_threshold,
    is_super_safe,
)
from app.trading.types import NetSignal

DEFAULT_CONFIG_JSON = BACKEND_ROOT / "data" / "best_bot_config.json"
DEFAULT_OUTPUT_MODEL = BACKEND_ROOT / "data" / "meta_model.xgb"
DEFAULT_OUTPUT_META = BACKEND_ROOT / "data" / "meta_model_meta.json"


def load_training_config(config_path: Path | None = None) -> BotConfig:
    """BotConfig từ best_bot_config.json + defaults ORM."""
    base = BotConfig(
        id=0,
        name="meta-label-train",
        status=BotStatus.STOPPED,
        bars_lookback=500,
        signal_threshold=0.65,
        donchian_period=20,
        supertrend_period=10,
        supertrend_multiplier=3.0,
        rsi_period=14,
        ema_period=21,
        donchian_weight=0.35,
        supertrend_weight=0.30,
        rsi_weight=0.20,
        ema_weight=0.15,
        single_tp_distance=1.2,
        hard_stop_adverse_distance=9.0,
        single_tp_min_usd=1.0,
    )
    path = config_path or DEFAULT_CONFIG_JSON
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in (
            "donchian_weight",
            "supertrend_weight",
            "rsi_weight",
            "ema_weight",
            "single_tp_distance",
            "layer_spacing_min",
        ):
            if key in data:
                setattr(base, key, float(data[key]))
    return base


def collect_labeled_samples(
    df_h1: pd.DataFrame,
    df_m5: pd.DataFrame,
    config: BotConfig,
    *,
    lookback: int | None = None,
) -> tuple[pd.DataFrame, np.ndarray]:
    """
    Duyệt M5, tại mỗi bar có entry signal hợp lệ → features + nhãn Win/Loss.
    """
    lookback = lookback or config.bars_lookback

    print("  Phase 1: precompute indicators...")
    pc = precompute_training_data(df_h1, df_m5, config, lookback=lookback)
    print("  Phase 2: filter signals + label outcomes...")

    rows: list[dict[str, float]] = []
    labels: list[int] = []

    entry_threshold = effective_signal_threshold(config)
    scalp_threshold = effective_scalp_entry_threshold(config)
    super_safe = is_super_safe(config)

    total = int(pc.valid.sum())
    processed = 0
    report_every = max(500, total // 10)

    for i in range(pc.min_bar, len(df_m5)):
        if not pc.valid[i]:
            continue

        processed += 1
        if processed > 0 and processed % report_every == 0:
            print(f"  labeling: {processed}/{total} valid bars...", flush=True)

        main_trend, _, _ = _resolve_main_trend(int(pc.h1_net[i]))

        final_net, is_scalp_mode, _, _ = _filter_entry_signal(
            int(pc.m5_entry_net[i]),
            float(pc.m5_entry_weighted[i]),
            main_trend,
            entry_threshold=entry_threshold,
            scalp_threshold=scalp_threshold,
            super_safe=super_safe,
        )

        if final_net not in (int(NetSignal.BUY), int(NetSignal.SELL)):
            continue

        features = build_features_from_precomputed(
            pc=pc,
            bar_index=i,
            df_m5=df_m5,
            main_trend=main_trend,
            entry_score=float(pc.m5_entry_weighted[i]),
            h1_score=float(pc.h1_weighted[i]),
            entry_net=final_net,
            is_scalp_mode=is_scalp_mode,
        )

        side = OrderSide.BUY if final_net == int(NetSignal.BUY) else OrderSide.SELL
        tp_dist = resolve_tp_distance(config, is_scalp_mode=is_scalp_mode)
        sl_dist = resolve_sl_distance(config)

        label = simulate_entry_outcome(
            df_m5,
            i,
            side,
            tp_distance=tp_dist,
            sl_distance=sl_dist,
        )
        if label is None:
            continue

        rows.append(features)
        labels.append(label)

    if not rows:
        return pd.DataFrame(columns=FEATURE_NAMES), np.array([], dtype=np.int8)

    return pd.DataFrame(rows, columns=FEATURE_NAMES), np.array(labels, dtype=np.int8)


def train_xgboost_classifier(
    X: pd.DataFrame,
    y: np.ndarray,
    *,
    test_size: float = 0.2,
    random_state: int = 42,
) -> tuple[xgb.Booster, dict]:
    """Huấn luyện XGBoost binary classifier với time-based split."""
    if len(X) < 50:
        raise ValueError(f"Cần ít nhất 50 mẫu labeled, hiện có {len(X)}")

    split_idx = int(len(X) * (1.0 - test_size))
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    if len(np.unique(y_train)) < 2:
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=random_state, stratify=y
        )

    scale_pos = float((y_train == 0).sum()) / max((y_train == 1).sum(), 1)

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_NAMES)
    dtest = xgb.DMatrix(X_test, label=y_test, feature_names=FEATURE_NAMES)

    params = {
        "objective": "binary:logistic",
        "eval_metric": "auc",
        "max_depth": 5,
        "eta": 0.08,
        "subsample": 0.85,
        "colsample_bytree": 0.85,
        "scale_pos_weight": scale_pos,
        "tree_method": "hist",
        "seed": random_state,
    }

    booster = xgb.train(
        params,
        dtrain,
        num_boost_round=200,
        evals=[(dtrain, "train"), (dtest, "test")],
        early_stopping_rounds=20,
        verbose_eval=False,
    )

    y_prob = booster.predict(dtest)
    y_pred = (y_prob >= 0.5).astype(int)

    metrics = {
        "train_samples": len(X_train),
        "test_samples": len(X_test),
        "win_rate_train": float(y_train.mean()),
        "win_rate_test": float(y_test.mean()),
        "test_auc": float(roc_auc_score(y_test, y_prob)) if len(np.unique(y_test)) > 1 else 0.0,
        "classification_report": classification_report(y_test, y_pred, digits=3),
    }
    return booster, metrics


def save_model(
    booster: xgb.Booster,
    output_model: Path,
    output_meta: Path,
    *,
    metrics: dict,
    min_win_probability: float = 55.0,
) -> None:
    output_model.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(output_model))

    meta = {
        "feature_names": FEATURE_NAMES,
        "min_win_probability": min_win_probability,
        "metrics": {
            k: v for k, v in metrics.items() if k != "classification_report"
        },
        "classification_report": metrics.get("classification_report", ""),
    }
    output_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Model saved: {output_model}")
    print(f"Meta saved:  {output_meta}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train Meta-Labeling XGBoost for XAUBot")
    parser.add_argument("--m5-csv", default=DEFAULT_M5_CSV)
    parser.add_argument("--h1-csv", default=DEFAULT_H1_CSV)
    parser.add_argument("--config-json", default=str(DEFAULT_CONFIG_JSON))
    parser.add_argument("--output-model", default=str(DEFAULT_OUTPUT_MODEL))
    parser.add_argument("--output-meta", default=str(DEFAULT_OUTPUT_META))
    parser.add_argument("--max-m5-bars", type=int, default=None, help="Giới hạn nến M5 (debug)")
    parser.add_argument("--lookback", type=int, default=200, help="Bars lookback (nhỏ hơn = train nhanh hơn)")
    parser.add_argument("--min-win-prob", type=float, default=55.0, help="Ngưỡng inference (%)")
    args = parser.parse_args(argv)

    print("Loading OHLCV data...")
    df_h1, df_m5 = load_backtest_environment(
        args.h1_csv,
        args.m5_csv,
        max_m5_bars=args.max_m5_bars,
    )
    print(f"  H1: {len(df_h1)} bars | M5: {len(df_m5)} bars")

    config = load_training_config(Path(args.config_json))
    config.bars_lookback = args.lookback
    print(
        f"Config weights: D={config.donchian_weight:.3f} ST={config.supertrend_weight:.3f} "
        f"RSI={config.rsi_weight:.3f} EMA={config.ema_weight:.3f}"
    )

    print("Collecting labeled samples (signal replay + TP/SL simulation)...")
    X, y = collect_labeled_samples(df_h1, df_m5, config)
    print(f"  Samples: {len(X)} | Win rate: {y.mean():.1%}" if len(y) else "  No samples!")

    if len(X) < 50:
        print("ERROR: Không đủ mẫu để train. Kiểm tra CSV và config.", file=sys.stderr)
        return 1

    print("Training XGBoost classifier...")
    booster, metrics = train_xgboost_classifier(X, y)
    print(f"  Test AUC: {metrics['test_auc']:.4f}")
    print(metrics["classification_report"])

    save_model(
        booster,
        Path(args.output_model),
        Path(args.output_meta),
        metrics=metrics,
        min_win_probability=args.min_win_prob,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
