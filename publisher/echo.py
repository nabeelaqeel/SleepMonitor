"""Sleep Monitor — MQTT ping/echo responder.

Relays latency probe messages back to the app so it can measure
round-trip time (RTT) without needing a synchronised clock:

    app  --publish qos/ping (QoS Q)-->  broker  -->  echo.py
    app  <--publish qos/pong (QoS Q)--  broker  <--

The payload is passed through verbatim; echo.py never computes latency.
Run it on the same host as the broker (the laptop) so the only measured
hop is app <-> broker. Without it running, the app's latency readout
shows "—".

Configuration is via environment variables (see .env.development).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
from pathlib import Path

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

# Anchor the env file to the repo root so the echo responder loads the same
# configuration wherever it is launched from.
load_dotenv(Path(__file__).resolve().parents[1] / ".env.development")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("echo")

# ── Config ────────────────────────────────────────────────────
MQTT_HOST     = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT     = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER     = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
CLIENT_ID     = os.getenv("ECHO_CLIENT_ID", "sleep-echo-001")

PING_TOPIC = "qos/ping"
PONG_TOPIC = "qos/pong"


# ── MQTT callbacks ────────────────────────────────────────────

def on_connect(client, userdata, connect_flags, reason_code, properties=None):
    """Subscribe to qos/ping at QoS 2, or exit when the broker refuses the connection."""
    if reason_code.is_failure:
        log.error("Connection refused — %s", reason_code)
        sys.exit(1)
    client.subscribe(PING_TOPIC, qos=2)
    log.info("Connected to %s:%d — listening on %s (QoS 2)", MQTT_HOST, MQTT_PORT, PING_TOPIC)


def on_message(client, userdata, msg):
    """Echo a JSON probe verbatim to qos/pong at the probe's advertised QoS (0-2); drop non-JSON payloads."""
    try:
        payload = json.loads(msg.payload.decode())
    except (ValueError, UnicodeDecodeError):
        log.warning("Non-JSON payload on %s — dropped", msg.topic)
        return

    qos = payload.get("qos", 0)
    if qos not in (0, 1, 2):
        qos = 0
    client.publish(PONG_TOPIC, msg.payload, qos=qos)


# ── Client setup ──────────────────────────────────────────────

def build_client() -> mqtt.Client:
    """Build the MQTT v5 echo client with its persisted client id and wired callbacks."""
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=CLIENT_ID,
        protocol=mqtt.MQTTv5,
    )
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

    client.on_connect = on_connect
    client.on_message = on_message
    return client


def main() -> None:
    """Connect to the broker and relay pings until SIGINT/SIGTERM disconnects the client."""
    client = build_client()

    def handle_signal(sig, frame):
        """Disconnect from the broker on SIGINT/SIGTERM to end loop_forever."""
        log.info("Signal %s received — shutting down", sig)
        client.disconnect()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_forever()
    log.info("Echo responder stopped")


if __name__ == "__main__":
    main()
