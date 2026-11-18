"""DB-backed tests for the doctor pairing flow (pairing-code + link-doctor).

Same Postgres-or-skip contract as test_api_register.py (tests/conftest.py):
the `pg` fixture runs ensure_setup (which applies the pairing_code
migration) and hands out fresh emails, deleting every created user on
teardown. Seeded-doctor state is exercised directly so lazy minting has
coverage without touching seeded credentials.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def register_and_login(pg, role: str):
    """Fresh account → 200 {user, token}; returns (headers, user_id, email)."""
    email = pg.unique_email(f"pair-{role}")
    r = client.post(
        "/auth/register",
        json={"email": email, "password": "correct-horse-42", "role": role},
    )
    assert r.status_code == 200
    body = r.json()
    headers = {"Authorization": f"Bearer {body['token']}"}
    return headers, body["user"]["id"], email


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_doctor_pairing_code_round_trip(pg):
    """Doctor JWT → 12-char unambiguous code, stable across repeat calls."""
    headers, user_id, _ = register_and_login(pg, "doctor")
    r = client.get("/auth/pairing-code", headers=headers)
    assert r.status_code == 200
    code = r.json()["pairing_code"]
    assert len(code) == 12
    assert all(ch in CODE_ALPHABET for ch in code)

    again = client.get("/auth/pairing-code", headers=headers)
    assert again.status_code == 200
    assert again.json()["pairing_code"] == code  # mint-once, then stable

    row = pg.query("SELECT pairing_code FROM users WHERE user_id = %s::uuid", (user_id,))
    assert row and row[0][0] == code


def test_pairing_code_requires_doctor_role(pg):
    patient_headers, _, _ = register_and_login(pg, "patient")
    r = client.get("/auth/pairing-code", headers=patient_headers)
    assert r.status_code == 403


def test_pairing_code_requires_bearer(pg):
    for headers in ({}, {"Authorization": "Token abc"}, {"Authorization": "Bearer junk"}):
        r = client.get("/auth/pairing-code", headers=headers)
        assert r.status_code == 401


def test_patient_link_round_trip(pg):
    """Patient + doctor code → doctor_patients row exists in the DB."""
    doc_headers, doc_id, _ = register_and_login(pg, "doctor")
    pat_headers, pat_id, _ = register_and_login(pg, "patient")
    code = client.get("/auth/pairing-code", headers=doc_headers).json()["pairing_code"]

    r = client.post("/auth/link-doctor", json={"code": code}, headers=pat_headers)
    assert r.status_code == 200
    assert r.json()["linked"] is True
    assert r.json()["doctor"]["id"] == doc_id

    rows = pg.query(
        """
        SELECT doctor_id::text, patient_id::text FROM doctor_patients
        WHERE doctor_id = %s::uuid AND patient_id = %s::uuid
        """,
        (doc_id, pat_id),
    )
    assert rows == [(doc_id, pat_id)]


def test_relink_same_doctor_is_noop(pg):
    """Same pair twice → still 200 and still exactly one row."""
    doc_headers, doc_id, _ = register_and_login(pg, "doctor")
    pat_headers, pat_id, _ = register_and_login(pg, "patient")
    code = client.get("/auth/pairing-code", headers=doc_headers).json()["pairing_code"]

    first = client.post("/auth/link-doctor", json={"code": code}, headers=pat_headers)
    second = client.post("/auth/link-doctor", json={"code": code}, headers=pat_headers)
    assert first.status_code == second.status_code == 200

    rows = pg.query(
        """
        SELECT 1 FROM doctor_patients
        WHERE doctor_id = %s::uuid AND patient_id = %s::uuid
        """,
        (doc_id, pat_id),
    )
    assert len(rows) == 1


def test_patient_may_link_multiple_doctors(pg):
    doc_a, doc_a_id, _ = register_and_login(pg, "doctor")
    doc_b, doc_b_id, _ = register_and_login(pg, "doctor")
    pat_headers, pat_id, _ = register_and_login(pg, "patient")

    code_a = client.get("/auth/pairing-code", headers=doc_a).json()["pairing_code"]
    code_b = client.get("/auth/pairing-code", headers=doc_b).json()["pairing_code"]

    assert client.post("/auth/link-doctor", json={"code": code_a}, headers=pat_headers).status_code == 200
    assert client.post("/auth/link-doctor", json={"code": code_b}, headers=pat_headers).status_code == 200

    rows = pg.query(
        "SELECT doctor_id::text FROM doctor_patients WHERE patient_id = %s::uuid",
        (pat_id,),
    )
    assert {row[0] for row in rows} == {doc_a_id, doc_b_id}


def test_link_unknown_code_is_404(pg):
    pat_headers, _, _ = register_and_login(pg, "patient")
    r = client.post(
        "/auth/link-doctor", json={"code": "ZZZZZZZZZZZZ"}, headers=pat_headers
    )
    assert r.status_code == 404
    assert "Unknown pairing code" in r.json()["detail"]


def test_link_non_doctor_code_is_422(pg):
    """A code that resolves to a patient must be refused, not linked."""
    _, _, pat_a_email = register_and_login(pg, "patient")
    pat_b_headers, _, _ = register_and_login(pg, "patient")
    pg.execute(
        "UPDATE users SET pairing_code = %s WHERE lower(email) = lower(%s)",
        ("PATIENTCODE", pat_a_email),
    )
    r = client.post(
        "/auth/link-doctor", json={"code": "PATIENTCODE"}, headers=pat_b_headers
    )
    assert r.status_code == 422


def test_link_requires_patient_role(pg):
    """A doctor calling link-doctor gets 403 — wrong role for the action."""
    doc_headers, _, _ = register_and_login(pg, "doctor")
    r = client.post(
        "/auth/link-doctor", json={"code": "ZZZZZZZZZZZZ"}, headers=doc_headers
    )
    assert r.status_code == 403


def test_link_requires_bearer(pg):
    for headers in ({}, {"Authorization": "Bearer junk"}):
        r = client.post("/auth/link-doctor", json={"code": "ZZZZZZZZZZZZ"}, headers=headers)
        assert r.status_code == 401


def test_seeded_doctor_code_is_generated_lazily(pg):
    """A doctor with NULL pairing_code gets one minted on first GET."""
    login = client.post(
        "/auth/login", json={"email": "doctor@sleep.com", "password": "1234"}
    )
    assert login.status_code == 200
    headers = bearer(login.json()["token"])

    pg.execute(
        "UPDATE users SET pairing_code = NULL WHERE email = %s",
        ("doctor@sleep.com",),
    )
    r = client.get("/auth/pairing-code", headers=headers)
    assert r.status_code == 200
    code = r.json()["pairing_code"]
    assert len(code) == 12
    assert all(ch in CODE_ALPHABET for ch in code)
