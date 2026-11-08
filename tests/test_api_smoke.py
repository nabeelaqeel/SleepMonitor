"""DB-free smoke tests for the auth API.

Deliberately minimal and database-free so CI needs no postgres:

  * imports api.main (proves the whole import chain — config, db, security,
    jose, psycopg2 — resolves together, like the container startup would)
  * exercises GET /auth/health (the liveness probe) and the exactly-one
    401 guard of GET /auth/verify

TestClient is used WITHOUT a context manager, so the FastAPI lifespan
(ensure_setup → Postgres) never runs — plain GETs against routes that don't
touch the DB keep this hermetic.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app

# Module-level on purpose: one app import for the whole test session.
# NOT entered as a context manager — that is what triggers the lifespan.
client = TestClient(app)


def test_health_probe_ok():
    r = client.get("/auth/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "sleep-monitor-api"


def test_verify_requires_bearer_header():
    r = client.get("/auth/verify")
    assert r.status_code == 401
    assert "Bearer" in r.json()["detail"]
