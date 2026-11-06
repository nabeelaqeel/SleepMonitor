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
    host: str | None = None,
    port: int | None = None,
) -> None:
    broker_host = host or os.getenv("MQTT_HOST", "localhost")
    broker_port = port if port is not None else int(os.getenv("MQTT_PORT", "1883"))
    client = build_client()
    client.connect(broker_host, broker_port, keepalive=60)
    try:
        client.loop_start()
        info = client.publish(topic, json.dumps(payload, default=str), qos=qos, retain=retain)
        info.wait_for_publish(timeout=timeout)
        if not info.is_published():
            raise RuntimeError(
                f"MQTT publish to {topic} did not complete within {timeout}s"
            )
    finally:
        client.loop_stop()
        client.disconnect()
