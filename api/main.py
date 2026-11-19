"""FastAPI HTTP service — Sleep Monitor authentication + future REST endpoints.

Runs on the host (like the ingest worker — Mosquitto and Postgres are the
only containerised services), so physical devices reach it over the LAN:

    .venv-dev/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000

Endpoints:
    GET  /auth/health         → liveness probe
    POST /auth/login          → {user, token}  |  401 Invalid email or password
    POST /auth/register       → {user, token}  |  409 duplicate email | 422 bad role/password
    POST /auth/google         → {user, token} | {"needs_role": true} | 401 bad token | 503 unconfigured
    GET  /auth/pairing-code   → the doctor's pairing code | 401 | 403
    POST /auth/link-doctor    → patient attaches to a doctor | 401 | 403 | 404 | 422
    GET  /auth/my-doctor      → the caller's linked doctor (or null) | 401
    PATCH /auth/me            → rename self (name only) | 401 | 422
    POST /devices/bind        → patient binds a device (registry) | 401 | 403 | 409 | 422
    GET  /devices             → the patient's bound devices | 401 | 403
    GET  /patients            → the doctor's roster (linked patients + data snapshot) | 401 | 403
    GET  /alerts              → the doctor's alert history | 401 | 403
    GET  /auth/verify         → Bearer-token claims echo  |  401
    GET  /admin/users         → every account (admin) | 401 | 403
    POST /admin/users         → provision any role (admin) | 401 | 403 | 409 | 422
    POST /admin/users/{id}/reset-password → set a password (admin) | 401 | 403 | 404 | 422
    GET  /admin/health        → api + db + broker + last-reading (admin) | 401 | 403
    GET  /admin/qos-sessions  → recent QoS delivery stats (admin) | 401 | 403

Login flow: bcrypt-verify against users.password_hash, then issue a HS256
JWT (12h). The password hash never leaves the server. /auth/google is
config-gated (GOOGLE_CLIENT_ID): unset keeps the LAN demo fully offline.

Roles: patients see their own sleep, doctors their patients, admins the
system itself. Admins are PROVISIONED — self-service endpoints keep the
Literal['doctor','patient'] validation, and /admin/* is the only path that
can mint the admin role (an existing admin is required to call it).
"""

from __future__ import annotations

import logging
import os
import socket
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, StringConstraints

from api import config
from api.db import (
    DEMO_SEEDING_ENABLED,
    bind_device,
    create_user,
    db_health,
    ensure_setup,
    find_user_by_pairing_code,
    get_doctor_of_patient,
    get_or_create_pairing_code,
    get_user_by_email,
    get_user_by_id,
    link_doctor,
    list_devices,
    list_doctor_alerts,
    list_doctor_patients,
    list_recent_qos_sessions,
    list_users,
    update_user_name,
    update_user_password,
)
from api.google_auth import (
    GoogleTokenError,
    GoogleUnavailableError,
    verify_google_token,
)
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


class RegisterRequest(BaseModel):
    email: str
    # < 8 characters fails validation (422) before any handler code runs
    password: str = Field(min_length=8)
    # anything outside doctor|patient fails validation (422) the same way
    role: Literal["doctor", "patient"]


class GoogleAuthRequest(BaseModel):
    id_token: str
    role: Literal["doctor", "patient"] | None = None


class LinkDoctorRequest(BaseModel):
    code: str


class BindDeviceRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=100)
    display_name: str | None = Field(default=None, max_length=100)


class UpdateNameRequest(BaseModel):
    # strip runs before the length check, so "   " is 422 (min_length) and a
    # 300-char padded name is judged on its trimmed form — users.name is
    # VARCHAR(255) NOT NULL, and an empty rename must never reach the DB.
    name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=255, strip_whitespace=True),
    ]


class AdminCreateUserRequest(BaseModel):
    email: str
    # Same strength floor as register — an admin provisions real accounts.
    password: str = Field(min_length=8)
    # Any role, admin included: this guarded endpoint is the ONLY path that
    # can mint an admin (self-service endpoints keep Literal['doctor','patient']).
    role: Literal["patient", "doctor", "admin"]
    # Optional display name; None falls back to the email prefix like register.
    name: Annotated[
        str,
        StringConstraints(min_length=1, max_length=255, strip_whitespace=True),
    ] | None = None


