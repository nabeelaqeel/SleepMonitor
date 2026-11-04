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

# Default is for local development only — set JWT_SECRET in .env.development.
JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-secret-change-me")
