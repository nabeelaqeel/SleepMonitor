"""Device-registry tests: bind API + ingest attribution.

Two halves against the real (local) Postgres, skipping cleanly when it is
unreachable (same contract as tests/conftest.py's pg fixture — replicated
here because this file owns its fixtures):

  * /devices/bind and GET /devices through the HTTP endpoints (patient
    JWT required, 409 guards device hijacking, 403 wrong role).
  * ingest attribution: worker.resolve_session_patient / _attribute and
    the writer_loop Last-Will recovery, using ingest/db.py directly.

Every created user is deleted at teardown; devices and sessions cascade.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import psycopg2
import pytest
from fastapi.testclient import TestClient

import api.db
from api.main import app
from api.security import hash_password

INGEST_DIR = Path(__file__).resolve().parents[1] / "ingest"
if str(INGEST_DIR) not in sys.path:
    sys.path.insert(0, str(INGEST_DIR))

import db as ingest_db
import worker as w

client = TestClient(app)

CONNECT_TIMEOUT = 2


class SimpleNamespaceMsg:
    """A paho-shaped msg: only .topic and .payload(bytes) are ever touched."""

    def __init__(self, topic: str, payload: bytes):
        self.topic = topic
        self.payload = payload


def _dsn_candidates() -> list[str]:
    """Configured DSN first, then the same DSN re-hosted onto 127.0.0.1."""
    from api.config import DATABASE_URL

    candidates = [DATABASE_URL]
    try:
        parsed = psycopg2.extensions.parse_dsn(DATABASE_URL)
        if parsed.get("host") not in ("localhost", "127.0.0.1", None):
            candidates.append(psycopg2.extensions.make_dsn(DATABASE_URL, host="127.0.0.1"))
    except psycopg2.ProgrammingError:
        pass
    return candidates


def _reachable(dsn: str) -> bool:
    try:
        conn = psycopg2.connect(dsn, connect_timeout=CONNECT_TIMEOUT)
    except psycopg2.OperationalError:
        return False
    conn.close()
    return True


class RegistryPg:
    """Reachable-Postgres handle with test-user/device/session bookkeeping."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._emails: list[str] = []
        self._devices: list[str] = []
        self._sessions: list[str] = []

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        with (
            psycopg2.connect(self.dsn, connect_timeout=CONNECT_TIMEOUT) as conn,
            conn.cursor() as cur,
        ):
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else []

    def execute(self, sql: str, params: tuple = ()) -> None:
        with (
            psycopg2.connect(self.dsn, connect_timeout=CONNECT_TIMEOUT) as conn,
            conn.cursor() as cur,
        ):
            cur.execute(sql, params)

    def unique_email(self, prefix: str) -> str:
        email = f"{prefix}-{uuid.uuid4().hex[:8]}@sleep.test"
        self._emails.append(email)
        return email

    def unique_device(self, prefix: str) -> str:
        device_id = f"{prefix}-{uuid.uuid4().hex[:8]}"
        self._devices.append(device_id)
        return device_id

    def unique_session(self, prefix: str) -> str:
        # sessions.session_id is a UUID column — tests must supply real ones.
        session_id = str(uuid.uuid4())
        self._sessions.append(session_id)
        return session_id

    def cleanup(self) -> None:
        for session_id in self._sessions:
            self.execute("DELETE FROM sessions WHERE session_id = %s::uuid", (session_id,))
        for device_id in self._devices:
            self.execute("DELETE FROM devices WHERE device_id = %s", (device_id,))
        for email in self._emails:
            self.execute("DELETE FROM users WHERE lower(email) = lower(%s)", (email,))


@pytest.fixture(scope="session")
def reg_pg():
    """Reachable-Postgres handle + the idempotent ensure_setup migration."""
    dsn = next((d for d in _dsn_candidates() if _reachable(d)), None)
    if dsn is None:
        pytest.skip("local Postgres unreachable — device-registry tests skipped")

    from api.db import ensure_setup

    handle = RegistryPg(dsn)
    mp = pytest.MonkeyPatch()
    mp.setattr(api.db, "DATABASE_URL", dsn)
    try:
        ensure_setup(hash_password)
        yield handle
    finally:
        mp.undo()
        handle.cleanup()


