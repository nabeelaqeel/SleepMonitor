"""DB-backed tests for the admin role and its /admin/* endpoints.

Admins are system operators — provisioned by seed or by another admin,
never self-registered (register/google keep Literal['doctor','patient']).
Tests mint admin accounts by inserting rows directly (provisioning, not
registration) and log in to obtain tokens; the pg fixture's email
tracking cleans every inserted user up. Skips cleanly without Postgres
like the rest of the auth suite.
"""

from __future__ import annotations

import socket
import uuid

import pytest
from fastapi.testclient import TestClient

from api.db import DEMO_SEEDING_ENABLED
from api.main import app
from api.security import hash_password

client = TestClient(app)

PASSWORD = "correct-horse-42"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _admin_token(pg) -> str:
    """Provision an admin row directly and log in for a token."""
    email = pg.unique_email("admin-api")
    pg.execute(
        """
        INSERT INTO users (email, name, role, password_hash)
        VALUES (%s, %s, 'admin', %s)
        """,
        (email, "Test Admin", hash_password(PASSWORD)),
    )
    r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200
    return r.json()["token"]


def _registered_token(pg, role: str) -> str:
    """A self-registered doctor/patient account for 403 checks."""
    email = pg.unique_email(f"reg-{role}")
    r = client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "role": role},
    )
    assert r.status_code == 200
    return r.json()["token"]


def test_role_check_migration_idempotent(pg):
    """ensure_setup runs twice: no error, one widened users_role_check."""
    from api.db import ensure_setup
    from api.security import hash_password as hp

    ensure_setup(hp)
    ensure_setup(hp)
    rows = pg.query(
        """
        SELECT pg_get_constraintdef(oid)
        FROM pg_constraint
        WHERE conrelid = 'users'::regclass AND conname = 'users_role_check'
        """
    )
    assert len(rows) == 1
    definition = rows[0][0]
    assert all(role in definition for role in ("doctor", "patient", "admin"))


def test_seeded_admin_exists_and_logs_in(pg):
    """The schema/API seed row admin@sleep.com is a working admin account."""
    if not DEMO_SEEDING_ENABLED:
        pytest.skip("demo seeding disabled — no seeded admin expected")
    assert pg.query(
        "SELECT role FROM users WHERE email = 'admin@sleep.com'"
    ) == [("admin",)]
    r = client.post(
        "/auth/login", json={"email": "admin@sleep.com", "password": "1234"}
    )
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "admin"


def test_admin_endpoints_reject_patient_and_doctor(pg):
    """403 for every non-admin role on every admin endpoint; admin passes."""
    admin = _admin_token(pg)
    provisioned_email = pg.unique_email("admin-created")
    calls = [
        ("get", "/admin/users", None),
        (
            "post",
            "/admin/users",
            {"email": provisioned_email, "password": PASSWORD, "role": "patient"},
        ),
        (
            "post",
            f"/admin/users/{uuid.uuid4()}/reset-password",
            {"password": PASSWORD},
        ),
        ("get", "/admin/health", None),
        ("get", "/admin/qos-sessions", None),
    ]
    for role in ("patient", "doctor"):
        token = _registered_token(pg, role)
        for method, path, body in calls:
            r = client.request(method, path, json=body, headers=_auth(token))
            assert r.status_code == 403, f"{role} {method} {path} must be 403"
            assert "admin" in r.json()["detail"].lower()
    for method, path, body in calls:
        r = client.request(method, path, json=body, headers=_auth(admin))
        # the reset call targets a random uuid → 404 by design (real-id
        # reset is covered by test_admin_reset_password_old_fails_new_works)
        expected = 404 if "reset-password" in path else 200
        assert r.status_code == expected, f"admin {method} {path} must be {expected}"


