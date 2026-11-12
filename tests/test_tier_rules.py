"""Boundary and precedence tests for the four-tier classification.

publisher/tier_rules.classify() is the single source of truth every
consumer (publisher, benchmark runner, analysis) shares, so its
boundaries are pinned here as a table: each row asserts the exact tier
AND the QoS that tier maps to, taken from TIER_QOS itself so a mapping
edit and a rule edit can never silently diverge.

The thresholds are half-open on purpose (Critical is SpO2 < 90, not
<=), so each boundary value belongs to exactly one neighbour — the
table records which. Overlap precedence (top-to-bottom evaluation) gets
its own tests using the module docstring's worked examples.

Imported by absolute file path, and here is why: other test modules
legitimately leave script directories on sys.path (benchmark inserts
publisher/ so run_benchmark can `import tier_rules` top-level). With
that entry in place, `from publisher.tier_rules import ...` resolves
`publisher` to publisher/publisher.py — a MODULE, not a package — and
dies with "'publisher' is not a package". Loading the file directly
makes this suite immune to any sys.path order anywhere.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_TIER_RULES_PATH = (
    Path(__file__).resolve().parents[1] / "publisher" / "tier_rules.py"
)
_spec = importlib.util.spec_from_file_location(
    "publisher_tier_rules_under_test", _TIER_RULES_PATH
)
tier_rules = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tier_rules)

TIER_QOS = tier_rules.TIER_QOS
classify = tier_rules.classify

# (spo2, heart_rate, hrv, motion, expected_tier) — boundary values only
CASES = [
    pytest.param(89.9, 65.0, 40.0, 0.0, "Critical", id="spo2 just under 90"),
    pytest.param(97.0, 39.9, 40.0, 0.0, "Critical", id="hr just under 40"),
    pytest.param(97.0, 100.1, 40.0, 0.0, "Critical", id="hr just over 100"),
    pytest.param(94.9, 65.0, 40.0, 0.0, "Important", id="spo2 borderline"),
    pytest.param(97.0, 49.9, 40.0, 0.0, "Important", id="hr just under 50"),
    pytest.param(97.0, 90.1, 40.0, 0.0, "Important", id="hr just over 90"),
    pytest.param(97.0, 65.0, 19.9, 0.0, "Important", id="hrv just under 20"),
    pytest.param(95.0, 50.0, 20.0, 0.0, "Normal", id="normal at both band lows"),
    pytest.param(
        100.0, 90.0, 20.0, 9.9, "Normal", id="normal at both band highs, moving"
    ),
    pytest.param(101.0, 65.0, 40.0, 0.0, "Background", id="spo2 over sensor clamp"),
    pytest.param(100.0, 110.0, 40.0, 0.0, "Critical", id="crash spike over hr 100"),
]


@pytest.mark.parametrize("spo2,hr,hrv,motion,expected_tier", CASES)
def test_classification_table(spo2, hr, hrv, motion, expected_tier):
    """Each boundary row lands in its tier with the TIER_QOS-backed QoS."""
    tier, _reason, qos = classify(spo2, hr, hrv, motion)
    assert tier == expected_tier
    assert qos == TIER_QOS[tier]


def test_reason_explains_itself_outside_normal():
    """Every tier except Normal returns a reason; Normal is silent."""
    assert classify(89.9, 65.0, 40.0, 0.0)[1]
    assert classify(94.9, 65.0, 40.0, 0.0)[1]
    assert classify(97.0, 65.0, 19.9, 0.0)[1]
    assert classify(101.0, 65.0, 40.0, 0.0)[1]
    assert classify(95.0, 62.0, 40.0, 0.0)[1] == ""


def test_critical_beats_borderline_on_overlap():
    """Rules evaluate strictly top-to-bottom: spo2 89 + hr 105 is Critical.

    Both the Critical and Important guards match; the FIRST one wins, so
    the reason names SpO2 — the apnea signal takes precedence over the
    borderline rate.
    """
    tier, reason, _qos = classify(89.0, 105.0, 40.0, 0.0)
    assert tier == "Critical"
    assert "SpO2" in reason


def test_borderline_hr_beats_normal_band():
    """HR 45 with otherwise-healthy signals is Important, never Normal.

    The module docstring's worked example: 45 is above the Critical low
    (40) but below the Normal band (50), leaving only Important.
    """
    assert classify(97.0, 45.0, 45.0, 0.0)[0] == "Important"


def test_motion_never_affects_the_tier():
    """Motion is recorded in the row but appears in no rule — a restless
    sleeper with healthy vitals is not graded as more at-risk."""
    still = classify(95.0, 60.0, 30.0, 0.0)[0]
    restless = classify(95.0, 60.0, 30.0, 9.9)[0]
    assert still == restless == "Normal"
