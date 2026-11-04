"""Unit tests for the AI nightly adapter and payload."""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
