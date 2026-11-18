"""DB-backed tests for /auth/register plus seeded-account login regression.

Runs against the local Postgres via the `pg` fixture (tests/conftest.py)
and skips cleanly when it is unreachable — CI never runs with a database.
Every test mints fresh uuid-suffixed emails and the fixture deletes them
afterwards, so reruns never collide and the demo DB stays clean.

The regression half pins the demo-day guarantee: the seeded accounts
(doctor@sleep.com / patient@sleep.com, password 1234) keep logging in
after the registration and pairing work lands.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

GENERIC_401 = "Invalid email or password"


def register(email: str, password: str, role: str):
    return client.post(
        "/auth/register",
        json={"email": email, "password": password, "role": role},
    )


def login(email: str, password: str):
    return client.post("/auth/login", json={"email": email, "password": password})


def test_register_success_mirrors_login_shape(pg):
    """200 {user, token} with exactly the four safe fields, email lowercased."""
    email = pg.unique_email("reg-ok")
    r = register(email, "correct-horse-42", "patient")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"user", "token"}
    assert set(body["user"]) == {"id", "email", "name", "role"}
    assert body["user"]["email"] == email  # create_user stores lowercase
    assert body["user"]["role"] == "patient"


def test_register_duplicate_email_is_409(pg):
    email = pg.unique_email("reg-dup")
    assert register(email, "correct-horse-42", "patient").status_code == 200
    r = register(email, "another-password-9", "patient")
    assert r.status_code == 409
    assert "registered" in r.json()["detail"].lower()


def test_register_duplicate_is_case_insensitive(pg):
    """create_user lowercases emails, so a case variant is still the same address."""
    email = pg.unique_email("reg-case")
    assert register(email, "correct-horse-42", "doctor").status_code == 200
    r = register(email.upper(), "another-password-9", "doctor")
    assert r.status_code == 409


def test_register_bad_role_is_422(pg):
    email = pg.unique_email("reg-role")
    for payload_role in ("nurse", "", "DOCTOR"):
        r = client.post(
            "/auth/register",
            json={"email": email, "password": "correct-horse-42", "role": payload_role},
        )
        assert r.status_code == 422, f"role {payload_role!r} must be rejected"
    # role absent entirely
    r = client.post(
        "/auth/register", json={"email": email, "password": "correct-horse-42"}
    )
    assert r.status_code == 422


def test_register_short_password_is_422(pg):
    email = pg.unique_email("reg-shortpw")
    for password in ("", "1234567"):
        r = client.post(
            "/auth/register",
            json={"email": email, "password": password, "role": "patient"},
        )
        assert r.status_code == 422, f"password {password!r} must be rejected"
    # password absent entirely
    r = client.post(
        "/auth/register", json={"email": email, "role": "patient"}
    )
    assert r.status_code == 422


def test_register_login_round_trip(pg):
    """The account /auth/register creates must log in like a seeded one."""
    email = pg.unique_email("reg-roundtrip")
    password = "correct-horse-42"
    registered = register(email, password, "doctor")
    assert registered.status_code == 200

    r = login(email, password)
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["id"] == registered.json()["user"]["id"]
    assert body["user"]["role"] == "doctor"

    v = client.get(
        "/auth/verify", headers={"Authorization": f"Bearer {body['token']}"}
    )
    assert v.status_code == 200
    assert v.json() == {
        "sub": registered.json()["user"]["id"],
        "role": "doctor",
    }


def test_seeded_accounts_still_login(pg):
    """Demo-day fallback: the two seeded accounts keep working unchanged."""
    r = login("doctor@sleep.com", "1234")
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "doctor"

    r = login("patient@sleep.com", "1234")
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "patient"


def test_seeded_bad_password_still_401(pg):
    r = login("doctor@sleep.com", "not-the-password")
    assert r.status_code == 401
    assert r.json()["detail"] == GENERIC_401
