"""Unit tests for the AI nightly adapter and payload."""

from __future__ import annotations

import json
import math
import unittest
from unittest.mock import MagicMock, patch
from ai.nightly_adapter import get_recommendation, session_to_nightly_features
from ai.recommend import recommendation_payload


class SessionToNightlyFeaturesTestCase(unittest.TestCase):
    def test_maps_heart_rate_from_postgres_column(self):
        readings = [{"spo2": 95.0, "heart_rate": 58.0, "hrv": 38.0, "motion": 0.2}]
        nightly = session_to_nightly_features(readings)
        self.assertEqual(nightly["hr_median"], 58.0)

    def test_maps_the_four_key_signals(self):
        readings = [
            {"spo2": 95.0, "heartRate": 60.0, "hrv": 42.0, "motion": 0.1},
            {"spo2": 97.0, "heartRate": 62.0, "hrv": 38.0, "motion": 0.3},
        ]
        nightly = session_to_nightly_features(readings, session_id="s1", patient_id="p1")

        self.assertEqual(nightly["session_id"], "s1")
        self.assertEqual(nightly["patient_id"], "p1")
        self.assertIn("hr_median", nightly)
        self.assertIn("rmssd_median", nightly)
        self.assertIn("spo2_median", nightly)
        self.assertIn("activity_mean", nightly)

    def test_empty_readings_report_error(self):
        nightly = session_to_nightly_features([])
        self.assertTrue(nightly.get("error"))


class GetRecommendationTestCase(unittest.TestCase):
    def test_empty_readings_report_error(self):
        result = get_recommendation([], session_id="empty", patient_id="p")
        self.assertTrue(result["nightly"].get("error"))
        self.assertIsNone(result["band"])

    def test_short_session_is_not_interpreted(self):
        readings = [
            {"timestamp": "2026-11-04T01:00:00Z", "spo2": 97, "heartRate": 60, "hrv": 40, "motion": 0.1},
            {"timestamp": "2026-11-04T01:59:00Z", "spo2": 97, "heartRate": 60, "hrv": 40, "motion": 0.1},
        ]
        with patch("ai.nightly_adapter.load_config") as load_config:
            load_config.return_value.min_tst_h = 2.0
            result = get_recommendation(readings, session_id="short", patient_id="p")

        self.assertIsNone(result["band"])
        self.assertEqual(result["nightly"]["error"], "session shorter than min_tst_h")
        self.assertLess(result["nightly"]["duration_hours"], 2.0)


class RecommendationPayloadTestCase(unittest.TestCase):
    def test_payload_only_exposes_needed_fields(self):
        result = {
            "session_id": "abc",
            "patient_id": "pd",
            "band": "monitor",
            "p_positive": 0.5,
            "flagged_positive": False,
            "disclaimer": "Research guidance band only.",
            "not_sent": "private",
        }
        payload = recommendation_payload(result)

        self.assertEqual(payload["sessionId"], "abc")
        self.assertEqual(payload["patientId"], "pd")
        self.assertEqual(payload["band"], "monitor")
        self.assertEqual(payload["disclaimer"], "Research guidance band only.")
        self.assertNotIn("not_sent", payload)

    def test_payload_carries_report_export_fields(self):
        """The export fields the nightly PDF needs ride along in the payload."""
        result = {
            "session_id": "abc",
            "patient_id": "pd",
            "band": "monitor",
            "p_positive": 0.5,
            "flagged_positive": True,
            "threshold": 0.1292,
            "window": {"start": "2026-11-04T01:00:00+00:00",
                       "end": "2026-11-04T07:30:00+00:00"},
            "model_version": "rf_phase2.joblib",
            "trained_on": "139 participants, PAAWS R2 v1.3",
            "disclaimer": "Research guidance band only.",
            "nightly": {
                "hr_median": 55.2,
                "spo2_below90_frac": 0.04,
                "rmssd_coverage": 0.82,
                "hrv_sufficient": True,
                "sleep_minutes": 396.0,
            },
        }
        payload = recommendation_payload(result)

        self.assertEqual(payload["threshold"], 0.1292)
        self.assertEqual(payload["window"]["start"], "2026-11-04T01:00:00+00:00")
        self.assertEqual(payload["modelVersion"], "rf_phase2.joblib")
        self.assertEqual(payload["trainedOn"], "139 participants, PAAWS R2 v1.3")
        self.assertEqual(payload["nightly"]["hr_median"], 55.2)

        # The extended payload must stay strict-JSON-safe, since it travels
        # over MQTT and is parsed phone-side.
        json.dumps(payload, allow_nan=False)

    def test_nightly_nan_becomes_null_in_payload(self):
        """NaN nightly features serialize as JSON null, never bare NaN."""
        result = {
            "session_id": "abc",
            "band": None,
            "p_positive": 0.5,
            "flagged_positive": False,
            "disclaimer": "Research guidance band only.",
            "nightly": {"rmssd_median": math.nan},
        }
        payload = recommendation_payload(result)

        self.assertIsNone(payload["nightly"]["rmssd_median"])
        json.dumps(payload, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
