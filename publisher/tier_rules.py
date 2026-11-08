"""
Single source of truth for the Sleep Monitor tier system.

Classifies a single sensor reading into one of four tiers:

  Critical   — SpO2 < 90%  OR HR < 40 bpm  OR HR > 100 bpm        (QoS 2)
  Important  — SpO2 90-94% OR HR < 50/ > 90  OR HRV < 20 ms       (QoS 1)
  Normal     — SpO2 95-100% AND HR 50-90 bpm                      (QoS 0)
  Background — all other readings (out-of-band / periodic stats)  (QoS 0)

Rules are evaluated strictly top-to-bottom, so the overlap in the HR
ranges resolves the same way every time (e.g. HR 45 → Important, never
Normal; HR 105 → Critical, not Important).

Edit the thresholds below and every consumer — publisher, benchmark
runner, benchmark analysis — picks the change up. The tier→QoS mapping
is defined in TIER_QOS and reused in classify() so the two can never
diverge.

Replace classify() with a trained scikit-learn model call when available:
    features = [[spo2, heart_rate, hrv, motion]]
    return _MODEL.predict(features)[0]
"""

from __future__ import annotations

# ── Tier thresholds — edit these ──────────────────────────────
SPO2_CRITICAL       = 90.0   # SpO2 below this                → Critical
HR_CRITICAL_LOW     = 40.0   # HR below this                  → Critical
HR_CRITICAL_HIGH    = 100.0  # HR above this                  → Critical

SPO2_IMPORTANT      = 95.0   # SpO2 below this (after Critical) → Important
HR_IMPORTANT_LOW    = 50.0   # HR below this  (after Critical)  → Important
HR_IMPORTANT_HIGH   = 90.0   # HR above this  (after Critical)  → Important
HRV_IMPORTANT       = 20.0   # HRV below this                   → Important

SPO2_NORMAL_MIN     = 95.0   # Normal band lower bound (in SpO2 95-100; 100 included
SPO2_NORMAL_MAX     = 100.0  # because many sensors clamp exactly at 100%)


# ── QoS per tier ─────────────────────────────────────────────
TIER_QOS = {"Critical": 2, "Important": 1, "Normal": 0, "Background": 0}


def classify(spo2: float, heart_rate: float, hrv: float, motion: float) -> tuple[str, str, int]:
    """
    Classify a reading into a tier.

    Returns:
        (tier, reason, qos)
        tier   — 'Critical' | 'Important' | 'Normal' | 'Background'
        reason — human-readable explanation (empty for Normal)
        qos    — MQTT QoS level to use (2 / 1 / 0)
    """
    # 1. Critical — SpO2 < 90 OR HR < 40 OR HR > 100
    if spo2 < SPO2_CRITICAL:
        reason = f"SpO2 critically low ({spo2:.1f}%) — apnea suspected"
        return "Critical", reason, TIER_QOS["Critical"]

    if heart_rate < HR_CRITICAL_LOW:
        reason = f"Heart rate critically low ({heart_rate:.1f} bpm) — bradycardia"
        return "Critical", reason, TIER_QOS["Critical"]

    if heart_rate > HR_CRITICAL_HIGH:
        reason = f"Heart rate critically high ({heart_rate:.1f} bpm) — tachycardia"
        return "Critical", reason, TIER_QOS["Critical"]

    # 2. Important — SpO2 90-94 OR HR 40-50 / 90-100 OR HRV < 20
    if spo2 < SPO2_IMPORTANT:
        reason = f"SpO2 in borderline range ({spo2:.1f}%) — abnormal trend"
        return "Important", reason, TIER_QOS["Important"]

    if heart_rate < HR_IMPORTANT_LOW:
        reason = f"Heart rate borderline low ({heart_rate:.1f} bpm) — below resting band"
        return "Important", reason, TIER_QOS["Important"]

    if heart_rate > HR_IMPORTANT_HIGH:
        reason = f"Heart rate borderline high ({heart_rate:.1f} bpm) — above resting band"
        return "Important", reason, TIER_QOS["Important"]

    if hrv < HRV_IMPORTANT:
        reason = f"HRV very low ({hrv:.1f} ms) — reduced variability"
        return "Important", reason, TIER_QOS["Important"]

    # 3. Normal — SpO2 95-100 AND HR 50-90
    if (SPO2_NORMAL_MIN <= spo2 <= SPO2_NORMAL_MAX
            and HR_IMPORTANT_LOW <= heart_rate <= HR_IMPORTANT_HIGH):
        return "Normal", "", TIER_QOS["Normal"]

    # 4. Background — all other readings (e.g. sensor-saturated or out-of-band values)
    reason = "Reading outside all monitoring bands"
    return "Background", reason, TIER_QOS["Background"]