class AdminResetPasswordRequest(BaseModel):
    # Same strength floor as register; 422 fires before the handler runs.
    password: str = Field(min_length=8)


def _safe_user(user: dict) -> dict:
    """Exactly the four non-sensitive fields — password_hash never leaves the server."""
    return {
        "id": str(user["user_id"]),
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
    }


def _session_response(user: dict) -> dict:
    """The {user, token} body shared by login, register and Google sign-in.

    Exactly the four non-sensitive fields — password_hash never leaves the
    server, and the JWT carries the role straight from the users row.
    """
    safe_user = _safe_user(user)
    return {
        "user": safe_user,
        "token": create_token(safe_user["id"], safe_user["role"]),
    }


def _doctor_summary(doctor: dict) -> dict:
    """Exactly the three doctor fields the app renders.

    Shared by POST /auth/link-doctor (link time) and GET /auth/my-doctor
    (every refresh) so the two bodies can never drift apart.
    """
    return {
        "id": str(doctor["user_id"]),
        "email": doctor["email"],
        "name": doctor["name"],
    }


def require_bearer(authorization: str) -> dict:
    """Validate an `Authorization: Bearer <token>` header and return its claims.

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
    return claims


def _require_admin(authorization: str) -> dict:
    """Shared gate for every /admin endpoint — the doctor-gated pattern.

    Admins are system operators, provisioned by seed or by another admin;
    there is no self-service path to this role, so a non-admin bearer gets
    the same 403 any gated endpoint returns.
    """
    claims = require_bearer(authorization)
    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return claims


def _broker_probe() -> dict:
    """TCP-connect to the MQTT broker exactly as the stack configures it.

    Reads MQTT_HOST/MQTT_PORT — the same .env.development keys the compose
    stack and the ingest worker use (config.py already loaded the file).
    The read lives here because only this probe needs it; a 1 s timeout
    keeps the health endpoint fast even against a filtered host.
    """
    host = os.getenv("MQTT_HOST", "localhost")
    raw_port = os.getenv("MQTT_PORT", "1883")
    try:
        port = int(raw_port)
    except ValueError:
        return {"host": host, "port": raw_port, "reachable": False}
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return {"host": host, "port": port, "reachable": True}
    except OSError:
        return {"host": host, "port": port, "reachable": False}


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
    return _session_response(user)


@app.post("/auth/register")
def register(req: RegisterRequest):
    """Create an account with a bcrypt-hashed password and log the user in.

    Registration must reveal duplicate emails (the 409) by design; no
    other property of an address is ever disclosed.
    """
    user = create_user(
        email=req.email,
        name=req.email.split("@", 1)[0],
        role=req.role,
        password_hash=hash_password(req.password),
    )
    if user is None:
        raise HTTPException(status_code=409, detail="Email already registered")
    return _session_response(user)


# Injectable so tests stub token verification and never touch the network.
GoogleVerifier = Callable[[str, str], dict]


def get_google_verifier() -> GoogleVerifier:
    """Return the real ID-token verifier; dependency overrides replace it in tests."""
    return verify_google_token


@app.post("/auth/google")
def google_login(
    req: GoogleAuthRequest,
    # Annotated keeps the Depends call out of a default argument (B008).
    verifier: Annotated[GoogleVerifier, Depends(get_google_verifier)],
):
    """Sign in (or first-time sign up) with a Google ID token.

    GOOGLE_CLIENT_ID unset → 503: the local LAN demo must never depend on
    Google being reachable. Known emails log in exactly like /auth/login
    (any supplied role is ignored — the DB row wins); unknown emails are
    created when a role is supplied, otherwise the app gets needs_role and
    re-posts with one.
    """
    client_id = config.GOOGLE_CLIENT_ID
    if not client_id:
        raise HTTPException(
            status_code=503,
            detail="Google sign-in is not configured on this deployment "
                   "(GOOGLE_CLIENT_ID unset); use email and password.",
        )
    try:
        claims = verifier(req.id_token, client_id)
    except GoogleTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired Google token")
    except GoogleUnavailableError:
        raise HTTPException(
            status_code=503,
            detail="Google's token-verification endpoint is unreachable; try again shortly",
        )
    user = get_user_by_email(claims["email"])
    if user is None:
        if req.role is None:
            return {"needs_role": True}
        user = create_user(
            email=claims["email"],
            name=claims.get("name") or claims["email"].split("@", 1)[0],
            role=req.role,
            # Google accounts have no local password — empty hash can never verify.
            password_hash="",
        )
        if user is None:
            # Email appeared between the lookup and the insert.
            raise HTTPException(status_code=409, detail="Email already registered")
    return _session_response(user)


@app.get("/auth/pairing-code")
def pairing_code(authorization: str = Header(default="")):
    """Return the doctor's pairing code, minting one on first use."""
    claims = require_bearer(authorization)
    if claims.get("role") != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors have pairing codes")
    code = get_or_create_pairing_code(str(claims["sub"]))
    if code is None:
        # Valid signature but the user row is gone — the token is no longer usable.
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"pairing_code": code}


