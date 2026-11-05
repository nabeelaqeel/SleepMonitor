# Deployment & Update Guide (AWS Learner Lab)

This guide covers putting the full SleepMonitor stack on an **AWS Academy Learner Lab** EC2 instance, exporting the React Native app as an **APK** (EAS cloud build), and — after the first deploy — how to ship fixes and changes without rebuilding the world every time.

> **Quick runbook:** the README's [Run the Full Stack](../README.md#run-the-full-stack) section is the laptop-local version; this document is the server + release version.

---

## Deploy Order at a Glance

There are **two separate artifacts**, and only one of them is rebuilt freely:

| Artifact | Where it runs | Built from | Update cost |
|---|---|---|---|
| Backend stack | EC2 (Learner Lab) | repo, runs directly | `git pull` + restart — **minutes** |
| App APK | phones (sideloaded) | repo via EAS — `EXPO_PUBLIC_*` **baked in at build time** | full EAS build — **~15–25 min** |

Because the app bundles its endpoints at build time, the deploy order is fixed:

```
Phase 0  one-time repo prep (laptop)
        │
Phase 1  EC2 backend on Learner Lab ──► verify with curl + mosquitto_sub
        │                              (dress rehearsal via Expo Go)
        ▼
Phase 2  EAS APK build ──► endpoints now final ──► sideload
        │
Phase 3  operating loop (Section 5) + edit/update loop (Section 6)
```

**Export the app first and it points at your laptop's LAN IP — useless. AWS first, build last.**

---

## 1. AWS Learner Lab Constraints

| Constraint | Impact | Handling |
|---|---|---|
| Starter budget (≈ $50, no top-ups) | Everything bills against it | t3.micro ≈ $0.02/hr; a lab month is single-digit dollars. The only recurring cost is an Elastic IP left attached (~$3.6/mo, only billed while the instance is stopped) — release it if you'll be idle for months |
| Region fixed at lab start (usually `us-east-1`) | No choice, must create everything there | Just be consistent |
| EC2 instance **stops when the session ends**; storage persists | Docker images, volumes, code survive | `systemd` units auto-start the services on next boot (Section 3.7); verify + fix IP after each restart (Section 5) |
| Public IPv4 changes on restart | The baked app endpoints break | Attach an **Elastic IP** once — it survives stop/start. This is the single highest-value 2 minutes in Phase 1 |
| IAM locked to `LabRole`, no load balancers | No ALB/NLB, no custom roles | Unneeded — everything lives on one instance behind a security group |
| Services usable: EC2, S3, RDS, … (subset) | Docker-on-EC2 is the simplest of the supported paths | Postgres + broker both run in containers; Python services run in a host venv |

---

## 2. Phase 0 — One-Time Repo Prep (laptop)

Do this once, before touching AWS. Everything here ships with the repo.

### 2.1 Broker + server compose files

`docker-compose.yml` is laptop-only (Postgres, Mosquitto runs natively there — running a second broker would port-clash). For the server, add two small files to the repo:

**`mosquitto/mosquitto.conf`** — the broker config the app needs:

```
# TCP listener — Python publisher / ingest / echo on localhost
listener 1883
allow_anonymous true

# WebSocket listener — the phone app (Paho JS)
listener 9001
protocol websockets
allow_anonymous true

# reap abandoned persistent sessions but keep queued QoS 1/2 alive (README guidance)
persistent_client_expiration 2h

log_dest stdout
```

**`docker-compose.aws.yml`** — Postgres + broker, both calling it a service:

