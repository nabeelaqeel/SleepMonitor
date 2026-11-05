# Deployment Notes — The Why

Every decision behind [`DEPLOYMENT.md`](DEPLOYMENT.md) lives here. The runbook tells you what to run; this tells you why, and what to change if you decide differently.

---

## 1. Why the APK is built last

There are **two separate artifacts**, and only one of them is rebuilt freely:

| Artifact | Where it runs | Built from | Update cost |
|---|---|---|---|
| Backend stack | EC2 (Learner Lab) | repo, runs directly | `git pull` + restart — **minutes** |
| App APK | phones (sideloaded) | repo via EAS — `EXPO_PUBLIC_*` **baked in at build time** | full EAS build — **~15–25 min** |

Expo inlines `EXPO_PUBLIC_*` variables into the JS bundle at build time. An APK built before the EC2 IP is known points at your laptop's LAN IP forever. Hence the fixed order: **server up → verify → (Expo Go rehearsal) → build once.**

```
Phase 1  EC2 backend ──► verify curl + mosquitto_sub ──► Expo Go rehearsal
        │
        ▼
Phase 2  eas build ──► endpoints now final ──► sideload
        │
        ▼
phase 3 operate (runbook §5) + ship changes (runbook §6)
```

---

## 2. AWS Learner Lab constraints (and what they force)

| Constraint | Consequence | What the runbook does about it |
|---|---|---|
| Starter budget ≈ $50, no top-ups | Everything bills against it | t3.micro ≈ $0.02/hr; a demo month costs single-digit dollars when you stop after sessions |
| Region fixed at lab start (usually `us-east-1`) | No choice; one region for everything | — |
| EC2 **stops at session end**; storage persists | Images, volumes, code survive; services don't auto-start unless configured | `restart: unless-stopped` on containers + `systemctl enable` on units **is the persistence mechanism** (runbook §2.10/2.12) |
| Public IPv4 changes on restart | Baked APK endpoints break | Elastic IP — see §5 |
| IAM locked to `LabRole`, no load balancers | No ALB/NLB/custom roles | Unneeded: one EC2, everything behind the SG |
| Supported: EC2, S3, RDS, … (subset) | Both needed services fit: RDS (db.t3.micro-class, single-AZ) for Postgres, Docker-on-EC2 for the broker. Core caveat: an RDS instance **cannot be stopped** — it bills continuously while alive, which is why the lifecycle is create-per-session/delete-per-session (see §5 and the runbook §5) |

Cost sketch (runbook §5 repeats the checklist):

| Item | ≈ Cost |
|---|---|
| t3.micro running 8h/day × 20 days | $3–4 |
| EBS 30 GB gp3 (persistent) | $2–3/mo |
| RDS db.t3.micro — created + deleted per session | ≈ $0.10–0.20/session; **"delete without final snapshot" is what keeps this true** — a retained snapshot is a separate bill |
| **Elastic IP attached** (bills even while instance is stopped) | **≈ $3.6/mo — an additional drain on top of the EBS row, which also keeps billing while stopped** |

---

## 3. What Phase 0 created — each piece and its reason

All of this **ships in the repo**; nothing here happens again per deployment.

