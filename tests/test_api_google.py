"""Google sign-in tests — fully offline by construction.

Two layers:

  * /auth/google endpoint behaviour with the token verifier swapped out via
    the FastAPI dependency (app.dependency_overrides on get_google_verifier)
    and the users table faked in memory (monkeypatch of api.main's
    get_user_by_email / create_user). No test here may touch the network —
    the 503-config-gate test additionally asserts the stub verifier is
    never even called, proving the gate fires before verification.
  * api.google_auth.verify_google_token itself, exercised against a locally
    generated RSA keypair whose JWK is fed to the module with _fetch_jwks
    monkeypatched — so signature/aud/iss/exp/email checks run for real
    without Google's certificate endpoint.
"""

from __future__ import annotations

import json
import time
import uuid
from urllib.error import URLError

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from jose.jwk import RSAKey as JoseRsaKey

import api.config
import api.main
from api import google_auth
from api.google_auth import (
    GoogleTokenError,
    GoogleUnavailableError,
    verify_google_token,
)
from api.main import app, get_google_verifier

client = TestClient(app)

CLIENT_ID = "test-google-client-id"


def id_token_for(email: str, **flags) -> str:
    """Build a stub id_token the fake verifier decodes back into claims."""
    return json.dumps({"email": email, **flags})


@pytest.fixture
def google_env(monkeypatch):
    """Configured GOOGLE_CLIENT_ID by default + an in-memory users table.

    Reading config at request time (api.config.GOOGLE_CLIENT_ID) is what
    makes the gate monkeypatchable per test; the 503 test overrides it
    back to empty.
    """
    monkeypatch.setattr(api.config, "GOOGLE_CLIENT_ID", CLIENT_ID)
    store: dict[str, dict] = {}

    def get_user_by_email(email: str) -> dict | None:
        matches = [u for u in store.values() if u["email"] == email.strip().lower()]
        return matches[0] if len(matches) == 1 else None

    def create_user(email: str, name: str, role: str, password_hash: str) -> dict | None:
        email = email.strip().lower()
        if any(u["email"] == email for u in store.values()):
            return None
        user = {
            "user_id": str(uuid.uuid4()),
            "email": email,
            "name": name,
            "role": role,
            "password_hash": password_hash,
        }
        store[user["user_id"]] = user
        return user

    monkeypatch.setattr(api.main, "get_user_by_email", get_user_by_email)
    monkeypatch.setattr(api.main, "create_user", create_user)
    return store


@pytest.fixture
def stub_verifier():
    """Swap the real verifier for a JSON-decoding fake — no network, ever."""
    calls: list[tuple[str, str]] = []

    def verifier(id_token: str, client_id: str) -> dict:
        calls.append((id_token, client_id))
        payload = json.loads(id_token)
        reason = payload.get("bad")
        if reason == "signature":
            raise GoogleTokenError("signature verification failed")
        if reason == "expired":
            raise GoogleTokenError("token expired")
        if reason == "unreachable":
            raise GoogleUnavailableError("cannot reach Google JWKS")
        return {
            "sub": "google-1",
            "email": payload["email"],
            "name": "Google Person",
            "email_verified": True,
        }

    app.dependency_overrides[get_google_verifier] = lambda: verifier
    yield verifier, calls
    app.dependency_overrides.pop(get_google_verifier, None)


# ── /auth/google endpoint ─────────────────────────────────────────────────────

def test_google_unconfigured_returns_503(google_env, stub_verifier, monkeypatch):
    """GOOGLE_CLIENT_ID unset → 503 BEFORE the verifier is ever invoked."""
    monkeypatch.setattr(api.config, "GOOGLE_CLIENT_ID", "")
    _, calls = stub_verifier
    r = client.post("/auth/google", json={"id_token": id_token_for("x@sleep.test")})
    assert r.status_code == 503
    assert "GOOGLE_CLIENT_ID" in r.json()["detail"]
    assert calls == []