@app.post("/auth/link-doctor")
def link_to_doctor(req: LinkDoctorRequest, authorization: str = Header(default="")):
    """Attach the calling patient to the doctor owning `code` (idempotent).

    A patient may attach to several doctors; attaching to the same doctor
    twice is a no-op, never an error.
    """
    claims = require_bearer(authorization)
    if claims.get("role") != "patient":
        raise HTTPException(status_code=403, detail="Only patients link to a doctor")
    doctor = find_user_by_pairing_code(req.code)
    if doctor is None:
        raise HTTPException(status_code=404, detail="Unknown pairing code")
    if doctor["role"] != "doctor":
        raise HTTPException(status_code=422, detail="That pairing code does not belong to a doctor")
    link_doctor(str(claims["sub"]), str(doctor["user_id"]))
    return {"linked": True, "doctor": _doctor_summary(doctor)}


@app.get("/auth/my-doctor")
def my_doctor(authorization: str = Header(default="")):
    """The caller's linked doctor, re-read fresh on every call.

    Role-agnostic — a doctor caller has no linked doctor and gets
    {doctor: null}. The doctor's CURRENT name comes back, never a
    link-time snapshot, so renames surface on the next refresh.
    """
    claims = require_bearer(authorization)
    if get_user_by_id(str(claims["sub"])) is None:
        # Valid signature but the user row is gone — the token is no longer usable.
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    doctor = get_doctor_of_patient(str(claims["sub"]))
    return {"doctor": _doctor_summary(doctor) if doctor else None}


@app.patch("/auth/me")
def update_my_name(req: UpdateNameRequest, authorization: str = Header(default="")):
    """Rename the caller; id, email and role are immutable through this path.

    No token reissue — the JWT carries only sub+role, and neither claim
    changes with a rename.
    """
    claims = require_bearer(authorization)
    user = update_user_name(str(claims["sub"]), req.name)
    if user is None:
        # Valid signature but the user row is gone — the token is no longer usable.
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"user": _safe_user(user)}


@app.post("/devices/bind")
def bind_my_device(req: BindDeviceRequest, authorization: str = Header(default="")):
    """Insert (or rename) the calling patient's registry row for a device.

    The ingest worker resolves sessions by deviceId against this row, so
    N watches attribute their data to the right patient. Binding a device
    owned by another patient is refused — no hijacking.
    """
    claims = require_bearer(authorization)
    if claims.get("role") != "patient":
        raise HTTPException(status_code=403, detail="Only patients bind devices")
    row = bind_device(str(claims["sub"]), req.device_id, req.display_name)
    if row is None:
        raise HTTPException(status_code=409, detail="Device is already bound to another patient")
    return {"device": row}


@app.get("/devices")
def list_my_devices(authorization: str = Header(default="")):
    """List the devices bound to the calling patient."""
    claims = require_bearer(authorization)
    if claims.get("role") != "patient":
        raise HTTPException(status_code=403, detail="Only patients list their devices")
    return {"devices": list_devices(str(claims["sub"]))}


