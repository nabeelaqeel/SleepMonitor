# Auth API (Login) Setup Guide

How the Expo app's login screen talks to PostgreSQL. This replaces the
client-side `mockAuth.js` (hardcoded credentials) with a real HTTP service
that bcrypt-verifies passwords and issues short-lived JWTs.

> **Quick runbook:** the README's [Run the Full Stack](../README.md#run-the-full-stack)
> section has the terminal-by-terminal version (the API is Terminal 3).
> Database schema details live in [`DATABASE.md`](DATABASE.md#users--login).

**Last updated:** 2026-11-04
**Branch:** `feature/db-backed-login`

---

## System Overview

```
Expo app (app/auth/apiAuth.js)
      │  POST /auth/login {email, password}
      ▼
FastAPI  (api/main.py, host venv, :8000)
      │  bcrypt.checkpw(password, users.password_hash)
      ▼
PostgreSQL :5432  (sleep_monitor.users)
```

The password is sent once per login as a JSON body; it is **never persisted**
— not in the database anyway (only the bcrypt hash is stored) and not by the
app — and the hash never leaves the server. On success the client gets the
user object plus a **12-hour HS256 JWT** stored in encrypted native storage.
One precise exception to keep in mind: the *demo* password is also a
plaintext literal in the server-side seed list (`api/db.py`, `SEED_USERS`),
hashed on first startup; everything else acts on it only through bcrypt.

| File | Responsibility |
|---|---|
| `api/main.py` | FastAPI app — endpoints, CORS, lifespan setup |
| `api/db.py` | `users` access layer, idempotent column-add + demo-user seeding |
| `api/security.py` | bcrypt hash/verify, JWT create/decode |
| `api/config.py` | Loads `.env.development` first; exposes `DATABASE_URL`, `JWT_SECRET` (enforced: ≥ 32 chars, no 'change_me' placeholders), `SEED_DEMO_USERS` |

---

## Quick Start

```bash
# 1. Python deps in the existing host venv (.venv-dev is already gitignored)
.venv-dev/bin/pip install -r api/requirements.txt

# 2. JWT secret — >= 32 chars and not a placeholder, or the API refuses to
#    start. Idempotent: replaces a placeholder in place, appends only when
#    the variable is missing, and NEVER overwrites an operator secret —
#    safe to re-run.
if grep -q 'change_me' .env.development; then
  V=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  sed -i "s|^JWT_SECRET=.*|JWT_SECRET=${V}|" .env.development
elif ! grep -q '^JWT_SECRET=' .env.development; then
  echo "JWT_SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> .env.development
fi

# 3. Postgres must be up first (credentials are verified against it)
docker compose --env-file .env.development up -d

# 4. Run the API — from the repository root, bound to the LAN
.venv-dev/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
```

On startup the lifespan hook calls `ensure_setup()`: it adds the
`password_hash` column when missing (`ADD COLUMN IF NOT EXISTS`) and seeds
bcrypt hashes for the demo users — **only when the stored hash is still
empty**. Demo seeding is controlled by `SEED_DEMO_USERS` in
`.env.development` (default `true`; set `false` beyond the demo deployment
and provision accounts separately). Three consequences:

* The API must start **at least once** before anyone can log into a fresh
  database (SQL init intentionally stores no plaintext passwords).
* Restarting the API never resets a password changed later.
* `SEED_DEMO_USERS=false` skips demo account creation entirely — schema
  migration still runs.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/auth/health` | Liveness probe |
| POST | `/auth/login` | Verify credentials, `{user, token}` or 401 |
| GET | `/auth/verify` (Authorization: Bearer) | Decode/validate a JWT (claims echo or 401) |

### `POST /auth/login`

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"patient@sleep.com","password":"1234"}'
```

Success (200):

```json
{"user":{"id":"00000000-0000-0000-0000-000000000002",
         "email":"patient@sleep.com","name":"Ali Hassan","role":"patient"},
 "token":"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwMDIiLCJyb2xlIjoicGF0aWVudCIs…"}
```

Bad password (401): `{"detail":"Invalid email or password"}` — the same
message is returned for an unknown email, so the endpoint does not leak
which accounts exist.

### Seeded accounts (in `users`, not in any client code)

| Email | Password | Role | user_id |
|---|---|---|---|
| `doctor@sleep.com` | `1234` | doctor | `00000000-0000-0000-0000-000000000001` |
| `patient@sleep.com` | `1234` | patient | `00000000-0000-0000-0000-000000000002` |

---

## JWT Design

| Claim | Meaning |
|---|---|
| `sub` | the user UUID |
| `role` | `doctor` or `patient` (mirrors `App.js` routing) |
| `iat` | issued-at (UTC) |
| `exp` | issued-at + 12h — re-login required after expiry |

Symmetric **HS256 (HMAC-SHA256)** with the shared `JWT_SECRET`. The payload is
Base64URL — readable by anyone (it contains no secrets) but **tamper-proof**:
`GET /auth/verify` with `Authorization: Bearer <token>` returns 401 for
changed or expired tokens — tokens in URLs would land in proxy and access
logs, so the header form is required. HS256 is
authentication, not confidentiality; see the security section below for what
that means end-to-end.

---

## App Side

| Piece | Detail |
|---|---|
| `app/auth/apiAuth.js` | `login()` POSTs `/auth/login` (plain HTTP refused for non-LAN hosts); resolves with the DB user, `null` on 401, throws on network/server errors so the screen shows a distinct message. `getStoredUser()` restores a session only when the stored JWT is present **and unexpired** (client-side `exp` check); anything stale is cleared |
| `app/.env.development` | `EXPO_PUBLIC_API_URL=http://<LAN-IP>:8000` — same Metro inlining rules as `EXPO_PUBLIC_BROKER_IP`, so **restart `npx expo start`** after changing it |
| User storage / token storage | User object (`current_user`, AsyncStorage — non-sensitive). JWT (`auth_token`, `expo-secure-store` → iOS Keychain / Android Keystore; AsyncStorage fallback on web, where SecureStore has no build) |
| `logout()` | Clears the AsyncStorage user and deletes the secure-store token |

`App.js` only changed its import; the user shape `{id, email, name, role}` is
what mockAuth stored, so role-based navigation and all screens are untouched.

---

## Security: Encryption & Hashing

| Data | Protected by | Algorithm | Where |
|---|---|---|---|
| **Password (at rest)** | One-way **hash** — not encryption; never reversible | **bcrypt** — 60-char `$2b$12$` format: `2b` = algorithm version, `12` = cost factor (2¹² = 4,096 rounds), 16-byte random salt generated per user and embedded in the hash | `users.password_hash` |
| **JWT (transit)** | **Signed** so it cannot be forged (signed, not encrypted — payload is readable, tampering is impossible) | **HS256** = HMAC-SHA256, secret from `JWT_SECRET`, 12h expiry | Auth response header/body |
| **Login exchange (transit)** | bcrypt verify happens server-side; the hash never leaves the server. The app sends the plaintext password once per login and **refuses plain HTTP to non-LAN hosts** (`assertSecureEndpoint` in `apiAuth.js`) — HTTPS hostnames are validated by the RN networking stack's certificate checks | (plain HTTP only to loopback/LAN hosts — dev) | app ↔ `:8000` |

### What is intentionally NOT encrypted

| Data | Why it is plain | Deployment TODO |
|---|---|---|
| HTTP app ↔ API on the LAN | Dev/demo transport; the app already blocks plain HTTP to public hosts | TLS — reverse proxy or `uvicorn --ssl-keyfile/--ssl-certfile` |
| MQTT `sleep/#` traffic | Pre-existing project scope, unchanged by this work | Mosquitto TLS listener |
| Readings/alerts at rest | Demo scope (single-user FYP) | Disk/volume encryption (managed by RDS in production) |
| JWT on the phone — `expo-secure-store` (Keychain/Keystore); AsyncStorage fallback is web-only (no native secure store in browsers) | User object in AsyncStorage is non-sensitive (`id/email/name/role`) | Move the session user into SecureStore too for production parity |

Summary claims: **passwords are bcrypt-hashed (cost 12, per-user salts) in
`users.password_hash`,** and **sessions are HS256-signed 12-hour JWTs kept in
device secure storage.** The hash never crosses the network; no plaintext
password is ever persisted — in the database, the app, or storage caches.
The only plaintext copy of the demo password anywhere in the repository is
the server-side seed literal in `api/db.py`, which exists so the demo
database can bootstrap itself and is converted to a bcrypt hash at startup.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| App shows *"Cannot reach the login server (http://…:8000).*" | API not running, or `EXPO_PUBLIC_API_URL` points at the wrong LAN IP; check `curl http://localhost:8000/auth/health` then the phone's view `http://<LAN-IP>:8000/auth/health` |
| API exits at startup: *"password authentication failed for user sleep_user"* | Wrong `DATABASE_URL` in `.env.development`, or Postgres container not up |
| Always 401 despite correct password | Demo hashes not seeded (hash column empty) — restart the API once so `ensure_setup()` fills them; or the volume predates the column (the live DB was migrated with `ALTER TABLE … ADD COLUMN IF NOT EXISTS`) |
| 401 after 12h | JWT expired by design — log in again |
| Login works on Web but not on a physical device | `EXPO_PUBLIC_API_URL` must be the host's LAN IP (`hostname -I`), not `localhost`; phone and host must share the network (same as the broker) |
| Env change not picked up | Expo inlines `EXPO_PUBLIC_*` at bundle time — restart Metro |

---

## Known Limitations / Next Steps

* **Demo password strength.** `1234` stays for the demo. Before real use,
  create a bcrypt hash and write it to `users.password_hash` — the column
  holds only hashes, never plaintext:

  ```bash
  # hash the new password…
  .venv-dev/bin/python -c "import bcrypt; print(bcrypt.hashpw(b'NEW_PASSWORD', bcrypt.gensalt()).decode())"
  # …then update the stored hash (safe while the API runs — seeding only
  # touches empty hashes).
  docker exec sleep-postgres psql -U sleep_user -d sleep_monitor \
    -c "UPDATE users SET password_hash = '<hash-from-above>' WHERE email = 'patient@sleep.com';"
  ```
* **No release endpoint.** App does not embed an API URL for release builds:
  `EXPO_PUBLIC_API_URL` must be pointed at a provisioned **HTTPS** endpoint
  before a store build ships. None exists yet, so none is invented here —
  `app.json` deliberately sets no `usesCleartextTraffic` (cleartext stays
  limited to dev via Expo Go / the LAN-HTTP exception in
  `assertSecureEndpoint`).
* **No login rate limiting.** Per-account and per-source-IP throttling was
  deliberately not added — no established throttling mechanism exists in
  this codebase yet, and the audience is one user on a private LAN.
  `slowapi` (or an nginx `limit_req`) is the natural next step.
* **Symmetric secret-only auth.** HS256 keeps the same secret on server(s);
  RS256/ES256 (asymmetric) suits multi-service deployments — plausible
  post-thesis work, not needed for one API.
* **No account endpoints.** Registration, password change and refresh tokens
  are out of scope for a single-user system (one doctor, one patient by design).
