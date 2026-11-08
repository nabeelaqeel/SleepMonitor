"""Unit tests for the ingest worker's MQTT callbacks — DB-free on purpose.

worker.py is written as a script (`python worker.py` from ingest/): its
`from db import ...` assumes the ingest directory is on sys.path, so this
module imports it the benchmark suite's way — insert the path, import
the module by top-level name. Nothing here touches Postgres:

  * on_message is exercised directly (it is what the network thread
    calls): only parse/validate/enqueue should happen, with the module's
    shared queue drained before AND after each test (autouse) so
    redeliveries from one test can never leak into the next.
  * on_connect needs only a fake client and a namespace-like reason
    code — a plain MagicMock's attributes are truthy, so the failure
    case uses a real SimpleNamespace (a MagicMock would exit too).
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

INGEST_DIR = Path(__file__).resolve().parents[1] / "ingest"
if str(INGEST_DIR) not in sys.path:
    sys.path.insert(0, str(INGEST_DIR))

import worker as w


@pytest.fixture(autouse=True)
def _drain_queue():
    """Empty the module-level queue before AND after each test — it is global."""
    while not w.q.empty():
        w.q.get_nowait()
    yield
    while not w.q.empty():
        w.q.get_nowait()


def message(topic: str, payload) -> SimpleNamespace:
    """A paho-shaped msg: only .topic and .payload(bytes) are ever touched."""
    return SimpleNamespace(topic=topic, payload=json.dumps(payload).encode())


READING_PAYLOAD = {
    "sessionId": "sess-unit",
    "seq": 7,
    "publishedAt": 1000000000000,
    "spo2": 97.0,
    "heartRate": 62.0,
    "hrv": 42.0,
    "motion": 1.5,
    "tier": "Normal",
    "qos": 0,
}


# ── to_dt ────────────────────────────────────────────────────────

def test_to_dt_converts_epoch_ms():
    """A fixed epoch (2001-09-09 01:46:40 UTC) survives the ms → s division."""
    assert w.to_dt(1_000_000_000_000) == datetime(2001, 9, 9, 1, 46, 40, tzinfo=UTC)


def test_to_dt_none_falls_back_to_now():
    """No timestamp in the payload means 'around now' — still UTC-aware."""
    before = datetime.now(UTC)
    got = w.to_dt(None)
    assert got.tzinfo is UTC
    assert abs((got - before).total_seconds()) < 60


# ── on_message: session lifecycle ────────────────────────────────

def test_session_start_enqueues_start_item():
    """session/start with an id becomes a start item with a real datetime."""
    w.on_message(MagicMock(), None, message(
        "session/events",
        {"sessionId": "sess-42", "event": "start", "startedAt": 1_000_000_000_000},
    ))
    item = w.q.get_nowait()
    assert item == {
        "kind": "session_start",
        "session_id": "sess-42",
        "started_at": datetime(2001, 9, 9, 1, 46, 40, tzinfo=UTC),
        "device_id": w.DEVICE_ID,  # omitted deviceId falls back to config
    }


def test_session_end_enqueues_end_item():
    """session/end carries the ended timestamp and the expected-count contract."""
    w.on_message(MagicMock(), None, message(
        "session/events",
        {"sessionId": "sess-42", "event": "end",
         "endedAt": 1_000_000_000_000, "totalReadings": 500},
    ))
    item = w.q.get_nowait()
    assert item == {
        "kind": "session_end",
        "session_id": "sess-42",
        "ended_at": datetime(2001, 9, 9, 1, 46, 40, tzinfo=UTC),
        "expected": 500,
    }


def test_session_event_without_id_is_ignored():
    """No sessionId → nothing enqueued, whatever the event says."""
    w.on_message(MagicMock(), None, message(
        "session/events", {"event": "start", "startedAt": 1_000_000_000_000},
    ))
    assert w.q.empty()


def test_unknown_session_event_is_ignored():
    """Events other than start/end enqueue nothing (defensive against typos)."""
    w.on_message(MagicMock(), None, message(
        "session/events", {"sessionId": "sess-42", "event": "restart"},
    ))
    assert w.q.empty()


# ── on_message: readings ─────────────────────────────────────────

def test_reading_defaults_to_normal_tier_without_alert():
    """A payload omitting tier/qos is a Normal QoS-0 reading, no alert row."""
    payload = dict(READING_PAYLOAD)
    del payload["tier"], payload["qos"]
    w.on_message(MagicMock(), None, message("sleep/sleepband-001/vitals", payload))

    item = w.q.get_nowait()
    assert "alert_row" not in item
    assert item["row"] == (
        "sess-unit", w.PATIENT_UUID, 7, 1000000000000,
        97.0, 62.0, 42.0, 1.5,
        "Normal", 0,
    )


def test_critical_reading_also_enqueues_alert_row():
    """Critical/Important tiers produce BOTH the reading and an alert row whose
    reason/topic/joined-payload let the dashboard explain the alert later."""
    payload = dict(READING_PAYLOAD) | {"tier": "Critical", "qos": 2,
                                       "reason": "SpO2 critically low"}
    w.on_message(MagicMock(), None, message("sleep/sleepband-001/vitals", payload))

    item = w.q.get_nowait()
    assert item["row"][-2:] == ("Critical", 2)
    assert item["alert_row"] == (
        "sess-unit", w.PATIENT_UUID, 7, "Critical",
        97.0, 62.0, 42.0,
        "SpO2 critically low", "sleep/sleepband-001/vitals", json.dumps(payload),
    )


def test_background_statistics_without_seq_are_skipped():
    """sleep/background without seq is a periodic statistic — not persisted.

    session_stats are computed from readings; draining the stats spam at
    the queue is what keeps the DB free of them.
    """
    w.on_message(MagicMock(), None, message(
        "sleep/background", {"sessionId": "sess-unit", "avgSpo2": 97.1},
    ))
    assert w.q.empty()


def test_background_reading_with_seq_is_persisted():
    """A Background-tier reading published WITH seq is a real row."""
    payload = dict(READING_PAYLOAD) | {"tier": "Background", "qos": 0}
    w.on_message(MagicMock(), None, message("sleep/background", payload))
    item = w.q.get_nowait()
    assert item["kind"] == "reading"
    assert "alert_row" not in item  # Background never alerts


def test_reading_without_session_id_or_seq_is_dropped():
    """Vitals missing their identity keys never reach the DB writer."""
    no_sid = {k: v for k, v in READING_PAYLOAD.items() if k != "sessionId"}
    no_seq = {k: v for k, v in READING_PAYLOAD.items() if k != "seq"}
    w.on_message(MagicMock(), None, message("sleep/x/vitals", no_sid))
    w.on_message(MagicMock(), None, message("sleep/x/vitals", no_seq))
    assert w.q.empty()


def test_non_json_payload_is_dropped():
    """Garbage bytes on a subscribed topic are a warning, not a crash."""
    bad = SimpleNamespace(topic="sleep/x/vitals", payload=b"{not json")
    w.on_message(MagicMock(), None, bad)
    assert w.q.empty()


# ── on_connect ───────────────────────────────────────────────────

def test_on_connect_subscribes_with_the_qos_split():
    """Success path: sleep/# rides QoS 2, session/# rides QoS 1."""
    client = MagicMock()
    reason = SimpleNamespace(is_failure=False)
    w.on_connect(client, None, None, reason)
    assert [c.args[0] for c in client.subscribe.call_args_list] == [
        "sleep/#", "session/#",
    ]
    assert [c.kwargs["qos"] for c in client.subscribe.call_args_list] == [2, 1]


def test_on_connect_refusal_exits_the_process():
    """A refused connection is fatal (systemd restarts it) — sys.exit(1)."""
    reason = SimpleNamespace(is_failure=True)
    with pytest.raises(SystemExit) as exc:
        w.on_connect(MagicMock(), None, None, reason)
    assert exc.value.code == 1
