"""Tests for GET /alerts — the doctor's persisted alert history feed.

Same Postgres-or-skip contract as the other DB-backed auth tests: this
file owns its fixtures (no conftest edits) and deletes every created
user at teardown; sessions (and the alerts cascading off them) go first.
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

ALERT_KEYS = {
    "alert_id", "patient_id", "patient_name", "severity",
    "spo2", "heart_rate", "ts", "session_id",
}


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


class AlertsPg:
    """Reachable-Postgres handle with test-user/session bookkeeping."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._emails: list[str] = []
        self._sessions: list[str] = []

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

    def cleanup(self) -> None:
        # Alerts cascade off sessions, sessions off users — two deletes.
        for session_id in self._sessions:
            self.execute("DELETE FROM sessions WHERE session_id = %s::uuid", (session_id,))
        for email in self._emails:
            self.execute("DELETE FROM users WHERE lower(email) = lower(%s)", (email,))


@pytest.fixture(scope="session")
def alerts_pg():
    """Reachable-Postgres handle + the idempotent ensure_setup migration."""
    dsn = next((d for d in _dsn_candidates() if _reachable(d)), None)
    if dsn is None:
        pytest.skip("local Postgres unreachable — alerts tests skipped")

    from api.db import ensure_setup

    handle = AlertsPg(dsn)
    mp = pytest.MonkeyPatch()
    mp.setattr(api.db, "DATABASE_URL", dsn)
    try:
        ensure_setup(hash_password)
        yield handle
    finally:
        mp.undo()
        handle.cleanup()


def register_and_login(pg: AlertsPg, role: str):
    """Fresh account → 200; returns (headers, user_id, email)."""
    email = pg.unique_email(f"alerts-{role}")
    r = client.post(
        "/auth/register",
        json={"email": email, "password": "correct-horse-42", "role": role},
    )
    assert r.status_code == 200
    body = r.json()
    return {"Authorization": f"Bearer {body['token']}"}, body["user"]["id"], email


def link(pg: AlertsPg, doctor_id: str, patient_id: str) -> None:
    pg.execute(
        """
        INSERT INTO doctor_patients (doctor_id, patient_id)
        VALUES (%s::uuid, %s::uuid)
        ON CONFLICT DO NOTHING
        """,
        (doctor_id, patient_id),
    )


def add_alert(pg: AlertsPg, patient_id: str, seq: int, ts: datetime,
              severity: str, spo2: float, hr: float) -> str:
    """One session per alert row — alerts FK both session and patient."""
    session_id = str(uuid.uuid4())
    pg._sessions.append(session_id)
    pg.execute(
        """
        INSERT INTO sessions (session_id, patient_id, started_at, device_id)
        VALUES (%s::uuid, %s::uuid, %s, 'alerts-test')
        """,
        (session_id, patient_id, ts),
    )
    pg.execute(
        """
        INSERT INTO alerts (session_id, patient_id, seq, ts, severity, spo2, heart_rate)
        VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s)
        """,
        (session_id, patient_id, seq, ts, severity, spo2, hr),
    )
    return session_id


def get_alerts(headers: dict):
    return client.get("/alerts", headers=headers)


def test_alert_shape_values_and_ts_desc_ordering(alerts_pg):
    doc_headers, doctor_id, _ = register_and_login(alerts_pg, "doctor")
    _, patient_id, _ = register_and_login(alerts_pg, "patient")
    link(alerts_pg, doctor_id, patient_id)

    base = datetime.now(UTC) - timedelta(hours=1)
    oldest = add_alert(alerts_pg, patient_id, 1, base,
                       "Important", 91.0, 101.0)
    middle = add_alert(alerts_pg, patient_id, 2, base + timedelta(minutes=5),
                       "Critical", 88.0, 118.0)
    newest = add_alert(alerts_pg, patient_id, 3, base + timedelta(minutes=9),
                       "Critical", 87.5, 121.0)

    r = get_alerts(doc_headers)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"alerts"}
    alerts = body["alerts"]
    assert len(alerts) == 3

    # Newest first, exactly the contract key set, exact values round-tripped.
    assert [a["session_id"] for a in alerts] == [newest, middle, oldest]
    assert all(set(a) == ALERT_KEYS for a in alerts)
    assert [a["severity"] for a in alerts] == ["Critical", "Critical", "Important"]
    crit = alerts[0]
    assert crit["spo2"] == 87.5
    assert crit["heart_rate"] == 121.0
    assert isinstance(crit["alert_id"], int)
    assert crit["patient_id"] == patient_id
    assert crit["patient_name"]
    ts = datetime.fromisoformat(crit["ts"])
    assert ts.utcoffset() == timedelta(0)


