"""Shared bootstrap for DB-backed auth tests.

These tests exercise /auth/register and the pairing flow against the real
(local) Postgres named by DATABASE_URL in .env.development. Postgres is a
dev-only convenience, never a CI dependency: when no candidate DSN answers
the `pg` fixture SKIPS (pytest.skip), so `python -m pytest -q` stays green
in CI (no postgres service) and on any laptop without the stack up.

TestClient is used WITHOUT a context manager (repo convention) so the
lifespan never runs; the `pg` fixture calls api.db.ensure_setup() itself —
which is also what exercises the pairing_code migration path.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest

from api.config import DATABASE_URL

CONNECT_TIMEOUT = 2


def _dsn_candidates() -> list[str]:
    """Configured DSN first, then the same DSN re-hosted onto 127.0.0.1.

    .env.development ships the compose hostname (`postgres`), which only
    resolves inside the docker network — host-venv pytest needs localhost.
    """
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


class Pg:
    """Small handle: ad-hoc SQL plus test-user bookkeeping for cleanup."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        self._tracked_emails: list[str] = []

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
        """A collision-free test address, remembered for teardown deletion."""
        email = f"{prefix}-{uuid.uuid4().hex[:8]}@sleep.test"
        self._tracked_emails.append(email)
        return email

    def cleanup(self) -> None:
        # doctor_patients + pairing codes cascade on the users row.
        for email in self._tracked_emails:
            self.execute(
                "DELETE FROM users WHERE lower(email) = lower(%s)", (email,)
            )


@pytest.fixture(scope="session")
def pg():
    """Reachable-Postgres handle + the idempotent ensure_setup migration.

    Skips (never fails) when neither DSN candidate answers, so a machine
    without the dev stack running still gets a green, fully-skipped run.
    api.db.DATABASE_URL is re-pointed at the reachable DSN for the session
    because ensure_setup (and every endpoint's connection()) read it at
    call time — the shipped value names the in-compose `postgres` host,
    which only resolves inside the docker network.
    """
    dsn = next((d for d in _dsn_candidates() if _reachable(d)), None)
    if dsn is None:
        pytest.skip("local Postgres unreachable — DB-backed auth tests skipped")

    import api.db
    from api.db import ensure_setup
    from api.security import hash_password

    handle = Pg(dsn)
    mp = pytest.MonkeyPatch()
    mp.setattr(api.db, "DATABASE_URL", dsn)
    try:
        ensure_setup(hash_password)
        yield handle
    finally:
        mp.undo()
        handle.cleanup()