| File | Why |
|---|---|
| `docker-compose.aws.yml` | The laptop compose is Postgres-only by design — Mosquitto runs natively there, a second broker would port-clash. The server can't rely on a native broker (system state you'd reinstall every long break), so the broker stays containerized. **Postgres left the server compose**: the database is AWS RDS with storage encryption — see the RDS row below and §9. |
| RDS (PostgreSQL, per-session) | Encrypted at rest, TLS connections (`sslmode=require`), private in the default VPC behind `sm-rds-sg` — inbound 5432 sourced from the EC2's security group only. **Same identifier on every recreation keeps the endpoint string constant**, so the app/env never re-points. Encrypted-at-rest is the *doctor-facing artifact* (§9 statement). The per-session cycle (create → demo → delete without final snapshot) keeps RDS off the idle bill list. |
| `./mosquitto:/mosquitto/config` (read-write dir mount) | `mosquitto_passwd` writes `mosquitto/passwd` from inside the container; a read-only file mount would block that, and a container-only path wouldn't survive recreates. |
| `mosquitto/mosquitto.conf` (locked) | The broker is reachable from the whole internet on 1883/9001. With anonymous access, anyone scanning the IP can **inject fake patient vitals**. `allow_anonymous false` + `password_file` closes it. The passwd file itself is generated on the server (runbook §2.9) and **never committed** (gitignored). |
| Passwd *before* first start | Mosquitto refuses to boot when its `password_file` is missing — that's why runbook step 2.7 exists before the compose `up`. |
| `app/eas.json` (gitignored) + `app/eas.example.json` (tracked) | `preview` profile builds an **installable APK** (`buildType: apk`), not a Play-Store AAB, and carries the five `EXPO_PUBLIC_*` values the app bakes. **`eas.json` is gitignored** — the tracked `eas.example.json` template carries placeholders; real endpoints + broker password are filled locally at runbook §4.2, so the repo never holds them. EAS cloud builds read profile env from the working tree, not from git. **Production profile diverges deliberately**: it drops `EXPO_PUBLIC_ALLOW_PLAIN_HTTP` (HTTPS `API_URL` placeholder stays) and carries **no MQTT credentials at all** — any non-demo (store) build fails closed without TLS instead of shipping demo relaxations or broker secrets. The database is **AWS RDS** with **storage encryption at rest** and TLS connections (`sslmode=require`) — see §9 for the encryption inventory and the doctor-facing statement. |
| `app/app.config.js` | Fail-guard: EAS cloud builds **throw** while `EXPO_PUBLIC_BROKER_IP`/`EXPO_PUBLIC_API_URL` are unset or still `SET_ME…` — an unfilled `eas.json` can no longer silently produce an APK with dead endpoints (the app would fall back to legacy hardcoded IPs). Local `npx expo start` is unaffected (no `EAS_BUILD` env set there). |
| MQTT creds & endpoints inside `eas.json` (local + gitignored; template `eas.example.json` tracks placeholders) | The APK embeds these strings anyway (phone-side credential), so they live beside the endpoints in one local file, filled at runbook §4.2 and rotated via §6. Repo-visible upgrade path: move them to EAS environment variables (`npx eas-cli env:create`) once supporting that is worth it. |
| `app.json` package fix (`com.aqeel.sleepmonitor`) | The Android package name is the app's identity — changing it after the first installed APK makes every future build a *different app* on the phone. Fixed before any build could run. |
| `mqttService.js` credentials | `doConnect()` now passes `userName`/`password` from `EXPO_PUBLIC_MQTT_*`. With `undefined` fallback so **anonymous brokers keep working** — your laptop's native broker ignores credentials anyway. |
| Credential parity (all consumers same user `sm`) | `publisher.py` defaults to `admin`/`changeme` when env is missing; ingest and echo default to empty. Explicit `MQTT_USER`/`MQTT_PASSWORD` in `.env.development` makes all three connect to the locked broker the same way. |
| `expo-updates` package | Enables OTA pushes for later JS-only fixes (§7) — added before the first APK so adopting it costs zero rebuilds. |

---

## 4. The `.env.development` naming gotcha

Every Python service loads `.env.development` **by literal name**:

- `api/config.py` — `load_dotenv(".env.development")`
- `ingest/worker.py` — same
- `publisher/*` — same

That filename is hardcoded, so the server's "production" values also live in a file *called* `.env.development` (runbook §2.7). It stays gitignored both places — the name is just the runtime's convention, not a claim about environment.

Two values the API actively guards: `JWT_SECRET` is **rejected at startup** if it's under 32 chars or still a `.env.example` placeholder (`change_me…`) — so a copied template can never become a live signing key. That's why runbook §2.7 generates one with `secrets.token_hex(32)`.

App values are separate by design — `app/.env.development` (Expo only reads env files in its own project root) holds the `EXPO_PUBLIC_*` copies used by the *local* `expo start` loop.

---

## 5. Session lifecycle & the Elastic IP

What happens at each lab end/start, mechanically:

1. **Lab ends** → EC2 stops (EBS keeps: Docker images, the venv, your code, the systemd units, mosquitto data). **RDS is deleted by you first** (runbook §5) — that's the lifecycle: endpoint stays constant on the next recreation (same identifier) and no snapshot carries a bill.
2. **Next lab starts** → you create the RDS instance (runbook §2.5/§5, ~5–10 min) *and* start the EC2 — both finish around the same minute. Containers come back (`restart: unless-stopped`), systemd services come back (`enable --now` set in runbook §2.12); the fresh DB gets `01_schema.sql` the once (`psql -f`). SSH in and confirm per runbook §5.
3. **The IP**: a public IPv4 is reassigned *randomly* per boot.