def test_admin_endpoints_require_bearer_token(pg):
    """Missing/invalid credentials are 401 before any role check matters."""
    _admin_token(pg)
    bodies = {
        "post": {"email": "x@sleep.test", "password": PASSWORD, "role": "patient"},
    }
    for method, path in (
        ("get", "/admin/users"),
        ("post", "/admin/users"),
        ("get", "/admin/health"),
        ("get", "/admin/qos-sessions"),
    ):
        r = client.request(method, path, json=bodies.get(method))
        assert r.status_code == 401, f"{method} {path} without token must be 401"
    r = client.get("/admin/users", headers=_auth("not-a-jwt"))
    assert r.status_code == 401


def test_admin_lists_users_without_hashes(pg):
    """GET /admin/users returns the five safe fields for every account."""
    admin = _admin_token(pg)
    email = pg.unique_email("reg-listed")
    assert client.post(
        "/auth/register",
        json={"email": email, "password": PASSWORD, "role": "patient"},
    ).status_code == 200
    r = client.get("/admin/users", headers=_auth(admin))
    assert r.status_code == 200
    users = r.json()["users"]
    mine = [u for u in users if u["email"] == email]
    assert len(mine) == 1
    assert set(mine[0]) == {"id", "email", "name", "role", "created_at"}
    assert all("password_hash" not in u for u in users)


def test_admin_creates_user_then_created_user_logs_in(pg):
    """Provisioned accounts work exactly like registered ones."""
    admin = _admin_token(pg)
    email = pg.unique_email("admin-created")
    r = client.post(
        "/admin/users",
        headers=_auth(admin),
        json={
            "email": email.upper(),
            "name": "Provisioned Doctor",
            "password": PASSWORD,
            "role": "doctor",
        },
    )
    assert r.status_code == 200
    user = r.json()["user"]
    assert set(user) == {"id", "email", "name", "role"}
    assert user["email"] == email  # stored lowercase like register
    assert user["name"] == "Provisioned Doctor"
    assert user["role"] == "doctor"

    login = client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200
    assert login.json()["user"]["id"] == user["id"]

    # the provisioned doctor token also carries the doctor role
    v = client.get("/auth/verify", headers=_auth(login.json()["token"]))
    assert v.json() == {"sub": user["id"], "role": "doctor"}


def test_admin_can_provision_another_admin(pg):
    """POST /admin/users is the only path that mints an admin."""
    admin = _admin_token(pg)
    email = pg.unique_email("admin-created")
    r = client.post(
        "/admin/users",
        headers=_auth(admin),
        json={"email": email, "password": PASSWORD, "role": "admin"},
    )
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "admin"
    token = client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    ).json()["token"]
    assert client.get("/admin/users", headers=_auth(token)).status_code == 200


def test_admin_create_duplicate_email_is_409(pg):
    admin = _admin_token(pg)
    email = pg.unique_email("admin-created")
    payload = {"email": email, "password": PASSWORD, "role": "patient"}
    assert client.post("/admin/users", headers=_auth(admin), json=payload).status_code == 200
    r = client.post("/admin/users", headers=_auth(admin), json=payload)
    assert r.status_code == 409
    assert "registered" in r.json()["detail"].lower()


def test_admin_create_validates_role_and_password(pg):
    """Same 422 rules as register: role outside the set, password < 8."""
    admin = _admin_token(pg)
    email = pg.unique_email("admin-created")
    base = {"email": email, "password": PASSWORD, "role": "patient"}
    r = client.post("/admin/users", headers=_auth(admin), json={**base, "role": "nurse"})
    assert r.status_code == 422
    r = client.post("/admin/users", headers=_auth(admin), json={**base, "password": "short"})
    assert r.status_code == 422