@app.get("/patients")
def patients_roster(authorization: str = Header(default="")):
    """The calling doctor's linked patients with their device/data snapshot.

    Roster completeness matters more than activity: a freshly paired
    patient with no devices and no readings still appears (nulls).
    """
    claims = require_bearer(authorization)
    if claims.get("role") != "doctor":
        raise HTTPException(status_code=403, detail="Only doctors list their patients")
    return {"patients": list_doctor_patients(str(claims["sub"]))}


@app.get("/alerts")
def alerts_history(authorization: str = Header(default="")):
    """The calling doctor's alert history across linked patients, newest first.

    Hard cap of 50 alerts — a recent-events feed, not an archive
    (docs/DATABASE.md: only Critical/Important events are ever stored).
    """
    claims = require_bearer(authorization)
    if claims.get("role") != "doctor":
        raise HTTPException(
            status_code=403,
            detail="Only doctors list their patients' alerts",
        )
    return {"alerts": list_doctor_alerts(str(claims["sub"]))}


@app.get("/auth/verify")
def verify(authorization: str = Header(default="")):
    """Validate a token sent as `Authorization: Bearer <token>`."""
    claims = require_bearer(authorization)
    return {"sub": claims.get("sub"), "role": claims.get("role")}


# ── Admin — the system-operator role ───────────────────────────
# patient = my sleep, doctor = my patients, admin = the system itself.
# Every endpoint below is gated by _require_admin; none ever returns a
# password hash.

@app.get("/admin/users")
def admin_list_users(authorization: str = Header(default="")):
    """Every account, oldest first — the operator's directory view.

    Exactly id/email/name/role/created_at; password_hash is never selected
    in list_users, so it cannot leak into a response shape by accident.
    """
    _require_admin(authorization)
    return {"users": list_users()}


@app.post("/admin/users")
def admin_create_user(
    req: AdminCreateUserRequest, authorization: str = Header(default="")
):
    """Provision an account with any role — the sole source of new admins.

    Validation and duplicate handling mirror /auth/register exactly
    (bcrypt hash, lowercase email, 409 on a taken address); the created
    account logs in like any other. No token is returned here — the
    provisioned user signs in themselves.
    """
    _require_admin(authorization)
    user = create_user(
        email=req.email,
        name=req.name or req.email.split("@", 1)[0],
        role=req.role,
        password_hash=hash_password(req.password),
    )
    if user is None:
        raise HTTPException(status_code=409, detail="Email already registered")
    return {"user": _safe_user(user)}


@app.post("/admin/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: str, req: AdminResetPasswordRequest,
    authorization: str = Header(default=""),
):
    """Set a new password for any account; the old one stops verifying.

    Strength rules match register (min_length=8 → 422 before the handler).
    No token reissue needed — the JWT carries only sub+role, neither of
    which a password reset changes.
    """
    _require_admin(authorization)
    try:
        UUID(user_id)
    except ValueError:
        # Malformed path id — psycopg2 would raise on the uuid cast (500);
        # report it as simply unknown instead.
        raise HTTPException(status_code=404, detail="Unknown user")
    user = update_user_password(user_id, hash_password(req.password))
    if user is None:
        raise HTTPException(status_code=404, detail="Unknown user")
    return {"user": _safe_user(user)}


@app.get("/admin/health")
def admin_health(authorization: str = Header(default="")):
    """System view: API liveness, DB reachability + newest reading, broker.

    Always answers 200 and describes each component — a health endpoint
    must report failures, not raise them. `status` is "ok" only when both
    the database and the broker answer; `database.last_data_received`
    (newest readings row) is the ingest-liveness proxy, null while the
    pipeline has never persisted a reading.
    """
    _require_admin(authorization)
    database = db_health()
    broker = _broker_probe()
    return {
        "status": "ok" if database["reachable"] and broker["reachable"]
        else "degraded",
        "api": {"status": "ok"},
        "database": database,
        "broker": broker,
    }


@app.get("/admin/qos-sessions")
def admin_qos_sessions(authorization: str = Header(default="")):
    """Recent QoS delivery accounting (session_stats), newest computed first.

    Cap of 20 — a pipeline-health view over the ingest worker's accounting,
    not an archive. delivery_pct is null for an empty session (nothing was
    expected, so no meaningful ratio).
    """
    _require_admin(authorization)
    return {"sessions": list_recent_qos_sessions()}
