"""DB-free unit tests for the auth endpoints beyond the smoke pair.

test_api_smoke.py proves the import chain and the two cheapest guards
(health probe, verify-without-header). This file covers the two real
routes — /auth/login and /auth/verify — for the happy path and every
documented 401/422 shape, while keeping CI hermetic:

  * only api.main.get_user_by_email is faked (monkeypatch) — Postgres is
    never touched; bcrypt and the JWT layer run for real, so the
    login→verify round-trip is a genuine pass through security.py.
  * the unknown-email case deliberately does NOT fake get_dummy_hash —
    the 401 still burns the real bcrypt cost, so the no-user-enumeration
    assertion stays honest (same detail string as wrong-password).

Expired and forged-signature tokens are crafted with jose directly
against the live JWT_SECRET — nothing inside the security layer is
mocked for them.

TestClient is used WITHOUT a context manager (same as test_api_smoke.py)
so the FastAPI lifespan (ensure_setup → Postgres) never runs.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt

import api.main
from api.config import JWT_SECRET
from api.main import app
from api.security import hash_password

# Module-level on purpose: one app import for the whole test session.
# NOT entered as a context manager — that is what triggers the lifespan.
client = TestClient(app)

USER_ID = "11111111-1111-1111-1111-111111111111"
EMAIL = "dr.test@sleep.com"
NAME = "Dr. Test"
ROLE = "doctor"
PASSWORD = "correct-horse-battery-staple"
# The one generic message login raises for BOTH unknown email and wrong
# password — pinning it is the no-user-enumeration guarantee.
GENERIC_401 = "Invalid email or password"


def fake_user(password_hash: str) -> dict:
    """A users-table row shaped exactly like api.db.get_user_by_email's output."""
    return {
        "user_id": USER_ID,
        "email": EMAIL,
        "name": NAME,
        "role": ROLE,
        "password_hash": password_hash,
    }


@pytest.fixture
def known_user(monkeypatch):
    """Point get_user_by_email at an in-memory doctor account (no DB)."""
    row = fake_user(hash_password(PASSWORD))
    monkeypatch.setattr(api.main, "get_user_by_email", lambda _email: row)
    return row


def login(email: str, password: str):
    """POST /auth/login with JSON creds (missing fields fail fast in pydantic)."""
    return client.post(
        "/auth/login", json={"email": email, "password": password}
    )


def verify(token: str):
    """GET /auth/verify with a Bearer token."""
    return client.get("/auth/verify", headers={"Authorization": f"Bearer {token}"})


def test_login_success_returns_token_and_safe_user(known_user):
    """Correct creds → 200 with a JWT and EXACTLY the four safe user fields."""
    r = login(EMAIL, PASSWORD)
    assert r.status_code == 200
    body = r.json()
    assert body["token"]
    # Exact key set — pins that password_hash (or anything else) never leaks.
    assert set(body["user"]) == {"id", "email", "name", "role"}
    assert body["user"] == {
        "id": USER_ID,
        "email": EMAIL,
        "name": NAME,
        "role": ROLE,
    }


def test_login_wrong_password_is_generic_401(known_user):
    """A known email with the wrong password gets the generic 401 message."""
    r = login(EMAIL, "not-the-password")
    assert r.status_code == 401
    assert r.json()["detail"] == GENERIC_401


def test_unknown_email_and_wrong_password_share_the_string(known_user, monkeypatch):
    """No user enumeration: unknown email answers identically to wrong password.

    get_dummy_hash runs for real here — the unknown-email path burns the
    same bcrypt cost before landing on the identical detail string.
    """
    r_wrong = login(EMAIL, "not-the-password")
    monkeypatch.setattr(api.main, "get_user_by_email", lambda _email: None)
    r_unknown = login("nobody@sleep.com", "whatever-pass")
    assert r_unknown.status_code == r_wrong.status_code == 401
    assert r_unknown.json()["detail"] == r_wrong.json()["detail"] == GENERIC_401


def test_login_requires_email_and_password_422(known_user):
    """Missing email and/or password → 422 before any handler code runs."""
    for payload in ({}, {"email": EMAIL}, {"password": PASSWORD}):
        r = client.post("/auth/login", json=payload)
        assert r.status_code == 422, f"payload {payload!r} should be rejected"


def test_login_token_round_trips_through_verify(known_user):
    """The token login issues must validate on /auth/verify with its claims."""
    token = login(EMAIL, PASSWORD).json()["token"]
    r = verify(token)
    assert r.status_code == 200
    assert r.json() == {"sub": USER_ID, "role": ROLE}


def test_verify_accepts_lowercase_bearer_scheme(known_user):
    """The scheme match is case-insensitive (`authorization.lower()` in main)."""
    token = login(EMAIL, PASSWORD).json()["token"]
    r = client.get(
        "/auth/verify", headers={"Authorization": f"bearer {token}"}
    )
    assert r.status_code == 200


def test_verify_rejects_non_bearer_scheme():
    """A present-but-wrong auth scheme is the same 401 as a missing header."""
    for value in ("Token abc123", "Basic dXNlcjpwYXNz"):
        r = client.get("/auth/verify", headers={"Authorization": value})
        assert r.status_code == 401
        assert "Bearer" in r.json()["detail"]


def test_verify_rejects_garbage_token():
    """An unparseable token is 401 with the invalid/expired message."""
    r = verify("not-a-jwt")
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid or expired token"


def test_verify_rejects_expired_token():
    """A correctly-signed token past its exp claim is rejected the same way."""
    now = int(datetime.now(UTC).timestamp())
    expired = jose_jwt.encode(
        {"sub": USER_ID, "role": ROLE, "iat": now - 13 * 3600, "exp": now - 3600},
        JWT_SECRET,
        algorithm="HS256",
    )
    r = verify(expired)
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid or expired token"


def test_verify_rejects_forged_signature():
    """A well-formed token signed by anyone else fails signature validation."""
    now = int(datetime.now(UTC).timestamp())
    forged = jose_jwt.encode(
        {"sub": USER_ID, "role": ROLE, "iat": now, "exp": now + 3600},
        "an-entirely-different-secret",
        algorithm="HS256",
    )
    r = verify(forged)
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid or expired token"