def test_admin_reset_password_old_fails_new_works(pg):
    admin = _admin_token(pg)
    email = pg.unique_email("reg-reset")
    old_password = "old-password-11"
    assert client.post(
        "/auth/register",
        json={"email": email, "password": old_password, "role": "patient"},
    ).status_code == 200
    users = client.get("/admin/users", headers=_auth(admin)).json()["users"]
    user_id = next(u["id"] for u in users if u["email"] == email)

    r = client.post(
        f"/admin/users/{user_id}/reset-password",
        headers=_auth(admin),
        json={"password": "new-password-22"},
    )
    assert r.status_code == 200
    assert set(r.json()["user"]) == {"id", "email", "name", "role"}

    assert client.post(
        "/auth/login", json={"email": email, "password": old_password}
    ).status_code == 401
    ok = client.post(
        "/auth/login", json={"email": email, "password": "new-password-22"}
    )
    assert ok.status_code == 200
    assert ok.json()["user"]["id"] == user_id


def test_admin_reset_password_validates_and_404s(pg):
    admin = _admin_token(pg)
    # short password → 422
    r = client.post(
        f"/admin/users/{uuid.uuid4()}/reset-password",
        headers=_auth(admin),
        json={"password": "short"},
    )
    assert r.status_code == 422
    # unknown but well-formed user_id → 404
    r = client.post(
        f"/admin/users/{uuid.uuid4()}/reset-password",
        headers=_auth(admin),
        json={"password": PASSWORD},
    )
    assert r.status_code == 404
    # malformed user_id → 404, never a 500 from the uuid cast
    r = client.post(
        "/admin/users/not-a-uuid/reset-password",
        headers=_auth(admin),
        json={"password": PASSWORD},
    )
    assert r.status_code == 404


def test_admin_qos_sessions_shape_and_fixture_row(pg):
    """Rows carry the delivery accounting; a seeded fixture row round-trips."""
    admin = _admin_token(pg)
    email = pg.unique_email("reg-qos")
    pg.execute(
        """
        INSERT INTO users (email, name, role, password_hash)
        VALUES (%s, %s, 'patient', '')
        """,
        (email, "QoS Patient"),
    )
    uid = pg.query(
        "SELECT user_id::text FROM users WHERE lower(email) = %s", (email,)
    )[0][0]
    session_id = str(uuid.uuid4())
    pg.execute(
        """
        INSERT INTO sessions (session_id, patient_id, started_at)
        VALUES (%s, %s, NOW())
        """,
        (session_id, uid),
    )
    pg.execute(
        """
        INSERT INTO session_stats
            (session_id, expected_readings, received_readings, missing_readings)
        VALUES (%s, 10, 8, 2)
        """,
        (session_id,),
    )
    r = client.get("/admin/qos-sessions", headers=_auth(admin))
    assert r.status_code == 200
    sessions = r.json()["sessions"]
    assert len(sessions) <= 20
    mine = next(s for s in sessions if s["session_id"] == session_id)
    assert set(mine) == {
        "session_id", "expected_readings", "received_readings",
        "missing_readings", "delivery_pct", "computed_at",
    }
    assert mine["expected_readings"] == 10
    assert mine["received_readings"] == 8
    assert mine["missing_readings"] == 2
    assert mine["delivery_pct"] == 80.0


def test_admin_health_reports_database_and_broker(pg, monkeypatch):
    """DB reachable + broker reachable → ok; closed port → degraded broker."""
    admin = _admin_token(pg)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        monkeypatch.setenv("MQTT_HOST", "127.0.0.1")
        monkeypatch.setenv("MQTT_PORT", str(port))
        r = client.get("/admin/health", headers=_auth(admin))
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["api"] == {"status": "ok"}
        assert body["database"]["reachable"] is True
        assert "last_data_received" in body["database"]
        assert body["broker"] == {
            "host": "127.0.0.1", "port": port, "reachable": True,
        }
    finally:
        listener.close()
    monkeypatch.setenv("MQTT_PORT", "1")  # closed loopback port → refused
    body = client.get("/admin/health", headers=_auth(admin)).json()
    assert body["broker"]["reachable"] is False
    assert body["status"] == "degraded"
    assert body["database"]["reachable"] is True
