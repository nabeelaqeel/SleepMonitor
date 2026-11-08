"""Nightly feature computation for the AI recommendation module.

This module is self-contained. It intentionally avoids PAAWS-specific code from
the upstream repo so that SleepMonitor can compute the same core 16 features
from a normal watch/sensor session stored in PostgreSQL or a CSV.

The purpose is to bridge session data into the 16 nightly features expected by
`ai.classifier.Phase2Classifier`. Missingness is preserved as NaN.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .config import FeatureConfig, load_config

NIGHTLY_FEATURES = [
    "hr_median",
    "hr_iqr",
    "hr_p5",
    "hr_p95",
    "hr_std",
    "rmssd_median",
    "rmssd_iqr",
    "spo2_median",
    "spo2_iqr",
    "spo2_p5",
    "spo2_min",
    "spo2_below90_frac",
    "spo2_t90_per_valid_h",
    "activity_mean",
    "activity_std",
    "activity_p95",
]

# Extra metadata the model is never fed, but useful for audit/QC.
NIGHTLY_META = [
    "n_readings",
    "hr_coverage",
    "spo2_coverage",
    "rmssd_coverage",
    "hrv_sufficient",
    "sleep_minutes",
]

EPOCH_FEATURES = list(NIGHTLY_FEATURES)

MAYBE_MISSING = {None, "None", "nan", "NaN"}


def normalize_features(features: dict[str, Any]) -> dict[str, float]:
    """Coerce a nightly feature dict into the exact feature names the model expects."""
    allowed = set(NIGHTLY_FEATURES)
    return {k: float(v) if k in allowed and v is not None else np.nan for k, v in features.items()}


def aggregate_nightly(epochs: pd.DataFrame, cfg: FeatureConfig | None = None) -> dict:
    """Compute nightly feature values from epoch rows.

    `epochs` is a DataFrame of rows that each contain at least one of:

    * `hr`
    * `rmssd_ms`
    * `spo2`
    * `activity`
    * optional `hrv_valid`, `hr_coverage`, `spo2_coverage`
    * optional `duration_s` and `offset_s`

    This function is intentionally simple: `epochwise` feature details from the
    upstream AI repo are not used here because SleepMonitor data is not PAAWS
    PSG data and does not carry torso/posture annotations. It stays live-safe:
    only features known at inference time are computed.
    """

    cfg = cfg or load_config().features
    out: dict[str, float | int] = {}
    n = int(len(epochs))
    out["n_readings"] = n
    out["sleep_minutes"] = round(n * cfg.epoch_seconds / 60.0, 2) if n else np.nan

    def _valid(values: pd.Series, lo: float, hi: float) -> np.ndarray:
        """Series to floats, trimmed to finite values inside [lo, hi]."""
        arr = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
        return arr[np.isfinite(arr) & (arr >= lo) & (arr <= hi)]

    hr_arr = pd.to_numeric(epochs.get("hr", pd.Series(dtype="float64")), errors="coerce").to_numpy(float)
    hr_valid = _valid(epochs.get("hr", pd.Series(dtype="float64")), *cfg.hr_valid_bpm)
    if not np.isfinite(hr_valid).any():
        hr_valid = np.array([], dtype=float)
    if len(hr_valid):
        out["hr_median"] = round(float(np.median(hr_valid)), 2)
        out["hr_iqr"] = round(float(np.percentile(hr_valid, 75) - np.percentile(hr_valid, 25)), 2)
        out["hr_p5"] = round(float(np.percentile(hr_valid, 5)), 2)
        out["hr_p95"] = round(float(np.percentile(hr_valid, 95)), 2)
        out["hr_std"] = round(float(np.std(hr_valid)), 2)
    else:
        out["hr_median"] = np.nan
        out["hr_iqr"] = np.nan
        out["hr_p5"] = np.nan
        out["hr_p95"] = np.nan
        out["hr_std"] = np.nan
    out["hr_coverage"] = round(float(np.isfinite(hr_arr).mean()), 4) if n else np.nan

    rmssd = pd.to_numeric(epochs.get("rmssd_ms", pd.Series(dtype="float64")), errors="coerce").to_numpy(float)
    rmssd_valid = rmssd[np.isfinite(rmssd)]
    out["rmssd_coverage"] = round(float(np.isfinite(rmssd).mean()), 4) if n else np.nan
    out["hrv_sufficient"] = bool((np.isfinite(rmssd).sum()) >= cfg.hrv_min_nightly_epochs)
    if out["hrv_sufficient"] and rmssd_valid.size:
        out["rmssd_median"] = round(float(np.median(rmssd_valid)), 2)
        out["rmssd_iqr"] = round(float(np.percentile(rmssd_valid, 75) - np.percentile(rmssd_valid, 25)), 2)
    else:
        out["rmssd_median"] = np.nan
        out["rmssd_iqr"] = np.nan

    spo2 = pd.to_numeric(epochs.get("spo2", pd.Series(dtype="float64")), errors="coerce").to_numpy(float)
    valid_spo2 = spo2[np.isfinite(spo2) & (spo2 >= cfg.spo2_valid_pct[0]) & (spo2 <= cfg.spo2_valid_pct[1])]
    if len(valid_spo2):
        out["spo2_median"] = round(float(np.median(valid_spo2)), 2)
        out["spo2_iqr"] = round(float(np.percentile(valid_spo2, 75) - np.percentile(valid_spo2, 25)), 2)
        out["spo2_p5"] = round(float(np.percentile(valid_spo2, 5)), 2)
        out["spo2_min"] = round(float(np.min(valid_spo2)), 2)
        below = float((valid_spo2 < cfg.desat_threshold_pct).mean())
        out["spo2_below90_frac"] = round(below, 4)
        valid_hours = len(valid_spo2) * cfg.epoch_seconds / 3600.0
        below_hours = below * valid_hours
        if valid_hours > 0:
            out["spo2_t90_per_valid_h"] = round(below_hours / valid_hours, 4)
        else:
            out["spo2_t90_per_valid_h"] = np.nan
    else:
        out["spo2_median"] = np.nan
        out["spo2_iqr"] = np.nan
        out["spo2_p5"] = np.nan
        out["spo2_min"] = np.nan
        out["spo2_below90_frac"] = np.nan
        out["spo2_t90_per_valid_h"] = np.nan
    out["spo2_coverage"] = round(float(np.isfinite(spo2).mean()), 4) if n else np.nan

    activity = pd.to_numeric(epochs.get("activity", pd.Series(dtype="float64")), errors="coerce").dropna()
    if len(activity):
        out["activity_mean"] = round(float(activity.mean()), 5)
        out["activity_std"] = round(float(activity.std()), 5)
        out["activity_p95"] = round(float(activity.quantile(0.95)), 5)
    else:
        out["activity_mean"] = np.nan
        out["activity_std"] = np.nan
        out["activity_p95"] = np.nan

    return {k: out.get(k, np.nan) for k in NIGHTLY_FEATURES}
