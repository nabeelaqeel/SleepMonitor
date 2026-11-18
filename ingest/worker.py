"""Sleep Monitor — PostgreSQL ingest worker.

Bridges MQTT and Postgres: subscribes to the broker and persists
readings/alerts into the database.

Design notes
------------
* The **publisher owns the session lifecycle** — it emits session/start
  and session/end (with an MQTT Last Will as a crash fallback). This
  worker never invents or ends a session on its own; on shutdown it
  simply flushes what it has and leaves the session open for the broker
  to redeliver.
* MQTT runs on Paho's network thread and only *enqueues* messages;
  the main thread is the single writer to Postgres (no DB locking).
* MQTTv5 persistent session (clean_start=False + SessionExpiryInterval)
  means the broker queues QoS 1/2 messages while the worker is down.
* Reads/inserts are idempotent on (session_id, seq), so redelivery and
  restarts are safe.
* Attribution: the payload's deviceId is resolved to a bound patient via
  the devices registry ONCE per session (never per reading). Unbound or
  missing deviceId falls back to PATIENT_UUID so the single-watch demo
  keeps working unchanged.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import signal
import sys
import threading
import time
from datetime import UTC, datetime

import paho.mqtt.client as mqtt
from db import (
    connect,
    ensure_registry,
    ensure_user,
    finalize_session,
    insert_alerts,
    insert_readings,
    resolve_patient,
    upsert_session,
)
from dotenv import load_dotenv
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

load_dotenv(".env.development")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("ingest.worker")

# ── Config ────────────────────────────────────────────────────
MQTT_HOST      = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT      = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER      = os.getenv("MQTT_USER", "")
MQTT_PASSWORD  = os.getenv("MQTT_PASSWORD", "")
CLIENT_ID      = os.getenv("INGEST_CLIENT_ID", "sleep-ingest-001")
SESSION_EXPIRY = int(os.getenv("SESSION_EXPIRY", "3600"))
FLUSH_INTERVAL = float(os.getenv("FLUSH_INTERVAL", "1.0"))
FLUSH_MAX      = int(os.getenv("FLUSH_MAX", "50"))

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://sleep_user:changeme@localhost:5432/sleep_monitor",
)
PATIENT_UUID = os.getenv("PATIENT_UUID", "00000000-0000-0000-0000-000000000002")
DEVICE_ID    = os.getenv("DEVICE_ID", "sleepband-001")

# ── State ─────────────────────────────────────────────────────
q = queue.Queue()
_stop = threading.Event()
_seq = 0  # running counter for logging only


def to_dt(ms) -> datetime:
    """Epoch milliseconds to an aware UTC datetime; None (payload with no timestamp) falls back to 'now'."""
    if ms is None:
        return datetime.now(UTC)
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC)


# ── MQTT callbacks (network thread — enqueue only) ────────────

def on_connect(client, userdata, connect_flags, reason_code, properties=None):
    """MQTT connect callback (CallbackAPI v2): refuse-on-failure exits the process; on success subscribe to sleep/# (QoS 2 readings/signals) and session/# (QoS 1)."""
    if reason_code.is_failure:
        log.error("Connection refused — %s", reason_code)
        sys.exit(1)
    log.info("Connected to broker %s:%d", MQTT_HOST, MQTT_PORT)
    client.subscribe("sleep/#", qos=2)
    client.subscribe("session/#", qos=1)
    log.info("Subscribed: sleep/# (QoS 2), session/# (QoS 1)")


