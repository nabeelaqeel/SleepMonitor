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
    if "hr" not in df:
        for key in ("heartRate", "heart_rate"):
            if key in df:
                df["hr"] = df[key]
                break
    nightly = aggregate_nightly(df, cfg.features)
    if session_id:
        nightly["session_id"] = session_id
    if patient_id:
        nightly["patient_id"] = patient_id
    return nightly


def _session_duration_hours(session_readings: list[dict]) -> float | None:
    """Derive duration from the stored reading timestamps.

    This deliberately avoids assuming a fixed reading cadence, because the ingest
    worker does not impose one; it also keeps the AI module independent from the
    QoS pipeline.
    """
    timestamps = [
        pd.to_datetime(
            reading.get("timestamp", reading.get("ts")),
            errors="coerce",
            utc=True,
        )
        for reading in session_readings
    ]
    timestamps = [ts for ts in timestamps if pd.notna(ts)]
    if not timestamps or len(timestamps) < 2:
        return None

    return (max(timestamps) - min(timestamps)).total_seconds() / 3600.0


def _session_quality(
    session_readings: list[dict],
    cfg,
) -> tuple[float, float] | None:
    """Measure valid-reading coverage and the largest timestamp gap."""
    timestamps: list = []
    for reading in session_readings:
        ts = pd.to_datetime(
            reading.get("timestamp", reading.get("ts")),
            errors="coerce",
            utc=True,
        )
        if pd.isna(ts):
            continue

        has_signal = any(
            pd.notna(reading.get(key))
            for key in ("spo2", "heartRate", "heart_rate", "hrv", "motion")
        )
        if has_signal:
            timestamps.append(ts)

    timestamps.sort()
    if len(timestamps) < 2:
        return None

    duration_seconds = (timestamps[-1] - timestamps[0]).total_seconds()
    if duration_seconds <= 0:
        return None

    expected_readings = max(1, int(duration_seconds // cfg.features.epoch_seconds))
    coverage = len(timestamps) / expected_readings
    max_gap_seconds = max(
        (later - earlier).total_seconds()
        for earlier, later in zip(timestamps, timestamps[1:])
    )
    return coverage, max_gap_seconds


def _unavailable_result(
    *,
    session_id: str | None = None,
    patient_id: str | None = None,
    nightly: dict,
) -> dict:
    return {
        "band": None,
        "probabilities": {},
        "p_positive": None,
        "positive_class": None,
        "flagged_positive": False,
        "threshold": None,
        "nightly": nightly,
        "session_id": session_id,
        "patient_id": patient_id,
        "disclaimer": "AI recommendation unavailable.",
    }


def get_recommendation(
    session_readings: list[dict],
    *,
    session_id: str | None = None,
    patient_id: str | None = None,
) -> dict:
    """Run the full pipeline: session data -> features -> model -> band.

    A session shorter than `min_tst_h` is not interpreted, because the trained
    model is only valid on nightly sessions above this threshold.
    """
    cfg = load_config()
    duration_hours = _session_duration_hours(session_readings)
    if duration_hours is None or duration_hours < cfg.min_tst_h:
        return {
            "band": None,
            "probabilities": {},
            "p_positive": None,
            "positive_class": None,
            "flagged_positive": False,
            "threshold": None,
            "nightly": {
                "error": "session shorter than min_tst_h",
                "duration_hours": duration_hours,
                "min_tst_h": cfg.min_tst_h,
            },
            "session_id": session_id,
            "patient_id": patient_id,
            "disclaimer": "AI recommendation unavailable.",
        }
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

    quality = _session_quality(session_readings, cfg)
    if quality is None:
        return _unavailable_result(
            session_id=session_id,
            patient_id=patient_id,
            nightly={"error": "insufficient valid readings"},
        )

    coverage, max_gap_seconds = quality
    if (
        coverage < cfg.features.min_valid_reading_coverage
        or max_gap_seconds > cfg.features.max_gap_seconds
    ):
        return _unavailable_result(
            session_id=session_id,
            patient_id=patient_id,
            nightly={
                "error": "session does not meet coverage/gap criteria",
                "coverage": coverage,
                "max_gap_seconds": max_gap_seconds,
                "min_valid_reading_coverage": cfg.features.min_valid_reading_coverage,
                "max_gap_seconds": cfg.features.max_gap_seconds,
            },
        )

    clf: Phase2Classifier = load_classifier()
    nightly_frame = pd.DataFrame([nightly])[clf.feature_names]
    result = clf.predict_full(nightly_frame)
    result["nightly"] = nightly
    result["session_id"] = session_id
    result["patient_id"] = patient_id
    return result
