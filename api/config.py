"""Shared config for the auth API.

Loads .env.development on import and exposes the DSN + JWT secret — import
order safe, so every module that needs these values just imports from here.

WORKDIR NOTE: uvicorn must be started from the repository root so the
relative .env.development path resolves (same as the ingest worker).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv(".env.development")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://sleep_user:changeme@localhost:5432/sleep_monitor",
)

# Tokens are signed with this secret — a committed fallback would let anyone
# forge valid JWTs, so startup refuses missing or weak values instead.
JWT_SECRET = os.getenv("JWT_SECRET", "").strip()
if len(JWT_SECRET) < 32:
    raise RuntimeError(
        "JWT_SECRET is missing or too weak (needs >= 32 characters). "
        'Generate one with: python3 -c "import secrets; print(secrets.token_hex(32));" '
        "and write the value to .env.development"
    )

# Demo account seeding can be turned off for anything beyond the demo
# deployment (set SEED_DEMO_USERS=false); production users should be
# provisioned separately with a hash from api.security.hash_password.
DEMO_SEEDING_ENABLED = os.getenv("SEED_DEMO_USERS", "true").strip().lower() in (
    "1", "true", "yes",
)