```yaml
# Sleep Monitor — AWS Learner Lab stack (Postgres + Mosquitto broker)
# The Python services (api, ingest, publisher, echo) run in a host venv,
# so Postgres is exposed on localhost:5432 and the broker on :1883 only.
# The phone reaches the broker over WebSocket :9001 via the SG.

services:
  postgres:
    image: postgres:16-alpine
    container_name: sleep-postgres
    restart: unless-stopped
    ports:
      - "127.0.0.1:5432:5432"   # host-only — never open 5432 in the SG
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./postgres/init:/docker-entrypoint-initdb.d:ro
    environment:
      POSTGRES_DB:       ${POSTGRES_DB:-sleep_monitor}
      POSTGRES_USER:     ${POSTGRES_USER:-sleep_user}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env.development}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-sleep_user} -d ${POSTGRES_DB:-sleep_monitor}"]
      interval: 10s
      timeout: 5s
      start_period: 20s
      retries: 5
    logging:
      driver: "json-file"
      options: { max-size: "10m", max-file: "3" }

  broker:
    image: eclipse-mosquitto:2
    container_name: sleep-broker
    restart: unless-stopped
    ports:
      - "1883:1883"
      - "9001:9001"
    volumes:
      - mosquitto_data:/mosquitto/data
      - ./mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
    logging:
      driver: "json-file"
      options: { max-size: "10m", max-file: "3" }

volumes:
  postgres_data:
  mosquitto_data:
```

Note `restart: unless-stopped` on both — after every lab-session restart, containers come back on their own.

### 2.2 Fix the Android package name

`app/app.json` currently has `"package": "com.anonymous.SleepMonitor"`. Change it to something owned by you — lowercase, dotted:

```json
"android": {
  "adaptiveIcon": { ... },
  "edgeToEdgeEnabled": true,
  "package": "com.aqeel.sleepmonitor"
}
```

This must happen **before the first APK build** — the package name is the app's identity; changing it later makes every future build a "different app" on the phone.

### 2.3 EAS setup

```bash
npm i -g eas-cli          # or use npx eas-cli@latest throughout

cd app
eas login                 # free account — sign up at expo.dev first if needed
```

Then create **`app/eas.json`** — the `preview` profile produces an installable APK, not a Play-Store bundle, and carries the AWS endpoints:

```json
{
  "build": {
    "preview": {
      "android": { "buildType": "apk" },
      "env": {
        "EXPO_PUBLIC_BROKER_IP": "SET_ME",
        "EXPO_PUBLIC_API_URL": "http://SET_ME:8000"
      }
    },
    "production": {
      "android": { "buildType": "app-bundle" }
    }
  }
}
```

> Profile-level `env` is the documented way to bake `EXPO_PUBLIC_*` into EAS cloud builds — `.env.development` is only used by the local `npx expo start` loop. Fill the `SET_ME` values in Phase 2, once the EC2 IP is known.

---

## 3. Phase 1 — EC2 Backend (per deployment)

### 3.1 Launch + Security Group

In the lab console (correct region — you have no choice), launch:

- **AMI:** Ubuntu 24.04 LTS
- **Instance type:** `t3.micro` (1 GiB RAM — add swap, step 3.5)
- **Key pair:** create `sm-key.pem`, `chmod 400` it
- **Security group `sm-sg`**, inbound:

| Port | Source | Why |
|---|---|---|
| 22 | your IP, or `0.0.0.0/0` while demoing | SSH |
| 1883 | `0.0.0.0/0` | MQTT TCP (publisher-side sanity checks) |
| 9001 | `0.0.0.0/0` | MQTT WebSocket — **the app's only path to the broker** |
| 8000 | `0.0.0.0/0` | Auth API — login |
| *5432* | — | **Do NOT open.** Postgres is host-only (see 2.1) |

### 3.2 Install Docker + Compose

```bash
ssh -i sm-key.pem ubuntu@<EC2_IP>

# one-time, ~2 min
sudo apt update
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker ubuntu    # log out/in once for this to apply
docker version && docker compose version   # sanity
```

### 3.3 Get the repo onto the server

