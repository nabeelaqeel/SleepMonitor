"""FastAPI HTTP service — Sleep Monitor authentication + future REST endpoints.

Runs on the host (like the ingest worker — Mosquitto and Postgres are the
only containerised services), so physical devices reach it over the LAN:

    .venv-dev/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000

Endpoints:
    GET  /auth/health         → liveness probe
    POST /auth/login          → {user, token}  |  401 Invalid email or password
    GET  /auth/verify         → Bearer-token claims echo  |  401

Login flow: bcrypt-verify against users.password_hash, then issue a HS256
JWT (12h). The password hash never leaves the server.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from api.db import DEMO_SEEDING_ENABLED, ensure_setup, get_user_by_email
from api.security import (
    create_token,
    decode_token,
    get_dummy_hash,
    hash_password,
    verify_password,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("api.main")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """One-shot startup: ensure the schema / seed users exist, then hold serving until shutdown."""
    ensure_setup(hash_password)
    log.info(
        "Database ready (demo seeding %s)",
        "on" if DEMO_SEEDING_ENABLED else "OFF — SEED_DEMO_USERS=false",
    )
    yield


app = FastAPI(title="Sleep Monitor API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # RN apps don't enforce CORS; enabled for web previews
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    email: str
    password: str


@app.get("/auth/health")
def health():
    """Liveness probe — proves the process answers; opens nothing near the DB."""
    return {"status": "ok", "service": "sleep-monitor-api"}


@app.post("/auth/login")
def login(req: LoginRequest):
    """Verify email+password and return a 12 h JWT plus the non-sensitive user fields. Unknown emails verify against a dummy hash so the 401 path burns the same bcrypt cost for every address."""
    user = get_user_by_email(req.email)
    # Timing-equaliser: unknown emails verify against a dummy hash of an
    # in-memory random value. verify_password runs for BOTH cases (no
    # short-circuit!) so an unknown email burns the same bcrypt cost as a
    # real account — the 401 path no longer leaks which addresses exist.
    stored_hash = user["password_hash"] if user is not None else get_dummy_hash()
    password_ok = verify_password(req.password, stored_hash)
    if user is None or not password_ok:
        # Same message for unknown email and wrong password — no user enumeration
        raise HTTPException(status_code=401, detail="Invalid email or password")

    safe_user = {
        "id": str(user["user_id"]),
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
    }
    return {
        "user": safe_user,
        "token": create_token(safe_user["id"], safe_user["role"]),
    }


@app.get("/auth/verify")
def verify(authorization: str = Header(default="")):
    """Validate a token sent as `Authorization: Bearer <token>`.

    Bearer-token in a header, never a query parameter — URLs are logged by
    proxies and access logs, so credentials must never appear in them.
    """
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authorization: Bearer <token> header required",
        )
    claims = decode_token(authorization[7:].strip())
    if claims is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"sub": claims.get("sub"), "role": claims.get("role")}
