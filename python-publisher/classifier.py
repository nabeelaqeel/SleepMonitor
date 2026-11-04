"""
Rule-based sleep tier classifier for the Sleep Monitor FYP.

Classifies a single sensor reading into one of four tiers:
  Critical   — SpO2 < 90%
  Important  — SpO2 90-94%
  Normal     — SpO2 >= 95%
  Background — periodic stats (publisher handles this separately)

Replace classify() with a trained scikit-learn model call when available:
    features = [[spo2, heart_rate, hrv, motion]]
    return _MODEL.predict(features)[0]
"""

from __future__ import annotations


# ── Thresholds ────────────────────────────────────────────────
SPO2_CRITICAL_THRESHOLD  = 90.0
SPO2_IMPORTANT_THRESHOLD = 95.0


def classify(spo2: float, heart_rate: float, hrv: float, motion: float) -> tuple[str, str, int]:
    """
    Classify a reading into a tier.

    Returns:
        (tier, reason, qos)
        tier   — 'Critical' | 'Important' | 'Normal'
        reason — human-readable explanation
        qos    — MQTT QoS level to use (2 / 1 / 0)
    """
    if spo2 < SPO2_CRITICAL_THRESHOLD:
        reason = f"SpO2 critically low ({spo2:.1f}%) — apnea suspected"
        return "Critical", reason, 2

    if spo2 < SPO2_IMPORTANT_THRESHOLD:
        reason = f"SpO2 in borderline range ({spo2:.1f}%) — abnormal trend"
        return "Important", reason, 1

    return "Normal", "", 0
