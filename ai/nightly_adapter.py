"""Adapt a completed sleep session to the AI feature pipeline."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .classifier import Phase2Classifier, load as load_classifier
from .config import load_config
from .features import NIGHTLY_FEATURES, aggregate_nightly


def session_to_nightly_features(
    session_readings: list[dict],
    *,
    session_id: str | None = None,
    patient_id: str | None = None,
) -> dict:
    """Convert completed-session readings into nightly features.

    Each reading dict should have: timestamp, spo2, heart_rate, hrv (rmssd),
    motion (activity). Missing values stay NaN/None. Optional helpers:
    `activity` (if you prefer this name over motion), `rmssd_ms`, `hr`,
    `spo2` are accepted.
    """
    cfg = load_config()
    if not session_readings:
        return {"error": "no readings", "disclaimer": "AI recommendation unavailable."}
    df = pd.DataFrame(session_readings)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    if "rmssd_ms" not in df and "hrv" in df:
        df["rmssd_ms"] = df["hrv"]
    if "activity" not in df and "motion" in df:
        df["activity"] = df["motion"]
    nightly = aggregate_nightly(df, cfg.features)
    if session_id:
        nightly["session_id"] = session_id
    if patient_id:
        nightly["patient_id"] = patient_id
    return nightly


def get_recommendation(
    session_readings: list[dict],
    *,
    session_id: str | None = None,
    patient_id: str | None = None,
) -> dict:
    """Run the full pipeline: session data -> features -> model -> band."""
    nightly = session_to_nightly_features(
        session_readings,
        session_id=session_id,
        patient_id=patient_id,
    )
    if not nightly or nightly.get("error"):
        return {
            "band": None,
            "probabilities": {},
            "p_positive": None,
            "positive_class": None,
            "flagged_positive": False,
            "threshold": None,
            "nightly": nightly,
            "disclaimer": "AI recommendation unavailable.",
        }

    clf: Phase2Classifier = load_classifier()
    nightly_frame = pd.DataFrame([nightly])[clf.feature_names]
    result = clf.predict_full(nightly_frame)
    result["nightly"] = nightly
    result["session_id"] = session_id
    result["patient_id"] = patient_id
    return result
