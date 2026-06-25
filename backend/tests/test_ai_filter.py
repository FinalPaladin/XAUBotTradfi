"""Tests for Meta-Labeling AI filter."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.config import BACKEND_ROOT
from app.trading.ai.ai_filter import MetaLabelingFilter
from app.trading.ai.features import FEATURE_NAMES, features_to_vector
from app.trading.signal_engine import (
    MainTrend,
    _apply_ai_meta_filter,
    _filter_entry_signal,
)
from app.trading.types import NetSignal

MODEL_PATH = BACKEND_ROOT / "data" / "meta_model.xgb"


@pytest.fixture
def sample_features() -> dict[str, float]:
    return {name: float(i) * 0.01 for i, name in enumerate(FEATURE_NAMES)}


def test_features_to_vector_order(sample_features: dict[str, float]) -> None:
    vec = features_to_vector(sample_features)
    assert len(vec) == len(FEATURE_NAMES)


@pytest.mark.skipif(not MODEL_PATH.is_file(), reason="meta_model.xgb chưa train")
def test_predict_win_probability_fast(sample_features: dict[str, float]) -> None:
    import time

    filt = MetaLabelingFilter(model_path=MODEL_PATH)
    assert filt.is_active

    start = time.perf_counter()
    for _ in range(100):
        prob = filt.predict_win_probability(sample_features)
    elapsed_ms = (time.perf_counter() - start) * 10.0
    assert elapsed_ms < 100.0, f"100 predicts took {elapsed_ms:.1f}ms (expect <100ms total)"
    assert 0.0 <= prob <= 100.0


def test_ai_filter_blocks_low_probability() -> None:
    mock_filter = MagicMock()
    mock_filter.is_active = True
    mock_filter.min_win_probability = 55.0
    mock_filter.predict_win_probability.return_value = 40.0

    net, scalp, log = _apply_ai_meta_filter(
        int(NetSignal.BUY),
        False,
        "Allowed LONG",
        ai_filter=mock_filter,
        ai_features={"direction": 1.0},
    )
    assert net == int(NetSignal.HOLD)
    assert "[AI FILTER] Blocked entry due to low win probability" in log


def test_filter_entry_signal_with_ai_passes_high_prob() -> None:
    mock_filter = MagicMock()
    mock_filter.is_active = True
    mock_filter.min_win_probability = 55.0
    mock_filter.predict_win_probability.return_value = 72.5

    net, scalp, log = _filter_entry_signal(
        int(NetSignal.BUY),
        0.7,
        MainTrend.BULLISH,
        entry_threshold=0.65,
        scalp_threshold=0.8,
        super_safe=False,
        ai_filter=mock_filter,
        ai_features={"direction": 1.0},
    )
    assert net == int(NetSignal.BUY)
    assert scalp is False
    assert "[AI FILTER] Win probability 72.5%" in log
