"""Unit tests for the AI session loader."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from ai.session_loader import latest_session_for_patient


class LatestSessionForPatientTestCase(unittest.TestCase):
    def test_returns_latest_session_id(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = ("abc",)
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cursor

        with patch("psycopg2.connect", return_value=conn):
            session_id = latest_session_for_patient("00000000-0000-0000-0000-000000000002")

        self.assertEqual(session_id, "abc")

    def test_raises_when_no_session_exists(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value = cursor

        with patch("psycopg2.connect", return_value=conn):
            with self.assertRaises(RuntimeError):
                latest_session_for_patient("00000000-0000-0000-0000-000000000002")


if __name__ == "__main__":
    unittest.main()
