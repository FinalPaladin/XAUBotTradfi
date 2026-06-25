"""
Meta-Labeling inference — load model 1 lần, predict < 10ms/tick.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import xgboost as xgb

from app.config import BACKEND_ROOT
from app.trading.ai.features import FEATURE_NAMES, features_to_vector

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = BACKEND_ROOT / "data" / "meta_model.xgb"
DEFAULT_META_PATH = BACKEND_ROOT / "data" / "meta_model_meta.json"
DEFAULT_MIN_WIN_PROBABILITY = 55.0


class MetaLabelingFilter:
    """
    Lớp phòng ngự AI: lọc entry M5 theo xác suất Win dự báo.

    Model được load vào RAM một lần khi khởi tạo (worker startup).
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        meta_path: str | Path | None = None,
        *,
        min_win_probability: float = DEFAULT_MIN_WIN_PROBABILITY,
    ) -> None:
        self.model_path = Path(model_path or DEFAULT_MODEL_PATH)
        self.meta_path = Path(meta_path or DEFAULT_META_PATH)
        self.min_win_probability = min_win_probability
        self._booster: xgb.Booster | None = None
        self._feature_names: list[str] = list(FEATURE_NAMES)
        self._load_model()

    @property
    def is_active(self) -> bool:
        return self._booster is not None

    def _load_model(self) -> None:
        if not self.model_path.is_file():
            logger.warning(
                "Meta-labeling model not found at %s — AI filter disabled",
                self.model_path,
            )
            return

        try:
            self._booster = xgb.Booster()
            self._booster.load_model(str(self.model_path))
        except Exception:
            logger.exception("Failed to load meta-labeling model from %s", self.model_path)
            self._booster = None
            return

        if self.meta_path.is_file():
            try:
                meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
                names = meta.get("feature_names")
                if names:
                    self._feature_names = list(names)
                threshold = meta.get("min_win_probability")
                if threshold is not None:
                    self.min_win_probability = float(threshold)
            except Exception:
                logger.warning("Could not read meta file %s", self.meta_path)

        logger.info(
            "Meta-labeling model loaded (%s, %d features, threshold=%.1f%%)",
            self.model_path.name,
            len(self._feature_names),
            self.min_win_probability,
        )

    def predict_win_probability(self, features: dict[str, float]) -> float:
        """
        Dự báo xác suất Win (0–100%).

        Trả về 100.0 khi model chưa load (fail-open để không chặn trading).
        """
        if self._booster is None:
            return 100.0

        row = features_to_vector(features)
        if len(self._feature_names) != len(FEATURE_NAMES):
            row = [float(features.get(name, 0.0)) for name in self._feature_names]

        matrix = xgb.DMatrix(
            np.array([row], dtype=np.float32),
            feature_names=self._feature_names,
        )
        prob = float(self._booster.predict(matrix)[0])
        return round(prob * 100.0, 2)


_shared_filter: MetaLabelingFilter | None = None


def get_meta_labeling_filter() -> MetaLabelingFilter:
    """Singleton — worker gọi 1 lần, tái sử dụng mỗi tick."""
    global _shared_filter
    if _shared_filter is None:
        _shared_filter = MetaLabelingFilter()
    return _shared_filter