def on_message(client, userdata, msg):
    """Network-thread callback: parse/validate the payload and enqueue work only. Session topics yield start/end items; sleep/# readings are persisted rows (+ alert rows for Critical/Important tiers); seq-less sleep/background statistics are skipped."""
    topic = msg.topic
    try:
        data = json.loads(msg.payload.decode())
    except (ValueError, UnicodeDecodeError):
        log.warning("Non-JSON payload on %s — dropped", topic)
        return

    # ── Session lifecycle ─────────────────────────────────────
    if topic.startswith("session/"):
        sid = data.get("sessionId")
        if not sid:
            return
        if data.get("event") == "start":
            q.put({
                "kind":       "session_start",
                "session_id": sid,
                "started_at": to_dt(data.get("startedAt")),
                "device_id":  data.get("deviceId", DEVICE_ID),
            })
        elif data.get("event") == "end":
            end_item = {
                "kind":     "session_end",
                "session_id": sid,
                "ended_at": to_dt(data.get("endedAt")),
                "expected": data.get("totalReadings"),
            }
            # Only present when the payload carries it — the Last-Will
            # recovery path otherwise resolves via the DEVICE_ID config.
            if data.get("deviceId"):
                end_item["device_id"] = data["deviceId"]
            q.put(end_item)
        return

    # ── sleep/background now carries two message types: Background-tier
    #    readings (out-of-band values, published WITH seq) and periodic
    #    statistics (no seq). Persist the readings; skip the statistics —
    #    session_stats are computed from readings. ───────────────────
    sid = data.get("sessionId")
    seq = data.get("seq")
    if topic == "sleep/background" and seq is None:
        return

    if sid is None or seq is None:
        log.warning("Reading without sessionId/seq on %s — dropped", topic)
        return

    tier = data.get("tier", "Normal")
    reading = (
        sid, PATIENT_UUID, int(seq), data.get("publishedAt"),
        data.get("spo2"), data.get("heartRate"), data.get("hrv"), data.get("motion"),
        tier, data.get("qos", 0),
    )

    item = {
        "kind":       "reading",
        "row":        reading,
        "session_id": sid,
        # Attribution is decided by the writer via the registry — the
        # parse-time PATIENT_UUID placeholder is swapped when bound.
        "device_id":  data.get("deviceId", DEVICE_ID),
    }
    if tier in ("Critical", "Important"):
        item["alert_row"] = (
            sid, PATIENT_UUID, int(seq), tier,
            data.get("spo2"), data.get("heartRate"), data.get("hrv"),
            data.get("reason", ""), topic, json.dumps(data),
        )
    q.put(item)


# ── MQTT client setup ─────────────────────────────────────────

def build_client() -> mqtt.Client:
    """Assemble the v5 client under a persistent client id and clean_start=False with the 12 h session expiry, retrying broker connect for a bounded startup window."""
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=CLIENT_ID,
        protocol=mqtt.MQTTv5,
    )
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

    client.on_connect = on_connect
    client.on_message = on_message

    props = Properties(PacketTypes.CONNECT)
    props.SessionExpiryInterval = SESSION_EXPIRY

    for attempt in range(1, 11):
        try:
            client.connect(
                MQTT_HOST, MQTT_PORT, keepalive=60,
                clean_start=False, properties=props,
            )
            return client
        except (ConnectionRefusedError, OSError) as exc:
            log.warning("Broker not ready (attempt %d/10): %s — retrying in 5s", attempt, exc)
            time.sleep(5)

    log.error("Could not connect to broker after 10 attempts. Exiting.")
    sys.exit(1)


# ── DB writer (main thread) ───────────────────────────────────

def flush(conn, readings, alerts):
    """Commit any stale reading/alert batches and log inserted vs offered counts."""
    if readings:
        n = insert_readings(conn, readings)
        log.info("Flushed %d/%d readings", n, len(readings))
    if alerts:
        n = insert_alerts(conn, alerts)
        log.info("Flushed %d/%d alerts", n, len(alerts))


def resolve_session_patient(conn, session_id: str, device_id: str,
                            cache: dict, warned: set) -> str:
    """Resolve a session's patient via the device registry, once per session.

    Unbound or missing deviceId falls back to PATIENT_UUID so the
    single-watch demo keeps working; the warning fires once per device,
    not per message.
    """
    if session_id in cache:
        return cache[session_id]
    patient = resolve_patient(conn, device_id, PATIENT_UUID)
    if patient == PATIENT_UUID and device_id not in warned:
        warned.add(device_id)
        log.warning(
            "Device %s is not bound in the registry — attributing session %s "
            "to the demo patient %s", device_id, session_id, PATIENT_UUID,
        )
    cache[session_id] = patient
    return patient


