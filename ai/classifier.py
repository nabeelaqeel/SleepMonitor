"""Trained-model wrapper used by nightly analysis only.

All outputs are non-diagnostic guidance bands, never diagnoses. The implementation
is intentionally local so SleepMonitor does not need the whole upstream repo.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .config import AI_RECOMMENDATION_DISCLAIMER, DISCLAIMER

MODEL_PATH = Path(__file__).resolve().parent / "models" / "rf_phase2.joblib"


@dataclass
class Phase2Classifier:
    model: object
    feature_names: list[str]
    label_order: list[str] = field(default_factory=list)
    label_rule: str = "worst_reliable_night"
    threshold_2class: float = 0.5
    config_path: str = ""
    target_recall: float = 0.85
    fitted_on: str = ""
    positive_class: str = "see_doctor"
    extra: dict = field(default_factory=dict)

    def frame_from_dict(self, features: dict) -> pd.DataFrame:
        missing = [c for c in self.feature_names if c not in features]
        if missing:
            raise KeyError(f"missing feature values: {missing}")
        data = {c: [features[c]] for c in self.feature_names}
        return pd.DataFrame(data, columns=list(self.feature_names), dtype=float)

    def predict_full(self, features: dict | pd.DataFrame) -> dict:
        """One predict_proba call is enough: bands, probabilities and threshold."""
        df = features if isinstance(features, pd.DataFrame) else self.frame_from_dict(features)
        proba = self.model.predict_proba(df.to_numpy(dtype=float))
        classes = [str(c) for c in self.model.classes_]
        p = {c: float(proba[0, j]) for j, c in enumerate(classes)}
        band = max(p, key=p.get)
        pos = (self.positive_class if (self.positive_class and self.positive_class in p)
               else classes[-1])
        return {
            "band": band,
            "probabilities": p,
            "p_positive": p[pos],
            "positive_class": pos,
            "flagged_positive": bool(p[pos] >= self.threshold_2class),
            "threshold": self.threshold_2class,
            "disclaimer": DISCLAIMER,
        }

    def predict_bands(self, features: dict | pd.DataFrame) -> list[dict]:
        """Back-compatible batch view."""
        df = features if isinstance(features, pd.DataFrame) else self.frame_from_dict(features)
        proba = self.model.predict_proba(df.to_numpy(dtype=float))
        classes = [str(c) for c in self.model.classes_]
        out = []
        for i in range(len(df)):
            p = {c: float(proba[i, j]) for j, c in enumerate(classes)}
            out.append({"band": max(p, key=p.get), "probabilities": p})
        return out


def _register_model_modules() -> None:
    """Register a minimal alias map so joblib can unpickle the artifact."""
    if "src.model.classifier" in sys.modules:
        return
    mod = types.ModuleType("src.model.classifier")
    mod.Phase2Classifier = Phase2Classifier
    parent = types.ModuleType("src.model")
    parent.classifier = mod
    root = types.ModuleType("src")
    root.model = parent
    root.features = types.ModuleType("src.features.config")  # Populate below
    sys.modules.update(
        {
            "src": root,
            "src.model": parent,
            "src.model.classifier": mod,
        }
    )


def load(path: Path | str | None = None) -> Phase2Classifier:
    _register_model_modules()
    return joblib.load(Path(path) if path else MODEL_PATH)
