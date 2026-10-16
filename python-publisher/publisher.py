"""
Sleep Monitor — MQTT Publisher
Reads sleep_data.csv row by row and publishes each reading as a JSON
payload to the Mosquitto broker, simulating a live sensor stream.

Configuration is via environment variables (see .env.development).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
import uuid
from datetime import datetime, timezone

import pandas as pd
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from classifier import classify

load_dotenv(".env.development")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("publisher")

# ── Config ────────────────────────────────────────────────────
MQTT_HOST        = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT        = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER        = os.getenv("MQTT_USER", "admin")
MQTT_PASSWORD    = os.getenv("MQTT_PASSWORD", "changeme")
CSV_PATH         = os.getenv("CSV_PATH", "/app/data/sleep_data.csv")
PUBLISH_INTERVAL = float(os.getenv("PUBLISH_INTERVAL", "1.0"))
LOOP_CSV         = os.getenv("LOOP_CSV", "true").lower() == "true"
PATIENT_ID       = os.getenv("PATIENT_ID", "patient-001")
DEVICE_ID        = os.getenv("DEVICE_ID", "sleepband-001")
STATS_INTERVAL   = int(os.getenv("STATS_INTERVAL", "10"))  # publish background stats every N rows

# ── Session identity ──────────────────────────────────────────
# The publisher owns the session lifecycle: it mints the ID, emits
# session/start + session/end, and installs an MQTT Last Will so a
# crash still closes the session. `_seq` is the monotonic per-session
# reading counter; the ingest worker dedups on (sessionId, seq) and
# uses seq gaps to measure QoS 0 loss.
SESSION_ID = str(uuid.uuid4())
_seq = 0

# ── State ─────────────────────────────────────────────────────
_shutdown = False
_stats = {"critical": 0, "important": 0, "normal": 0, "background": 0, "total": 0}


# ── MQTT callbacks ────────────────────────────────────────────

def on_connect(client, userdata, connect_flags, reason_code, properties=None):
    if reason_code.is_failure:
        log.error("Connection refused — reason code %s", reason_code)
        sys.exit(1)
    log.info("Connected to broker %s:%d — session %s", MQTT_HOST, MQTT_PORT, SESSION_ID)


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    if reason_code.is_failure:
        log.warning("Unexpected disconnection (reason=%s) — will retry", reason_code)


# ── MQTT client setup ─────────────────────────────────────────

def build_client() -> mqtt.Client:
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"sleep-publisher-{PATIENT_ID}",
        protocol=mqtt.MQTTv5,
    )
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

    # Last Will: if the publisher dies without a clean session/end,
    # the broker publishes this so the worker can still close the session.
    client.will_set(
        "session/end",
        json.dumps({
            "sessionId": SESSION_ID,
            "event":     "end",
            "patientId": PATIENT_ID,
            "deviceId":  DEVICE_ID,
            "reason":    "publisher disconnected unexpectedly",
        }),
        qos=1,
        retain=False,
    )

    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect

    for attempt in range(1, 11):
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            return client
        except (ConnectionRefusedError, OSError) as exc:
            log.warning("Broker not ready (attempt %d/10): %s — retrying in 5s", attempt, exc)
            time.sleep(5)

    log.error("Could not connect to broker after 10 attempts. Exiting.")
    sys.exit(1)


# ── CSV loading ───────────────────────────────────────────────

def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    log.info("Loaded %d rows from %s (columns: %s)", len(df), path, list(df.columns))
    return df


# ── Publishing ────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%I:%M %p")


def now_ms() -> int:
    return int(time.time() * 1000)


def publish_session_event(client: mqtt.Client, event: str, reason: str | None = None) -> None:
    topic   = f"session/{event}"
    payload = {
        "sessionId": SESSION_ID,
        "event":     event,
        "patientId": PATIENT_ID,
        "deviceId":  DEVICE_ID,
    }
    if event == "start":
        payload["startedAt"] = now_ms()
    else:
        payload["endedAt"] = now_ms()
        # Exact number of readings published this session, so the ingest
        # worker can compute delivery loss without guessing from seq gaps.
        payload["totalReadings"] = _stats["total"]
        if reason:
            payload["reason"] = reason

    result = client.publish(topic, json.dumps(payload), qos=1)
    result.wait_for_publish(timeout=5)
    log.info("Session event published: %s", topic)


def publish_reading(client: mqtt.Client, row: pd.Series, row_idx: int) -> None:
    global _seq

    # sleep_data.csv uses 'bo' for processed SpO2 and 'hr' for heart rate
    spo2       = float(row.get("bo", row.get("spo2", 97)))
    heart_rate = float(row.get("hr", row.get("heart_rate", 60)))
    hrv        = float(row.get("hrv", 35))
    motion     = float(row.get("lm", row.get("motion", 0)))

    tier, reason, qos = classify(spo2, heart_rate, hrv, motion)
    tier_key = tier.lower()

    _stats[tier_key] += 1
    _stats["total"]  += 1

    seq     = _seq
    _seq   += 1
    topic   = f"sleep/{tier_key}"
    payload = json.dumps({
        "sessionId":   SESSION_ID,
        "seq":         seq,
        "publishedAt": now_ms(),
        "tier":        tier,
        "spo2":        round(spo2, 1),
        "heartRate":   round(heart_rate, 1),
        "hrv":         round(hrv, 1),
        "motion":      round(motion, 2),
        "timestamp":   now_iso(),
        "reason":      reason,
        "qos":         qos,
        "topic":       topic,
        "stats":       _stats.copy(),
    })

    result = client.publish(topic, payload, qos=qos)
    result.wait_for_publish(timeout=5)
    log.info("Row %4d seq=%d → %-14s spo2=%.1f hr=%.1f (QoS %d)", row_idx, seq, topic, spo2, heart_rate, qos)


def publish_background_stats(client: mqtt.Client) -> None:
    topic   = "sleep/background"
    payload = json.dumps({
        "sessionId": SESSION_ID,
        "publishedAt": now_ms(),
        "tier":      "Background",
        "spo2":      0,
        "heartRate": 0,
        "hrv":       0,
        "motion":    0,
        "timestamp": now_iso(),
        "reason":    "Periodic session statistics",
        "qos":       0,
        "topic":     topic,
        "stats":     _stats.copy(),
    })
    client.publish(topic, payload, qos=0)
    _stats["background"] += 1
    log.info("Background stats published — total=%d", _stats["total"])


# ── Main loop ─────────────────────────────────────────────────

def run() -> None:
    global _shutdown

    def handle_signal(sig, frame):
        global _shutdown
        log.info("Shutdown signal received")
        _shutdown = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT,  handle_signal)

    df     = load_csv(CSV_PATH)
    client = build_client()
    client.loop_start()

    publish_session_event(client, "start")

    try:
        loop_count = 0
        while not _shutdown:
            for idx, row in df.iterrows():
                if _shutdown:
                    break

                publish_reading(client, row, int(idx))

                if (int(idx) + 1) % STATS_INTERVAL == 0:
                    publish_background_stats(client)

                time.sleep(PUBLISH_INTERVAL)

            loop_count += 1
            if not LOOP_CSV:
                log.info("CSV exhausted after %d row(s). Exiting.", len(df))
                break

            log.info("CSV loop %d complete — restarting from row 0", loop_count)

    finally:
        publish_session_event(client, "end", reason="clean shutdown")
        time.sleep(0.2)
        client.loop_stop()
        client.disconnect()
        log.info("Publisher shut down cleanly. Final stats: %s", _stats)


if __name__ == "__main__":
    run()