def _attribute(row: tuple, patient: str) -> tuple:
    """Swap the session's resolved patient into a row (patient rides index 1)."""
    if row[1] == patient:
        return row
    return (row[0], patient, *row[2:])


def writer_loop(conn):
    """Main-thread drain: batch queued rows into the DB, restoring FK targets on first sight per session, flush at size or time thresholds, and finalize on session/end. Keeps draining after stop until the queue empties."""
    global _seq
    readings: list[tuple] = []
    alerts: list[tuple] = []
    seen_sessions: set[str] = set()
    session_patients: dict[str, str] = {}
    warned_unbound: set[str] = set()
    last_flush = time.time()

    while not _stop.is_set() or not q.empty():
        try:
            item = q.get(timeout=0.2)
        except queue.Empty:
            item = None

        if item is not None:
            kind = item["kind"]

            if kind == "reading":
                sid = item["session_id"]
                patient = resolve_session_patient(
                    conn, sid, item["device_id"], session_patients, warned_unbound,
                )
                # Guarantee the FK target exists even if we joined mid-session.
                if sid not in seen_sessions:
                    upsert_session(
                        conn, sid, patient,
                        item["device_id"], to_dt(item["row"][3]),
                    )
                    seen_sessions.add(sid)
                readings.append(_attribute(item["row"], patient))
                if "alert_row" in item:
                    alerts.append(_attribute(item["alert_row"], patient))
                _seq += 1

            elif kind == "session_start":
                flush(conn, readings, alerts); readings.clear(); alerts.clear()
                patient = resolve_session_patient(
                    conn, item["session_id"], item["device_id"],
                    session_patients, warned_unbound,
                )
                upsert_session(
                    conn, item["session_id"], patient,
                    item["device_id"], item["started_at"],
                )
                seen_sessions.add(item["session_id"])
                log.info("Session %s started (patient %s)", item["session_id"], patient)

            elif kind == "session_end":
                flush(conn, readings, alerts); readings.clear(); alerts.clear()
                sid = item["session_id"]
                if sid not in seen_sessions:
                    # Last-Will recovery: recreate the session row so the
                    # stats FK has a target; started_at is unknowable, so
                    # ended_at stands in. Attribution resolves from the
                    # Will's deviceId (or the DEVICE_ID config).
                    device_id = item.get("device_id", DEVICE_ID)
                    patient = resolve_session_patient(
                        conn, sid, device_id, session_patients, warned_unbound,
                    )
                    upsert_session(conn, sid, patient, device_id, item["ended_at"])
                    seen_sessions.add(sid)
                stats = finalize_session(
                    conn, item["session_id"], item["ended_at"],
                    declared_total=item.get("expected"),
                )
                log.info(
                    "Session %s ended — received=%d expected=%d missing=%d "
                    "(critical=%d important=%d)",
                    item["session_id"], stats["received"], stats["expected"],
                    stats["missing"], stats["critical"], stats["important"],
                )

        if (readings or alerts) and (
            len(readings) + len(alerts) >= FLUSH_MAX
            or time.time() - last_flush >= FLUSH_INTERVAL
        ):
                flush(conn, readings, alerts)
                readings.clear(); alerts.clear()
                last_flush = time.time()

    flush(conn, readings, alerts)


def main() -> None:
    """Bootstrap the connection, MQTT client and signal handlers, then run the writer loop until drained and cleaned up."""
    conn = connect(DATABASE_URL)
    ensure_registry(conn)
    ensure_user(conn, PATIENT_UUID)

    client = build_client()
    client.loop_start()

    def handle_signal(sig, frame):
        """SIGTERM/SIGINT handler: request a clean stop; the running session is deliberately left open for the next worker."""
        log.info("Signal %s received — shutting down (session stays open)", sig)
        _stop.set()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    log.info("Ingest worker started — client_id=%s db=%s", CLIENT_ID, DATABASE_URL.split("@")[-1])

    try:
        writer_loop(conn)
    finally:
        client.loop_stop()
        client.disconnect()
        conn.close()
        log.info("Ingest worker stopped — total readings seen=%d", _seq)


if __name__ == "__main__":
    main()