def test_google_known_email_logs_in_ignoring_supplied_role(google_env, stub_verifier, monkeypatch):
    """Known email → exact /auth/login shape; supplied role must NOT win."""
    monkeypatch.setattr(api.config, "GOOGLE_CLIENT_ID", CLIENT_ID)
    google_env["g1"] = {
        "user_id": "g-user-1",
        "email": "known@sleep.test",
        "name": "Known User",
        "role": "patient",
        "password_hash": "stored-bcrypt-hash",
    }
    _, calls = stub_verifier
    r = client.post(
        "/auth/google",
        json={"id_token": id_token_for("known@sleep.test"), "role": "doctor"},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"user", "token"}
    assert body["user"] == {
        "id": "g-user-1",
        "email": "known@sleep.test",
        "name": "Known User",
        "role": "patient",
    }
    # The real client id reached the verifier — config plumbing works.
    assert calls[0][1] == CLIENT_ID

    v = client.get("/auth/verify", headers={"Authorization": f"Bearer {body['token']}"})
    assert v.status_code == 200
    assert v.json() == {"sub": "g-user-1", "role": "patient"}


def test_google_unknown_email_without_role_needs_role(google_env, stub_verifier):
    _, _ = stub_verifier
    r = client.post(
        "/auth/google", json={"id_token": id_token_for("fresh@sleep.test")}
    )
    assert r.status_code == 200
    assert r.json() == {"needs_role": True}
    assert google_env == {}  # no user row was created