Options for step 3:

| Option | Effort | Effect |
|---|---|---|
| **Elastic IP (recommended)** | 2 min: EC2 → Elastic IPs → Allocate → Associate | Address survives stop/start. The APK stays valid forever. Bills ≈ $3.6/mo while stopped — an additional drain on top of EBS storage. Release it if you'll be inactive for a long stretch and accept one rebuild later. |
| No EIP | zero | Every session you must re-bake `<EC2_IP>` and rebuild (`npx eas-cli build`, ~20 min) — or wait for an OTA push (§7). Workable, painful. |

---

## 6. Rotating credentials

The broker credential lives in exactly four places:

1. `mosquitto/passwd` — generated on the server (runbook §2.9); **read by the broker at startup only**
2. server `.env.development` — `MQTT_USER`/`MQTT_PASSWORD` (§2.7, generated there, never committed)
3. laptop `app/eas.json` — `EXPO_PUBLIC_MQTT_*` (gitignored; template `eas.example.json`; baked into the APK at build time)
4. laptop copies — root `.env.development` + `app/.env.development` (local development only)

Rotation is an ordered sequence — **restarts are required, a rebuild usually is not**:

```bash
# 1. server: new password → passwd file, env file stays consistent with it
#    (run value through BOTH so nothing can mix credentials)
#    in /opt/SleepMonitor:
NEWPW=$(openssl rand -hex 12)
docker run --rm -u 1883 -v "$PWD/mosquitto:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -b /mosquitto/config/passwd sm "$NEWPW" || exit 1   # batch mode + add-or-update; aborts on failure
sed -i "s/^MQTT_PASSWORD=.*/MQTT_PASSWORD=$NEWPW/" .env.development

# 2. server: broker reload — password_file is only read at startup
docker compose -f docker-compose.aws.yml restart broker

# 3. server: the four Python units hold long-lived paho connections with the
#    OLD password — they must be restarted to re-read .env.development:
sudo systemctl restart sm-api sm-ingest sm-pub sm-echo
systemctl is-active sm-api sm-ingest sm-pub sm-echo        # 4× active

# 4. laptop (from the repo ROOT): rotate BOTH sources of EXPO_PUBLIC_* —
#    eas.json feeds future BUILDS; app/.env.local feeds OTA publishes
#    (SDK 54 `eas update` reads local .env, NOT the eas.json profile env)
cd app
sed -i 's/^EXPO_PUBLIC_MQTT_PASSWORD.*/EXPO_PUBLIC_MQTT_PASSWORD=<new password>/' eas.json
# .env.local presence-aware edit: replace when present, append when the key
# or even the file itself is missing (bare `sed || echo` silently succeeds
# when the file exists without the key)
grep -q '^EXPO_PUBLIC_MQTT_PASSWORD=' .env.local 2>/dev/null \
  && sed -i 's/^EXPO_PUBLIC_MQTT_PASSWORD=.*/EXPO_PUBLIC_MQTT_PASSWORD=<new password>/' .env.local \
  || echo 'EXPO_PUBLIC_MQTT_PASSWORD=<new password>' >> .env.local
npx eas-cli update --branch preview --message "rotate MQTT credential"
# scope: preview installs ONLY — production (store) builds carry no broker
# credentials by design (§3), so this procedure deliberately doesn't target them

# 5. laptop copies (4) — at leisure, they are local-only
```

If the password was ever deployed AND the repo is public, treat it as burned and run this sequence once immediately (the pre-deploy value inevitably leaked into the source history otherwise).

---

## 7. OTA — what EAS Update can and cannot push

With `expo-updates` wired (it is — Phase 0) and the `preview` channel APK installed:

| Change | OTA-able? | Notes |
|---|---|---|
| App JS code (screens, logic) | ✅ | The main use: `npx eas-cli update --branch preview` (runbook §6.3) |
| `EXPO_PUBLIC_*` **values** | ✅ for preview installs | Source rule (SDK 54): `eas update` publishes read envs from **local `.env` files** (`app/.env.local` — §4.2 seeds it) — NOT the `eas.json` profile `env` block (that only feeds `eas build`). An IP/credential change ships via OTA only if `.env.local` rotates with it. On SDK 55+ the route is EAS env vars + `eas update --environment <name>`. **Rotation publishes to preview installs only** — production (store) builds are credential-free by design (§3), so production OTA rotation is a TLS-era §8 concern. EIP still preferred: the APK works offline of EAS, no dependency. |
| `app.json` (package name, plugins), icons/splash | ❌ | Native — full `eas build` |
| New native dependency | ❌ | Full `eas build` |
| Python/backend | n/a | Never goes through the APK — §6.1 |