@pytest.fixture(autouse=True)
def _drain_queue():
    """Empty the ingest queue before AND after each test — it is global."""
    while not w.q.empty():
        w.q.get_nowait()
    yield
    while not w.q.empty():
        w.q.get_nowait()


def register_and_login(pg: RegistryPg, role: str):
    """Fresh account → 200; returns (headers, user_id, email)."""
    email = pg.unique_email(f"dev-{role}")
    r = client.post(
        "/auth/register",
        json={"email": email, "password": "correct-horse-42", "role": role},
    )
    assert r.status_code == 200
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}, body["user"]["id"], email


# ── bind API ──────────────────────────────────────────────────────────────

def test_bind_success_creates_registry_row(reg_pg):
    headers, patient_id, _ = register_and_login(reg_pg, "patient")
    device_id = reg_pg.unique_device("watch")

    r = client.post(
        "/devices/bind",
        json={"device_id": device_id, "display_name": "Ali's watch"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["device"]["device_id"] == device_id
    assert body["device"]["patient_id"] == patient_id
    assert body["device"]["display_name"] == "Ali's watch"
    assert body["device"]["created_at"]

    rows = reg_pg.query(
        "SELECT patient_id::text, display_name FROM devices WHERE device_id = %s",
        (device_id,),
    )
    assert rows == [(patient_id, "Ali's watch")]


def test_rebind_same_patient_updates_display_name(reg_pg):
    headers, _, _ = register_and_login(reg_pg, "patient")
    device_id = reg_pg.unique_device("watch")
    assert client.post(
        "/devices/bind", json={"device_id": device_id, "display_name": "First"},
        headers=headers,
    ).status_code == 200

    r = client.post(
        "/devices/bind", json={"device_id": device_id, "display_name": "Renamed"},
        headers=headers,
    )
    assert r.status_code == 200
    rows = reg_pg.query(
        "SELECT display_name FROM devices WHERE device_id = %s", (device_id,)
    )
    assert rows == [("Renamed",)]


def test_rebind_without_name_keeps_existing_name(reg_pg):
    headers, _, _ = register_and_login(reg_pg, "patient")
    device_id = reg_pg.unique_device("watch")
    assert client.post(
        "/devices/bind", json={"device_id": device_id, "display_name": "Kept"},
        headers=headers,
    ).status_code == 200

    r = client.post("/devices/bind", json={"device_id": device_id}, headers=headers)
    assert r.status_code == 200
    assert r.json()["device"]["display_name"] == "Kept"


def test_rebind_other_patient_is_409(reg_pg):
    """No hijacking: a second patient cannot claim a bound device."""
    headers_a, patient_a, _ = register_and_login(reg_pg, "patient")
    device_id = reg_pg.unique_device("watch")
    assert client.post(
        "/devices/bind", json={"device_id": device_id}, headers=headers_a,
    ).status_code == 200

    headers_b, _, _ = register_and_login(reg_pg, "patient")
    r = client.post("/devices/bind", json={"device_id": device_id}, headers=headers_b)
    assert r.status_code == 409
    assert "another patient" in r.json()["detail"]

    rows = reg_pg.query(
        "SELECT patient_id::text FROM devices WHERE device_id = %s", (device_id,)
    )
    assert rows == [(patient_a,)]


def test_get_devices_lists_only_callers_devices(reg_pg):
    headers_a, _, _ = register_and_login(reg_pg, "patient")
    headers_b, _, _ = register_and_login(reg_pg, "patient")
    w1, w2, w3 = (reg_pg.unique_device("watch") for _ in range(3))
    for headers, device in ((headers_a, w1), (headers_a, w2), (headers_b, w3)):
        assert client.post(
            "/devices/bind", json={"device_id": device}, headers=headers,
        ).status_code == 200

    got_a = client.get("/devices", headers=headers_a)
    assert got_a.status_code == 200
    assert {d["device_id"] for d in got_a.json()["devices"]} == {w1, w2}

    got_b = client.get("/devices", headers=headers_b)
    assert {d["device_id"] for d in got_b.json()["devices"]} == {w3}


def test_doctor_role_is_403(reg_pg):
    headers, _, _ = register_and_login(reg_pg, "doctor")
    device_id = reg_pg.unique_device("watch")
    assert client.post(
        "/devices/bind", json={"device_id": device_id}, headers=headers,
    ).status_code == 403
    assert client.get("/devices", headers=headers).status_code == 403


def test_unauthenticated_is_401(reg_pg):
    device_id = reg_pg.unique_device("watch")
    for headers in ({}, {"Authorization": "Bearer junk"}):
        assert client.post(
            "/devices/bind", json={"device_id": device_id}, headers=headers,
        ).status_code == 401
        assert client.get("/devices", headers=headers).status_code == 401


def test_bind_validates_422(reg_pg):
    headers, _, _ = register_and_login(reg_pg, "patient")
    assert client.post("/devices/bind", json={}, headers=headers).status_code == 422
    assert client.post(
        "/devices/bind", json={"device_id": ""}, headers=headers,
    ).status_code == 422
    assert client.post(
        "/devices/bind", json={"device_id": "w", "display_name": "x" * 101},
        headers=headers,
    ).status_code == 422


# ── ingest attribution ────────────────────────────────────────────────────

def test_bound_device_resolves_to_bound_patient(reg_pg):
    _, patient_id, _ = register_and_login(reg_pg, "patient")
    device_id = reg_pg.unique_device("watch")
    reg_pg.execute(
        "INSERT INTO devices (device_id, patient_id) VALUES (%s, %s::uuid)",
        (device_id, patient_id),
    )

    with ingest_db.connect(reg_pg.dsn) as conn:
        got = w.resolve_session_patient(conn, "sess-bound", device_id, {}, set())
    assert got == patient_id


def test_unbound_device_falls_back_with_single_warning(reg_pg, caplog):
    device_id = reg_pg.unique_device("ghost")

    with ingest_db.connect(reg_pg.dsn) as conn:
        cache: dict = {}
        warned: set = set()
        with caplog.at_level(logging.WARNING, logger="ingest.worker"):
            first = w.resolve_session_patient(conn, "sess-a", device_id, cache, warned)
            second = w.resolve_session_patient(conn, "sess-b", device_id, cache, warned)

    assert first == second == w.PATIENT_UUID
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1  # once per device, not per message/session
    assert device_id in warnings[0].getMessage()


def test_missing_device_id_uses_config_fallback(reg_pg):
    """No deviceId in the payload → the DEVICE_ID config → unbound → demo patient."""
    payload = {
        "sessionId": "sess-unit", "seq": 7, "publishedAt": 1_000_000_000_000,
        "spo2": 97.0, "heartRate": 62.0, "hrv": 42.0, "motion": 1.5,
        "tier": "Normal", "qos": 0,
    }
    w.on_message(None, None, SimpleNamespaceMsg(
        topic="sleep/sleepband-001/vitals",
        payload=json.dumps(payload).encode(),
    ))
    item = w.q.get_nowait()
    assert item["device_id"] == w.DEVICE_ID

    with ingest_db.connect(reg_pg.dsn) as conn:
        got = w.resolve_session_patient(conn, "sess-m", w.DEVICE_ID, {}, set())
    assert got == w.PATIENT_UUID


def test_attribute_swaps_patient_only_when_needed():
    demo_row = ("sess-x", w.PATIENT_UUID, 7, 1, "Normal", 0)
    other = str(uuid.uuid4())
    assert w._attribute(demo_row, other)[1] == other
    assert w._attribute(demo_row, other)[0] == "sess-x"
    assert w._attribute(demo_row, other)[2:] == demo_row[2:]
    assert w._attribute(demo_row, w.PATIENT_UUID) is demo_row


def test_writer_attributes_bound_device_reading(reg_pg):
    """End-to-end: bound device's reading lands under the BOUND patient."""
    _, patient_id, _ = register_and_login(reg_pg, "patient")
    device_id = reg_pg.unique_device("watch")
    reg_pg.execute(
        "INSERT INTO devices (device_id, patient_id) VALUES (%s, %s::uuid)",
        (device_id, patient_id),
    )
    session_id = reg_pg.unique_session("sess")
    payload = {
        "sessionId": session_id, "deviceId": device_id, "seq": 7,
        "publishedAt": 1_000_000_000_000,
        "spo2": 97.0, "heartRate": 62.0, "hrv": 42.0, "motion": 1.5,
        "tier": "Critical", "qos": 2, "reason": "low spo2",
    }
    w.on_message(None, None, SimpleNamespaceMsg(
        topic="sleep/x/vitals", payload=json.dumps(payload).encode(),
    ))

    w._stop.set()
    try:
        with ingest_db.connect(reg_pg.dsn) as conn:
            w.writer_loop(conn)
        session_patient, session_device = reg_pg.query(
            "SELECT patient_id::text, device_id FROM sessions WHERE session_id = %s::uuid",
            (session_id,),
        )[0]
        reading_patient = reg_pg.query(
            "SELECT patient_id::text FROM readings WHERE session_id = %s::uuid AND seq = 7",
            (session_id,),
        )[0][0]
        alert_patient = reg_pg.query(
            "SELECT patient_id::text FROM alerts WHERE session_id = %s::uuid AND seq = 7",
            (session_id,),
        )[0][0]
        assert (session_patient, reading_patient, alert_patient) == (patient_id,) * 3
        assert session_device == device_id
        assert session_patient != w.PATIENT_UUID  # registry beat the env fallback
    finally:
        w._stop.clear()


def test_writer_unbound_device_falls_back(reg_pg):
    """Unknown deviceId keeps the demo patient (existing single-watch behavior)."""
    device_id = reg_pg.unique_device("ghost")
    session_id = reg_pg.unique_session("sess")
    payload = {
        "sessionId": session_id, "deviceId": device_id, "seq": 3,
        "publishedAt": 1_000_000_000_000,
        "spo2": 96.0, "heartRate": 60.0, "hrv": 40.0, "motion": 0.5,
        "tier": "Normal", "qos": 1,
    }
    w.on_message(None, None, SimpleNamespaceMsg(
        topic="sleep/x/vitals", payload=json.dumps(payload).encode(),
    ))

    w._stop.set()
    try:
        with ingest_db.connect(reg_pg.dsn) as conn:
            w.writer_loop(conn)
        rows = reg_pg.query(
            "SELECT patient_id::text FROM readings WHERE session_id = %s::uuid",
            (session_id,),
        )
        assert rows == [(w.PATIENT_UUID,)]
    finally:
        w._stop.clear()


def test_writer_last_will_end_recovers_session(reg_pg):
    """session/end alone (crashed publisher) still creates the session row
    for the bound patient, so session_stats has an FK target."""
    _, patient_id, _ = register_and_login(reg_pg, "patient")
    device_id = reg_pg.unique_device("watch")
    reg_pg.execute(
        "INSERT INTO devices (device_id, patient_id) VALUES (%s, %s::uuid)",
        (device_id, patient_id),
    )
    session_id = reg_pg.unique_session("sess")
    w.q.put({
        "kind": "session_end",
        "session_id": session_id,
        "ended_at": datetime.now(UTC),
        "expected": 0,
        "device_id": device_id,
    })

    w._stop.set()
    try:
        with ingest_db.connect(reg_pg.dsn) as conn:
            w.writer_loop(conn)
        session_patient = reg_pg.query(
            "SELECT patient_id::text FROM sessions WHERE session_id = %s::uuid",
            (session_id,),
        )[0][0]
        stats = reg_pg.query(
            "SELECT expected_readings FROM session_stats WHERE session_id = %s::uuid",
            (session_id,),
        )
        assert session_patient == patient_id
        assert stats == [(0,)]
    finally:
        w._stop.clear()
