"""PostgreSQL access layer for the auth API.

One short-lived connection per operation; the app only logs in twice a
day, so pooling would be overkill. Startup is idempotent — the same
permissive pattern the ingest worker uses:

  * ensure_setup() adds the password_hash column when missing and seeds
    bcrypt hashes for the two demo users, but ONLY when the stored hash
    is empty, so restarts never clobber a password changed later.

The DATABASE_URL comes from .env.development (same as the ingest worker).
"""

from __future__ import annotations

from contextlib import contextmanager

import psycopg2

from api.config import DATABASE_URL, DEMO_SEEDING_ENABLED

# demo credentials are hashed at API startup; SEED_DEMO_USERS=false disables
# this entirely so deployments can provision their own accounts instead.
SEED_USERS = [
    {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "email": "doctor@sleep.com",
        "name": "Dr. Ahmad",
        "role": "doctor",
        "password": "1234",
    },
    {
        "user_id": "00000000-0000-0000-0000-000000000002",
        "email": "patient@sleep.com",
        "name": "Ali Hassan",
        "role": "patient",
        "password": "1234",
    },
]

_USER_COLS = ("user_id", "email", "name", "role", "password_hash")


@contextmanager
def connection():
    """Yield a connection with commit-on-success / rollback-on-error."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_setup(hash_password) -> None:
    """Add password_hash when missing and seed demo users (hash only when empty).

    `hash_password` is injected (security.hash_password) so db.py has no
    dependency on the hashing layer. Demo seeding respects SEED_DEMO_USERS
    (api.config) — schema migration runs regardless.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255) DEFAULT ''
            """
        )
        for user in SEED_USERS if DEMO_SEEDING_ENABLED else []:
            cur.execute(
                "SELECT password_hash FROM users WHERE email = %s",
                (user["email"],),
            )
            row = cur.fetchone()
            if row is None:
                # Fresh install: init sql already seeds these rows, but be
                # safe in case the DB predates the seed volume.
                cur.execute(
                    """
                    INSERT INTO users (user_id, email, name, role, password_hash)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (email) DO NOTHING
                    """,
                    (user["user_id"], user["email"], user["name"],
                     user["role"], hash_password(user["password"])),
                )
                # A concurrent insert may have won; re-read to see if the
                # hash still needs filling.
                cur.execute(
                    "SELECT password_hash FROM users WHERE email = %s",
                    (user["email"],),
                )
                row = cur.fetchone()
            # Fill the hash only when empty — never overwrite a real one.
            if row is not None and not (row[0] or ""):
                cur.execute(
                    "UPDATE users SET password_hash = %s WHERE email = %s",
                    (hash_password(user["password"]), user["email"]),
                )


def get_user_by_email(email: str) -> dict | None:
    """Return the user row (incl. password_hash) or None."""
    email = email.strip().lower()
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {', '.join(_USER_COLS)}
            FROM users
            WHERE email = %s
            """,
            (email,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return dict(zip(_USER_COLS, row))
