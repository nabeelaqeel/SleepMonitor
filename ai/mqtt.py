"""Lightweight MQTT publisher used only by the AI recommendation module."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

import paho.mqtt.client as mqtt

AI_CLIENT_ID_PREFIX = "sleep-ai-recommendation-"


def build_client() -> mqtt.Client:
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=AI_CLIENT_ID_PREFIX + str(os.getpid()),
    )
    user = os.getenv("MQTT_USER")
    password = os.getenv("MQTT_PASSWORD")
    if user:
        client.username_pw_set(user, password or "")
    return client


def publish(
    topic: str,
    payload: Mapping[str, Any],
    *,
    qos: int = 1,
    retain: bool = False,
    timeout: float = 5.0,
) -> None:
    host = os.getenv("MQTT_HOST", "localhost")
    port = int(os.getenv("MQTT_PORT", "1883"))
    client = build_client()
    client.connect(host, port, keepalive=60)
    client.loop_start()
    info = client.publish(topic, json.dumps(payload, default=str), qos=qos, retain=retain)
    info.wait_for_publish(timeout=timeout)
    client.loop_stop()
    client.disconnect()