def test_google_unknown_email_with_role_creates_user(google_env, stub_verifier):
    _, _ = stub_verifier
    r = client.post(
        "/auth/google",
        json={"id_token": id_token_for("fresh@sleep.test"), "role": "doctor"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "doctor"
    assert body["token"]

    created = google_env[body["user"]["id"]]
    assert created["email"] == "fresh@sleep.test"
    # Google accounts have no local password — empty hash never verifies.
    assert created["password_hash"] == ""

    v = client.get("/auth/verify", headers={"Authorization": f"Bearer {body['token']}"})
    assert v.status_code == 200
    assert v.json() == {"sub": body["user"]["id"], "role": "doctor"}


def test_google_created_user_cannot_password_login(google_env, stub_verifier):
    """A Google account's empty hash must fail /auth/login for any password."""
    _, _ = stub_verifier
    assert (
        client.post(
            "/auth/google",
            json={"id_token": id_token_for("fresh@sleep.test"), "role": "patient"},
        ).status_code
        == 200
    )
    r = client.post(
        "/auth/login", json={"email": "fresh@sleep.test", "password": "anything-8+"}
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"


def test_google_tampered_token_is_401(google_env, stub_verifier):
    _, _ = stub_verifier
    r = client.post(
        "/auth/google",
        json={"id_token": id_token_for("x@sleep.test", bad="signature")},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid or expired Google token"


def test_google_expired_token_is_401(google_env, stub_verifier):
    _, _ = stub_verifier
    r = client.post(
        "/auth/google",
        json={"id_token": id_token_for("x@sleep.test", bad="expired")},
    )
    assert r.status_code == 401


def test_google_unreachable_jwks_is_503(google_env, stub_verifier, monkeypatch):
    """Token fine but Google's certificate endpoint down → 503, not 401."""
    monkeypatch.setattr(api.config, "GOOGLE_CLIENT_ID", CLIENT_ID)
    _, _ = stub_verifier
    r = client.post(
        "/auth/google",
        json={"id_token": id_token_for("x@sleep.test", bad="unreachable")},
    )
    assert r.status_code == 503


def test_google_missing_id_token_is_422(google_env, stub_verifier):
    _, _ = stub_verifier
    assert client.post("/auth/google", json={}).status_code == 422


def test_google_invalid_role_is_422(google_env, stub_verifier, monkeypatch):
    monkeypatch.setattr(api.config, "GOOGLE_CLIENT_ID", CLIENT_ID)
    _, _ = stub_verifier
    r = client.post(
        "/auth/google",
        json={"id_token": id_token_for("fresh@sleep.test"), "role": "nurse"},
    )
    assert r.status_code == 422


# ── api.google_auth.verify_google_token (real verification, fake JWKS) ───────

def _keypair() -> tuple[bytes, dict]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    jwk = JoseRsaKey(key=key.public_key(), algorithm="RS256").to_dict()
    jwk["kid"] = "unit-kid"
    jwk["use"] = "sig"
    return pem, jwk


def _sign(pem: bytes, kid: str = "unit-kid", **claim_overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "sub": "google-1",
        "email": "g.person@sleep.test",
        "email_verified": True,
        "name": "Google Person",
        "iat": now,
        "exp": now + 600,
    }
    claims.update(claim_overrides)
    return jose_jwt.encode(claims, pem, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def offline_jwks(monkeypatch):
    """Feed the module a locally generated JWKS — zero network access."""
    pem, jwk = _keypair()
    monkeypatch.setattr(google_auth, "_jwks_cache", [])
    monkeypatch.setattr(google_auth, "_jwks_cached_at", 0.0)
    monkeypatch.setattr(google_auth, "_fetch_jwks", lambda: [jwk])
    return pem, jwk


def test_valid_google_token_accepted(offline_jwks):
    pem, _ = offline_jwks
    claims = verify_google_token(_sign(pem), CLIENT_ID)
    assert claims["email"] == "g.person@sleep.test"
    assert claims["aud"] == CLIENT_ID


def test_wrong_audience_rejected(offline_jwks):
    pem, _ = offline_jwks
    with pytest.raises(GoogleTokenError):
        verify_google_token(_sign(pem, aud="someone-elses-client"), CLIENT_ID)


def test_expired_token_rejected(offline_jwks):
    pem, _ = offline_jwks
    with pytest.raises(GoogleTokenError):
        verify_google_token(_sign(pem, exp=-10), CLIENT_ID)


def test_missing_email_rejected(offline_jwks):
    pem, _ = offline_jwks
    with pytest.raises(GoogleTokenError):
        verify_google_token(_sign(pem, email=None), CLIENT_ID)


def test_unverified_email_rejected(offline_jwks):
    pem, _ = offline_jwks
    with pytest.raises(GoogleTokenError):
        verify_google_token(_sign(pem, email_verified=False), CLIENT_ID)


def test_wrong_issuer_rejected(offline_jwks):
    pem, _ = offline_jwks
    with pytest.raises(GoogleTokenError):
        verify_google_token(_sign(pem, iss="https://evil.example"), CLIENT_ID)


def test_garbage_token_rejected(offline_jwks):
    with pytest.raises(GoogleTokenError):
        verify_google_token("not-a-jwt", CLIENT_ID)


def test_unknown_kid_refetches_then_rejects(offline_jwks):
    """A rotated key forces one cache refresh; still unknown → rejected."""
    pem, jwk = offline_jwks
    fetches: list[int] = []

    def counting_fetch() -> list[dict]:
        fetches.append(1)
        return [jwk]

    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(google_auth, "_fetch_jwks", counting_fetch)
        with pytest.raises(GoogleTokenError):
            verify_google_token(_sign(pem, kid="rotated-kid"), CLIENT_ID)
        assert len(fetches) == 2  # normal read + the forced rotation refresh
    finally:
        mp.undo()


def test_jwks_fetch_failure_is_unavailable(offline_jwks):
    """Empty cache + unreachable endpoint → GoogleUnavailableError (→ 503)."""
    def failing_fetch():
        raise URLError("network down")

    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(google_auth, "_fetch_jwks", failing_fetch)
        with pytest.raises(GoogleUnavailableError):
            verify_google_token(_sign(offline_jwks[0]), CLIENT_ID)
    finally:
        mp.undo()


def test_stale_cache_survives_fetch_failure(offline_jwks):
    """Trusted-but-stale keys still verify — better than rejecting everyone."""
    pem, jwk = offline_jwks

    def failing_fetch():
        raise URLError("network down")

    # Force the TTL-expired path while keeping the previously cached key.
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(google_auth, "_jwks_cache", [jwk])
        monkeypatch.setattr(google_auth, "_jwks_cached_at", 0.0)
        monkeypatch.setattr(google_auth, "_fetch_jwks", failing_fetch)
        claims = verify_google_token(_sign(pem), CLIENT_ID)
        assert claims["email"] == "g.person@sleep.test"
    finally:
        monkeypatch.undo()