def test_alerts_scoped_to_linked_patients(alerts_pg):
    doc_a_headers, _, _ = register_and_login(alerts_pg, "doctor")
    doc_b_headers, doc_b, _ = register_and_login(alerts_pg, "doctor")
    _, patient_b1, _ = register_and_login(alerts_pg, "patient")
    _, patient_b2, _ = register_and_login(alerts_pg, "patient")
    link(alerts_pg, doc_b, patient_b1)
    link(alerts_pg, doc_b, patient_b2)
    base = datetime.now(UTC) - timedelta(minutes=30)
    add_alert(alerts_pg, patient_b1, 1, base, "Important", 90.0, 99.0)
    add_alert(alerts_pg, patient_b2, 2, base + timedelta(minutes=1),
              "Critical", 85.0, 130.0)

    r_a = get_alerts(doc_a_headers)
    assert r_a.status_code == 200
    assert r_a.json() == {"alerts": []}

    r_b = get_alerts(doc_b_headers)
    assert r_b.status_code == 200
    got = r_b.json()["alerts"]
    assert {a["patient_id"] for a in got} == {patient_b1, patient_b2}
    # Cross-doctor ordering still holds: b2's alert is one minute newer.
    assert [a["patient_id"] for a in got] == [patient_b2, patient_b1]


def test_limit_50_hard_cap_keeps_newest(alerts_pg):
    doc_headers, doctor_id, _ = register_and_login(alerts_pg, "doctor")
    _, patient_id, _ = register_and_login(alerts_pg, "patient")
    link(alerts_pg, doctor_id, patient_id)
    base = datetime.now(UTC) - timedelta(hours=1)
    # One session holds all 51 rows (alerts are unique per (session, seq)).
    session_id = str(uuid.uuid4())
    alerts_pg._sessions.append(session_id)
    alerts_pg.execute(
        """
        INSERT INTO sessions (session_id, patient_id, started_at, device_id)
        VALUES (%s::uuid, %s::uuid, %s, 'alerts-test')
        """,
        (session_id, patient_id, base),
    )
    for seq in range(1, 52):
        ts = base + timedelta(seconds=seq)
        alerts_pg.execute(
            """
            INSERT INTO alerts (session_id, patient_id, seq, ts, severity, spo2, heart_rate)
            VALUES (%s::uuid, %s::uuid, %s, %s, 'Important', 89.0, 100.0)
            """,
            (session_id, patient_id, seq, ts),
        )

    r = get_alerts(doc_headers)
    assert r.status_code == 200
    alerts = r.json()["alerts"]
    assert len(alerts) == 50
    # seq 1 (oldest ts) fell off the bottom; the 50 newest remain.
    stamps = [datetime.fromisoformat(a["ts"]) for a in alerts]
    assert stamps == sorted(stamps, reverse=True)
    assert stamps[0] == base + timedelta(seconds=51)
    assert stamps[-1] == base + timedelta(seconds=2)


def test_no_alerts_is_empty_array(alerts_pg):
    doc_headers, doctor_id, _ = register_and_login(alerts_pg, "doctor")
    _, patient_id, _ = register_and_login(alerts_pg, "patient")
    link(alerts_pg, doctor_id, patient_id)
    r = get_alerts(doc_headers)
    assert r.status_code == 200
    assert r.json() == {"alerts": []}


def test_patient_jwt_is_403(alerts_pg):
    pat_headers, _, _ = register_and_login(alerts_pg, "patient")
    r = get_alerts(pat_headers)
    assert r.status_code == 403
    assert "doctors" in r.json()["detail"]


def test_unauthenticated_is_401(alerts_pg):
    for headers in ({}, {"Authorization": "Bearer junk"}):
        r = get_alerts(headers)
        assert r.status_code == 401