**Version rule:** `runtimeVersion: { policy: "appVersion" }` is configured — OTA pushes land on every install whose `app.json` **version string is unchanged** (currently `1.0.0`). Bump the version and old installs stop receiving updates until they're rebuilt/reinstalled — which is the right moment for a build anyway.

**Branch rule:** `eas update --branch preview` ↔ `"channel": "preview"` on the `preview` profile (`eas update:configure` set this in Phase 0). Publishing to the wrong branch silently reaches no one.

---

## 8. Transport security — where the demo sits

The review's HTTPS finding is half-mitigated already: `assertSecureEndpoint()` in `app/auth/apiAuth.js` is **default-deny** — it refuses plain-HTTP credentials to any public host — and only relaxes when the deployment explicitly sets `EXPO_PUBLIC_ALLOW_PLAIN_HTTP=true` (baked into the **preview profile only** at §4.2 — production dropped the flag, so store-profile builds fail closed at config/login time). That flag is the documented demo tradeoff: README's Known Limitations already lists "rotate demo password + TLS before a real deployment."

MQTT stays plain on 1883/9001 with broker credentials. TLS on 9001 (WSS, `useSSL: true`) needs a cert the phone trusts — a self-signed cert breaks React Native's WebSocket trust handling, a real cert needs DNS + ports 80/443; both out of scope for the lab demo, tracked as Known Limitations.

Upgrade path once a cert exists: nginx/Let's Encrypt → `EXPO_PUBLIC_API_URL` becomes `https://…` (the guard accepts it as-is, the flag becomes unnecessary), broker listeners gain `certfile`/`keyfile`, app flips `useSSL: true`. Small code deltas then.

Post-verification tightening (no TLS required): port 1883 exists mostly for the §3.2 laptop check — narrow that SG rule's source to your IP after verification is done; the phone only ever uses 9001.

---

## 9. Encryption inventory — the doctor-facing answer

Data in this system is synthetic (generated CSV readings) — **no real patient records exist in the deployment**. That remains true by policy: real PHI must never be loaded into the demo DB. Everything below is about protecting the data path anyway.

| Layer | Encryption status |
|---|---|
| **At rest — database** | ✅ **AWS RDS storage encryption, enabled at instance creation** (§2.5); keys are AWS-managed KMS. Volumes/backups inside RDS inherit it. |
| **In transit — app/EC2 ↔ database** | ✅ `DATABASE_URL` carries `?sslmode=require` (§2.7) — every DB connection is TLS. |
| **At rest — app passwords** | ✅ bcrypt (cost 12) hashes only — no plaintext password is ever stored or shipped. |
| **In transit — phone ↔ broker** | ⚠ planned: plain WebSocket (`ws://`) today; WSS/TLS is the documented upgrade path (README Known Limitations + §8). Demo mitigations while it is not yet in place: source-restricted security groups, broker credentials, synthetic data. |
| **In transit — app/admin login** | ⚠ demo escape documented (§8): `EXPO_PUBLIC_ALLOW_PLAIN_HTTP=true` on the preview profile only; production profile fails closed and requires an HTTPS endpoint. |
| **Backups** | Host-side only when needed (`pg_dump` before destructive schema ops, §6.2b); deleted with the session or gated by the operator — no plaintext dumps are left on disk by default. |
| **App password storage on device** | JWT in the nativeKeychain/Keystore via `expo-secure-store`; AsyncStorage only as web fallback. |

**Doctor-facing statement (verbatim, defensible):**

> *Stored health data is encrypted at rest — the deployment database is AWS RDS with storage encryption, and the application connects to it over TLS (`sslmode=require`). User passwords are stored only as bcrypt hashes. All medical data in this deployment is synthetic; production rollout additionally includes WSS (TLS) for phone→server streaming, listed on the documented production checklist. Database access is private-network only: the DB endpoint has no public access and admits only the application's security group.*

**To keep those claims true:** never load real patient data into the demo DB, keep the RDS per-session lifecycle (delete without final snapshot, §5), and don't repoint `DATABASE_URL` without the `?sslmode=require` suffix (§7 has the troubleshooting row if you do).