Easiest: a private GitHub repo (add the lab's default key or clone over HTTPS with a token):

```bash
sudo mkdir -p /opt/SleepMonitor && sudo chown ubuntu:ubuntu /opt/SleepMonitor
git clone https://github.com/<you>/SleepMonitor.git /opt/SleepMonitor
```

No repo? `scp` a tarball instead (exclude junk):

```bash

# laptop:
tar --exclude='node_modules' --exclude='.venv*' --exclude='.git' \
    --exclude='benchmark' --exclude='graphify-out' \
    -czf sm.tar.gz .
scp -i sm-key.pem sm.tar.gz ubuntu@<EC2_IP>:/opt/SleepMonitor/

# server:
tar -xzf /opt/SleepMonitor/sm.tar.gz -C /opt/SleepMonitor/
```

### 3.4 Environment file

> **Naming gotcha:** every Python service does `load_dotenv(".env.development")` — that exact filename is hardcoded (`api/config.py`, `ingest/worker.py`, `publisher/*`). Production values go into a file *named* `.env.development` at the repo root. It stays gitignored.

```bash
cp .env.example .env.development   # on the server, from the template

# then edit .env.development:
# - POSTGRES_PASSWORD=<strong password>
# - DATABASE_URL=postgresql://sleep_user:<password>@localhost:5432/sleep_monitor
# - JWT_SECRET=<fresh secret — see below>
# - MQTT_HOST=localhost            (broker container, same host)
# - MQTT_USER/MQTT_PASSWORD=       (empty = anonymous; see Appendix A if you lock the broker)
```

Generate the signing secret on the server itself:

```bash
python3 -c 'import secrets; print("JWT_SECRET=" + secrets.token_hex(32))'
```

> `api/config.py` **refuses to start** on placeholder secrets (`change_me...`) or values under 32 chars — by design, so a copied template can never go live. Use a different secret than your laptop's.

All publisher knobs (`CSV_PATH`, `PUBLISH_INTERVAL`, `LOOP_CSV`, `PATIENT_ID`, …) have sane defaults — only touch them if the demo needs different behavior.

### 3.5 Swap (1 GiB RAM reality check)

Postgres + broker + uvicorn + 2 Python workers fit, but give it headroom:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 3.6 Start Postgres + broker

```bash
cd /opt/SleepMonitor
docker compose -f docker-compose.aws.yml --env-file .env.development up -d
docker ps --format 'table {{.Names}}\t{{.Status}}'
# wait until sleep-postgres shows "healthy"
docker logs sleep-broker          # expect "Opening ipv4 listen socket on port 9001."
```

The schema (`postgres/init/01_schema.sql`) is applied **on first boot only**.

### 3.7 Host venv + systemd services

```bash
cd /opt/SleepMonitor
python3 -m venv .venv
.venv/bin/pip install -r api/requirements.txt -r ingest/requirements.txt -r publisher/requirements.txt
```

Four units, run as root services starting from the repo root. Create `/etc/systemd/system/sm-api.service`:

```ini
[Unit]
Description=SleepMonitor auth API
After=network-online.target docker.service
Requires=docker.service

[Service]
WorkingDirectory=/opt/SleepMonitor
ExecStart=/opt/SleepMonitor/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Reuse the same skeleton for the other three, changing only `Description` and `ExecStart`:

| Unit | ExecStart |
|---|---|
| `sm-ingest.service` | `.venv/bin/python ingest/worker.py` |
| `sm-pub.service` | `.venv/bin/python publisher/publisher.py` |
| `sm-echo.service` | `.venv/bin/python publisher/echo.py` |

Then enable and start everything:

```bash
sudo systemctl enable --now sm-api sm-ingest sm-pub sm-echo
systemctl status sm-api --no-pager
```

`enable` + `Restart=always` means: session ends → EC2 stops → next session starts → broker/postgres (compose restart policy) and app (systemd) all come back automatically.

### 3.8 Verify from the laptop

```bash
# login round-trip (real bcrypt check against Postgres)
curl -sS -X POST http://<EC2_IP>:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"patient@sleep.com","password":"1234"}'
# expect a JSON with "token":"..."

# live MQTT tap — should print a reading every PUBLISH_INTERVAL
mosquitto_sub -h <EC2_IP> -p 1883 -t 'sleep/#' -v

# DB is receiving
ssh ... 'docker exec sleep-postgres psql -U sleep_user -d sleep_monitor -c "SELECT count(*) FROM readings;"'
```

All three green = backend done.

---

## 4. Phase 2 — Export the APK

### 4.1 Dress rehearsal via Expo Go (before any build)

Point the **dev** env at the server and run the real app in Expo Go — catches broken endpoints *before* they get baked into a 25-minute build:

```bash
# app/.env.development (local repo)
EXPO_PUBLIC_BROKER_IP=<EC2_IP>
EXPO_PUBLIC_API_URL=http://<EC2_IP>:8000

npx expo start    # scan the QR with Expo Go
```

Walk through: login on both test accounts → Home shows live vitals → Alert screen fires on critical readings. If this works, the APK will too.

### 4.2 Build

```bash
# 1. Finalize the endpoints in app/eas.json "build.preview.env" (replace SET_ME)
# 2. Build
cd app
eas build -p android --profile preview
```

Android uses EAS-managed keystores — accept the defaults on first run. When the build finishes (~15–25 min), the dashboard gives a download link.

```bash
# 3. Sideload: download the .apk → transfer to phone → allow "install unknown apps" → install
# 4. Log in as usual: patient@sleep.com / 1234
```

> Since the endpoints are baked, this APK works **forever** — but only against the IP baked in. That's what the Elastic IP buys you (Section 1).

---

## 5. Operations Runbook (every session)

```
1. AWS Academy portal ── Start Lab ── console (region is fixed)
2. EC2 ── your instance ── Start
3. Copy the new public IPv4         ── no EIP? → this CHANGED, remember it
4. ssh -i sm-key.pem ubuntu@<IP>
5. docker ps --format ...           # sleep-postgres healthy? sleep-broker up?
6. systemctl status sm-api sm-ingest sm-pub sm-echo --no-pager
7. mosquitto_sub / curl login from the laptop — if green, the demo is live
```

| Activity | Cost |
|---|---|
| t3.micro running ~8h/day, 20 days | ≈ $3–4 |
| EBS 30 GB gp3 persistent | ≈ $2–3/mo |
| Elastic IP attached (even when stopped) | ≈ $3.6/mo — the only thing that drains budget while you're not demoing |

Leaving for a long break? Release the Elastic IP (accepting a rebuild next session) or let it ride if the academic deadline is near.

---

## 6. Editing & Updating After the First Deploy

### 6.1 Decision table — what changed vs what it costs

| Change | What to do | Phone impact |
|---|---|---|
| Backend Python (`api/`, `ingest/`, `publisher/`) | `git pull` + restart unit | **None** |
| MQTT broker config (`mosquitto/mosquitto.conf`) | edit file + `docker compose -f docker-compose.aws.yml restart broker`; **requires app rebuild if credentials added** | Rebuild only for creds change |
| Database schema (`postgres/init/01_schema.sql`) | **Data-wipes:** `down -v` + re-up (§6.3) | None |
| App **JS** (screens, logic, components) | full rebuild — *or* shortcut, Appendix B | New APK → reinstall |
| App **config/native** (`app.json`, plugins, icons, native deps) | full rebuild, always | New APK → reinstall |
| AWS endpoints (session restart without EIP) | values in `eas.json`/`.env.*`, then rebuild | New APK → reinstall |

### 6.2 Backend fixes — the cheap loop

```bash
# laptop: edit, test against the LOCAL stack (README "Run the Full Stack"), commit, push

# server (only what's affected):
cd /opt/SleepMonitor && git pull
.venv/bin/pip install -r api/requirements.txt   # only if that file changed
sudo systemctl restart sm-api                   # sm-ingest / sm-pub / sm-echo as needed
journalctl -u sm-api -n 50 -f                   # watch it come up
```

No app rebuild, no EAS, nothing to reinstall.

### 6.3 Database schema changes — data loss warning

`postgres/init/01_schema.sql` only runs on **first boot of a fresh volume**. To apply schema changes you must wipe:

```bash
cd /opt/SleepMonitor
docker compose -f docker-compose.aws.yml down -v    # ⚠ deletes ALL data
docker compose -f docker-compose.aws.yml up -d    # re-applies init scripts
```

Sessions/alerts counts reset to zero — that's the point of a schema migration here. Do it mid-session, not mid-demo.

### 6.4 App changes — two separate loops

**Dev loop (free, seconds):** all fixing happens here — `npx expo start` + Expo Go, env pointed at whichever backend you're testing against. Every JS edit hot-reloads. Never build to test an idea.

**Release loop (build, 15–25 min):** once a demo version is *frozen*, bake it:

```bash
cd app
eas build -p android --profile preview
```

Same endpoints unless the IP changed — in which case update `eas.json` first.

Practical rhythm: **build only when freezing**, not per fix. Between freezes, demos run from Expo Go.

### 6.5 What always forces a rebuild

No shortcuts for: new/explicit dependency with native code, `app.json` changes (icons, splash, package name, plugins), or `EXPO_PUBLIC_*` value changes. Everything else is Appendix B-eligible.

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `RuntimeError: JWT_SECRET is missing, too weak…` at API start | Copied placeholder or < 32 chars — `api/config.py` rejects it by design | Generate with `secrets.token_hex(32)` |
| `docker logs sleep-broker` silent / app can't reach WS | `mosquitto.conf` not mounted, or config has a syntax error | Check the `-v ./mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf` line |
| Login works once then 401s | `JWT_SECRET` changed → old JWTs invalid | Log out/in in the app (or clear app storage) |
| `sleep-postgres` restart-loop / unhealthy | Password mismatch between `.env.development` and existing volume | Match the values, or `down -v` (wipes) |
| App shows "Broker: disconnected" after a session restart | Public IP changed; the APK still bakes the old one | EIP, or a rebuild from the correct IP |
| Publisher logs "connection refused" | Broker container not up yet | `docker compose -f docker-compose.aws.yml up -d` |
| EAS build fails immediately | No/eas account login, or `eas.json` not in `app/` | `eas login`; verify the JSON path is `app/eas.json` |
| Budget exhausted / lab locked | EIP or instance left running too long | Release the EIP (main suspect — see Section 5 cost table) |

---

## Appendix A — Optional: Broker Credentials

By default the broker is anonymous and open to the internet on 1883/9001 — safe-ish behind the SG, but anyone scanning the IP can inject fake readings. To lock it:

1. **Generate the password** — with a config dir mounted read-write (`./mosquitto/:/mosquitto/config/`, not `:ro`):

```bash
sudo apt install mosquitto-clients            # host, for mosquitto_passwd binary — or:
docker run --rm eclipse-mosquitto:2 mosquitto_passwd -c -b /tmp/pw sm '<password>'
# → append to mosquitto/passwd (host), ensure container can read it
```

2. **Close the broker** — in `mosquitto/mosquitto.conf`:

```
listener 1883
allow_anonymous false
password_file /mosquitto/config/passwd

listener 9001
protocol websockets
allow_anonymous false
password_file /mosquitto/config/passwd
```

3. **Every service gets the creds** — Python side already supports it via env (`.env.development`):

```
MQTT_USER=sm
MQTT_PASSWORD=<password>
```

> Note: `publisher.py` defaults to `admin`/`changeme` — set these explicitly or it won't connect to the locked broker.

4. **App change** (`app/services/mqttService.js`, in `doConnect`):

```js
c.connect({
  cleanSession: false,
  keepAliveInterval: 30,
  useSSL: false,
  userName: process.env.EXPO_PUBLIC_MQTT_USER,
  password: process.env.EXPO_PUBLIC_MQTT_PASSWORD,
  ...
});
```

5. Add the vars to `eas.json` → rebuild (forced: they're `EXPO_PUBLIC_*`).

Do this **before freezing an APK** if you plan to, so you only eat one rebuild.

---

## Appendix B — Optional: OTA Updates (expo-updates / EAS Update)

Every JS-only fix currently costs a full APK rebuild. With EAS Update installed, those changes go over the air to already-installed APKs in ~2 minutes:

```bash
cd app
npx expo install expo-updates   # adds the package
eas init                        # sets "extra.eas.projectId" in app.json
eas update:configure            # writes "updates" + runtimeVersion config
eas build -p android --profile preview   # LAST full rebuild — this APK gains OTA
```

After that one-time setup:

```bash
# ship a JS-only fix without a rebuild:
eas update --branch preview --message "fix alert filter"
```

Limits to remember:

- Covers **JS code only**. Anything in Section 6.5's "always rebuild" list still means `eas build`.
- Covers `EXPO_PUBLIC_*` values too — **an IP change cannot be OTA'd usefully** unless the new value is the same as what the bundle already has, so the EIP recommendation stands.

If you expect to iterate on app code much before the deadline, fold this into Phase 0 instead of retrofitting later — it saves one rebuild cycle that the retrofit itself costs.

---

*Owner note: this document assumes the Phase 0 files (`docker-compose.aws.yml`, `mosquitto/mosquitto.conf`, `app/eas.json`) exist in the repo — create them first (Section 2) if they don't.*
