"""Unit tests for the AI MQTT publisher."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from ai.mqtt import publish


class PublishTestCase(unittest.TestCase):
    def test_publishes_one_message_with_expected_qos_and_retain(self):
        client = MagicMock()
        with patch("ai.mqtt.build_client", return_value=client):
            publish("sleep/recommendation", {"band": "monitor"}, qos=1, retain=False)

        client.publish.assert_called_once_with(
            "sleep/recommendation",
            '{"band": "monitor"}',
            qos=1,
            retain=False,
        )
        client.connect.assert_called_once()
        client.disconnect.assert_called_once()
        client.loop_start.assert_called_once()
        client.loop_stop.assert_called_once()

    def test_unpublished_message_raises_and_cleans_up(self):
        client = MagicMock()
        info = MagicMock()
        info.is_published.return_value = False
        client.publish.return_value = info

        with patch("ai.mqtt.build_client", return_value=client):
            with self.assertRaises(RuntimeError):
                publish("sleep/recommendation", {"band": "monitor"})

        client.disconnect.assert_called_once()
        client.loop_stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
