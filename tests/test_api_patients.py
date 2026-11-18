"""Roster tests for GET /patients (the doctor's linked-patient snapshot).

Same Postgres-or-skip contract as the other DB-backed auth tests: this
file owns its fixtures (no conftest edits) and deletes every created
user at teardown; devices/sessions/readings/stats cascade with them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import psycopg2
import pytest
from fastapi.testclient import TestClient

import api.db
from api.main import app
from api.security import hash_password

client = TestClient(app)

CONNECT_TIMEOUT = 2


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


class RosterPg:
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

    def unique_session(self) -> str:
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
def roster_pg():
    """Reachable-Postgres handle + the idempotent ensure_setup migration."""
    dsn = next((d for d in _dsn_candidates() if _reachable(d)), None)
    if dsn is None:
        pytest.skip("local Postgres unreachable — roster tests skipped")

    from api.db import ensure_setup

    handle = RosterPg(dsn)
    mp = pytest.MonkeyPatch()
    mp.setattr(api.db, "DATABASE_URL", dsn)
    try:
        ensure_setup(hash_password)
        yield handle
    finally:
        mp.undo()
        handle.cleanup()


def register_and_login(pg: RosterPg, role: str):
    """Fresh account → 200; returns (headers, user_id, email)."""
    email = pg.unique_email(f"roster-{role}")
    r = client.post(
        "/auth/register",
        json={"email": email, "password": "correct-horse-42", "role": role},
    )
    assert r.status_code == 200
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}, body["user"]["id"], email


def link(pg: RosterPg, doctor_id: str, patient_id: str) -> None:
    pg.execute(
        """
        INSERT INTO doctor_patients (doctor_id, patient_id)
        VALUES (%s::uuid, %s::uuid)
        ON CONFLICT DO NOTHING
        """,
        (doctor_id, patient_id),
    )


def bind_device(pg: RosterPg, patient_id: str, display_name: str) -> str:
    device_id = pg.unique_device("watch")
    pg.execute(
        """
        INSERT INTO devices (device_id, patient_id, display_name)
        VALUES (%s, %s::uuid, %s)
        """,
        (device_id, patient_id, display_name),
    )
    return device_id


def add_session(pg: RosterPg, patient_id: str, started_at: datetime,
                ended_at: datetime | None, total: int | None, missing: int | None) -> str:
    session_id = pg.unique_session()
    pg.execute(
        """
        INSERT INTO sessions (session_id, patient_id, started_at, ended_at, device_id)
        VALUES (%s::uuid, %s::uuid, %s, %s, 'roster-test')
        """,
        (session_id, patient_id, started_at, ended_at),
    )
    if total is not None:
        pg.execute(
            """
            INSERT INTO session_stats (session_id, total_readings, missing_readings)
            VALUES (%s::uuid, %s, %s)
            """,
            (session_id, total, missing),
        )
    return session_id


def add_reading(pg: RosterPg, session_id: str, patient_id: str, seq: int,
                ts: datetime, spo2: float, hr: float) -> None:
    pg.execute(
        """
        INSERT INTO readings (session_id, patient_id, seq, ts, spo2, heart_rate, tier, qos)
        VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, 'Normal', 1)
        """,
        (session_id, patient_id, seq, ts, spo2, hr),
    )


def roster(headers: dict):
    return client.get("/patients", headers=headers)


def test_roster_shows_linked_patient_with_data_and_zero_data_patient(roster_pg):
    doc_headers, doctor_id, _ = register_and_login(roster_pg, "doctor")
    _, patient_a, _ = register_and_login(roster_pg, "patient")
    _, patient_b, _ = register_and_login(roster_pg, "patient")
    link(roster_pg, doctor_id, patient_a)
    link(roster_pg, doctor_id, patient_b)

    device_id = bind_device(roster_pg, patient_a, "Ali's watch")
    older_session = add_session(
        roster_pg, patient_a, datetime.now(UTC) - timedelta(hours=2),
        datetime.now(UTC) - timedelta(hours=1), total=50, missing=3,
    )
    add_reading(roster_pg, older_session, patient_a, 1,
                datetime.now(UTC) - timedelta(hours=2), 91.0, 71.0)
    newer_session = add_session(
        roster_pg, patient_a, datetime.now(UTC) - timedelta(minutes=30),
        datetime.now(UTC) - timedelta(minutes=5), total=108, missing=0,
    )
    add_reading(roster_pg, newer_session, patient_a, 2,
                datetime.now(UTC) - timedelta(minutes=10), 97.0, 62.0)

    r = roster(doc_headers)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"patients"}
    patients = body["patients"]
    assert [p["name"] for p in patients] == sorted(p["name"] for p in patients)

    by_id = {p["id"]: p for p in patients}
    assert set(by_id) == {patient_a, patient_b}

    pa = by_id[patient_a]
    assert set(pa) == {"id", "email", "name", "devices", "last_reading", "last_session"}
    assert pa["devices"] == [{"device_id": device_id, "display_name": "Ali's watch"}]
    assert set(pa["last_reading"]) == {"ts", "spo2", "heart_rate"}
    # latest by ts wins over the older reading
    assert pa["last_reading"]["spo2"] == 97.0
    assert pa["last_reading"]["heart_rate"] == 62.0
    ls = pa["last_session"]
    assert set(ls) == {
        "session_id", "started_at", "ended_at", "total_readings", "missing_readings",
    }
    # latest by started_at wins, with its own stats
    assert ls["session_id"] == newer_session
    assert ls["total_readings"] == 108
    assert ls["missing_readings"] == 0
    assert ls["started_at"] is not None
    assert datetime.fromisoformat(ls["ended_at"]) > datetime.now(UTC) - timedelta(minutes=6)

    pb = by_id[patient_b]
    assert pb["devices"] == []
    assert pb["last_reading"] is None
    assert pb["last_session"] is None


def test_unlinked_patient_absent_even_if_paired_elsewhere(roster_pg):
    doc_headers, _, _ = register_and_login(roster_pg, "doctor")
    other_headers, other_doctor, _ = register_and_login(roster_pg, "doctor")
    _, patient_id, _ = register_and_login(roster_pg, "patient")
    link(roster_pg, other_doctor, patient_id)

    r = roster(doc_headers)
    assert r.status_code == 200
    assert all(p["id"] != patient_id for p in r.json()["patients"])

    r_other = roster(other_headers)
    assert any(p["id"] == patient_id for p in r_other.json()["patients"])


def test_empty_roster_is_empty_array(roster_pg):
    doc_headers, _, _ = register_and_login(roster_pg, "doctor")
    r = roster(doc_headers)
    assert r.status_code == 200
    assert r.json() == {"patients": []}


def test_open_session_counts_default_to_zero(roster_pg):
    """A session without a stats row (not yet finalized) is still null-safe."""
    doc_headers, doctor_id, _ = register_and_login(roster_pg, "doctor")
    _, patient_id, _ = register_and_login(roster_pg, "patient")
    link(roster_pg, doctor_id, patient_id)
    add_session(roster_pg, patient_id, datetime.now(UTC) - timedelta(minutes=20),
                None, None, None)

    r = roster(doc_headers)
    entry = next(p for p in r.json()["patients"] if p["id"] == patient_id)
    ls = entry["last_session"]
    assert ls["ended_at"] is None
    assert ls["total_readings"] == 0
    assert ls["missing_readings"] == 0


def test_patient_jwt_is_403(roster_pg):
    pat_headers, _, _ = register_and_login(roster_pg, "patient")
    r = roster(pat_headers)
    assert r.status_code == 403
    assert "doctors" in r.json()["detail"]


def test_unauthenticated_is_401(roster_pg):
    for headers in ({}, {"Authorization": "Bearer junk"}):
        r = roster(headers)
        assert r.status_code == 401
