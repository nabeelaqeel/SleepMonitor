"""Minimal Phase-2 configuration loader used by the AI recommendation module.

Only the parameters needed by the nightly adapter live here. The broader
clinical pipeline (PAAWS-only) is intentionally not copied into this repo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(__file__).resolve().parent / "config" / "phase2.yaml"

DISCLAIMER = (
    "Research guidance band only. Not a diagnosis, not clinically validated, "
    "and not a substitute for medical review."
)
AI_RECOMMENDATION_DISCLAIMER = DISCLAIMER

# Reproducibility metadata shipped in the sleep/recommendation payload so the
# app can stamp "model version · dataset version" onto exported reports. The
# human-readable dataset lineage per artifact lives in Phase2Classifier.fitted_on
# (e.g. "139 participants, PAAWS R2 v1.3 ...") — MODEL_VERSION only names the file.
MODEL_VERSION = "rf_phase2.joblib"


@dataclass(frozen=True)
class FeatureConfig:
    epoch_seconds: int = 30
    hr_valid_bpm: tuple[float, float] = (20.0, 250.0)
    spo2_valid_pct: tuple[float, float] = (50.0, 120.0)
    desat_threshold_pct: float = 90.0
    rmssd_bounds_ms: tuple[float, float] = (5.0, 200.0)
    posture_change_deg: float = 30.0
    hr_nightly_plausible_bpm: tuple[float, float] = (30.0, 120.0)
    spo2_nightly_plausible_pct: tuple[float, float] = (85.0, 100.0)
    hrv_min_nightly_epochs: int = 30
    min_valid_reading_coverage: float = 0.5
    max_gap_seconds: float = 60.0


@dataclass(frozen=True)
class RuntimeConfig:
    workers: int = 4
    pilot_nights: int = 30
    pilot_seed: int = 42


@dataclass(frozen=True)
class Phase2Config:
    labels_3class: tuple[str, ...] = ("healthy", "monitor", "see_doctor")
    min_tst_h: float = 2.0
    features: FeatureConfig = FeatureConfig()
    runtime: RuntimeConfig = RuntimeConfig()


def load_config(path: Path | str | None = None) -> Phase2Config:
    """Parse the phase-2 YAML into Phase2Config; every key is optional and falls back to the defaults above, labels revert to healthy/monitor/see_doctor when three-class labels are absent."""
    path = Path(path) if path else CONFIG_PATH
    with path.open() as f:
        raw = yaml.safe_load(f)

    lab = raw.get("labels", {})
    three_class = lab.get("three_class", {})
    feat = raw.get("features", {})
    runtime = raw.get("runtime", {})

    features = FeatureConfig(
        epoch_seconds=int(feat.get("epoch_seconds", 30)),
        hr_valid_bpm=tuple(float(v) for v in feat.get("hr_valid_bpm", (20, 250))),
        spo2_valid_pct=tuple(float(v) for v in feat.get("spo2_valid_pct", (50, 120))),
        desat_threshold_pct=float(feat.get("desat_threshold_pct", 90)),
        rmssd_bounds_ms=tuple(float(v) for v in feat.get("rmssd_bounds_ms", (5, 200))),
        posture_change_deg=float(feat.get("posture_change_deg", 30)),
        hr_nightly_plausible_bpm=tuple(
            float(v) for v in feat.get("hr_nightly_plausible_bpm", (30, 120))
        ),
        spo2_nightly_plausible_pct=tuple(
            float(v) for v in feat.get("spo2_nightly_plausible_pct", (85, 100))
        ),
        hrv_min_nightly_epochs=int(feat.get("hrv_min_nightly_epochs", 30)),
        min_valid_reading_coverage=float(
            feat.get("min_valid_reading_coverage", 0.5)
        ),
        max_gap_seconds=float(feat.get("max_gap_seconds", 60)),
    )
    runtime_cfg = RuntimeConfig(
        workers=int(runtime.get("workers", 4)),
        pilot_nights=int(runtime.get("pilot_nights", 30)),
        pilot_seed=int(runtime.get("pilot_seed", 42)),
    )

    labels = tuple(
        str(v)
        for v in (
            "healthy",
            "monitor",
            "see_doctor",
        )
    )
    if len(three_class) == 0:
        labels = tuple(labels)
    return Phase2Config(
        labels_3class=labels,
        min_tst_h=float(lab.get("min_tst_h", 2.0)),
        features=features,
        runtime=runtime_cfg,
    )
