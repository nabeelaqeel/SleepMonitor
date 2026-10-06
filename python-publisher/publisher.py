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
from datetime import datetime, timezone

import pandas as pd
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from classifier import classify

load_dotenv()

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
STATS_INTERVAL   = int(os.getenv("STATS_INTERVAL", "10"))  # publish background stats every N rows

# ── State ─────────────────────────────────────────────────────
_shutdown = False
_stats = {"critical": 0, "important": 0, "normal": 0, "background": 0, "total": 0}


# ── MQTT callbacks ────────────────────────────────────────────

def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        log.info("Connected to broker %s:%d", MQTT_HOST, MQTT_PORT)
    else:
        log.error("Connection refused — reason code %s", reason_code)
        sys.exit(1)


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    if reason_code != 0:
        log.warning("Unexpected disconnection (reason=%s) — will retry", reason_code)


# ── MQTT client setup ─────────────────────────────────────────

def build_client() -> mqtt.Client:
    client = mqtt.Client(
        client_id=f"sleep-publisher-{PATIENT_ID}",
        protocol=mqtt.MQTTv5,
    )
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
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


def publish_reading(client: mqtt.Client, row: pd.Series, row_idx: int) -> None:
    # sleep_data.csv uses 'bo' for processed SpO2 and 'hr' for heart rate
    spo2       = float(row.get("bo", row.get("spo2", 97)))
    heart_rate = float(row.get("hr", row.get("heart_rate", 60)))
    hrv        = float(row.get("hrv", 35))
    motion     = float(row.get("lm", row.get("motion", 0)))

    tier, reason, qos = classify(spo2, heart_rate, hrv, motion)
    tier_key = tier.lower()

    _stats[tier_key] += 1
    _stats["total"]  += 1

    topic   = f"sleep/{tier_key}"
    payload = json.dumps({
        "tier":      tier,
        "spo2":      round(spo2, 1),
        "heartRate": round(heart_rate, 1),
        "hrv":       round(hrv, 1),
        "motion":    round(motion, 2),
        "timestamp": now_iso(),
        "reason":    reason,
        "qos":       qos,
        "topic":     topic,
        "stats":     _stats.copy(),
    })

    result = client.publish(topic, payload, qos=qos)
    result.wait_for_publish(timeout=5)
    log.info("Row %4d → %-14s spo2=%.1f hr=%.1f (QoS %d)", row_idx, topic, spo2, heart_rate, qos)


def publish_background_stats(client: mqtt.Client) -> None:
    topic   = "sleep/background"
    payload = json.dumps({
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
        client.loop_stop()
        client.disconnect()
        log.info("Publisher shut down cleanly. Final stats: %s", _stats)


if __name__ == "__main__":
    run()
