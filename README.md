# SleepMonitor

A QoS-aware real-time sleep monitoring system built as a Final Year Project (FYP). The mobile app receives live physiological data (SpO2, heart rate, HRV, motion) from a Python publisher (`publisher/`) via MQTT and displays it to patients and doctors with role-based dashboards.

---

## Table of Contents

- [Run the demo](#run-the-demo)
- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Run the full stack](#run-the-full-stack)
- [Running the app](#running-the-app)
- [Test credentials](#test-credentials)
- [MQTT messages and QoS](#mqtt-messages-and-qos)
- [Project structure](#project-structure)
- [Documentation](#documentation)
- [Known limitations](#known-limitations)

---

## Run the demo

Server side is **one command** — Mosquitto broker, PostgreSQL, Auth API, ingest worker, publisher, and echo responder all start as one containerized stack. The Expo app is the only process you start by hand.

**First time on this machine?** Do the [one-time setup](#one-time-setup-fresh-laptop) below (env files + broker credentials), then come back here.

```bash
# Server — returns immediately; the first run builds the image (~2 min)
docker compose -f docker-compose.aws.yml --env-file .env.development \
  --profile local-db up -d --build

# Client
cd app && npx expo start
```

Scan the QR code with Expo Go (same Wi-Fi), then log in as `patient@sleep.com` / `1234` or `doctor@sleep.com` / `1234`. Verify with `docker ps` — `sleep-postgres` must report `healthy` and every `sleep-*` container `Up`.

### Docker-free alternative

Prefer running each service by hand, one terminal at a time from a host venv? The complete flow — including system Mosquitto setup — lives in [`docs/RUN_TERMINAL.md`](docs/RUN_TERMINAL.md).

### AI recommendation demo

```bash
# Print what the model says for a synthetic night (healthy | monitor | apnea | rotate)
.venv-dev/bin/python -m ai.demo --scenario apnea

# Or publish to the broker so the app account with that patientId shows the band
.venv-dev/bin/python -m ai.demo --scenario monitor --publish \
  --patient-id 00000000-0000-0000-0000-000000000002 --host localhost
```

Details and the container `--profile ai-demo` variant: [`ai/README.md`](ai/README.md).

---

## Overview

SleepMonitor classifies sleep readings into four tiers and transmits them over MQTT with different Quality-of-Service (QoS) levels matching the clinical urgency of each event:

| Tier | Trigger Condition | MQTT Topic | QoS | Colour |
|---|---|---|---|---|
| Critical | SpO2 < 90% OR HR < 40 OR HR > 100 bpm | `sleep/critical` | 2 — Exactly once | Red |
| Important | 90 ≤ SpO2 < 95% OR 40 ≤ HR < 50 OR 90 < HR ≤ 100 bpm OR HRV < 20 ms | `sleep/important` | 1 — At least once | Amber |
| Normal | 95 ≤ SpO2 ≤ 100% AND 50 ≤ HR ≤ 90 bpm AND HRV ≥ 20 ms | `sleep/normal` | 0 — Best effort | Green |
| Background | All other readings + periodic session stats | `sleep/background` | 0 — Best effort | Grey |

The Python publisher reads `data/sleep_data_realistic.csv`, assigns a tier, and publishes JSON payloads to the Mosquitto broker. The React Native app in `app/` subscribes over WebSocket and renders live vitals, an event log, session reports, and network diagnostics.

---

## Architecture

```
data/sleep_data_realistic.csv
      │
      ▼
Python Publisher  (publisher/)
  Reads rows → applies tier rules → publishes JSON
      │
      │  TCP :1883
      ▼
Mosquitto Broker  (your laptop LAN IP)
      │
      │  WebSocket :9001
      ▼
app/services/mqttService.js  (Paho JS client)
      │
      ▼
app/context/SleepContext.js  (React Context — single source of truth)
      │
      ├── HomeScreen    — live vitals + SpO2 sparkline
      ├── AlertsScreen  — filterable Critical/Important event log
      ├── ReportScreen  — session statistics + tier distribution
      └── NetworkScreen — broker status + measured per-topic delivery/latency
```

### Role-based routing

`App.js` checks `AsyncStorage` for a persisted session on launch, then renders one of three branches:

| State | Rendered UI |
|---|---|
| Not logged in | `LoginScreen` |
| `role === 'doctor'` | `DoctorNavigator` — stack: Patient List → Patient Detail |
| `role === 'patient'` | `PatientNavigator` — bottom tabs: Home / Alerts / Report / Network |

---

## Prerequisites

- **Node.js** ≥ 18
- **Expo CLI** — use `npx expo` (no global install needed)
- **Expo Go** app on your phone (iOS / Android), or an emulator
- **Docker** + **Docker Compose** — runs the entire server-side stack with one command
- Your laptop and phone must be on the **same Wi-Fi network**

Only the Docker-free [terminal-by-terminal flow](docs/RUN_TERMINAL.md) additionally needs **Mosquitto** as a system service and a **Python venv** with `paho-mqtt` / `uvicorn` installed manually.

---

## Installation

```bash
# Clone the repo
git clone <repo-url>
cd SleepMonitor

# Install app dependencies (the Expo project lives in app/)
cd app
npm install
```

The repository has **two runtimes**:

| Runtime | Where | How to run |
|---|---|---|
| Expo app | `app/` | `cd app && npx expo start` |
| Python (publisher, echo, ingest) | repo root | `.venv-dev/bin/python <script>` |
| Auth API (`api/`) | repo root | `.venv-dev/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000` |

The containerized stack in [Run the full stack](#run-the-full-stack) replaces
the last two rows: one shared image runs the publisher, echo, ingest worker,
and Auth API as separate containers.

---

## Run the full stack

One command brings up **everything server-side** — Mosquitto broker,
PostgreSQL, Auth API, ingest worker, publisher, and echo responder — as one
containerized stack (`docker-compose.aws.yml`: the same compose file that
deploys to AWS, so a laptop rehearsal exercises the real deployment). The
only process you still run by hand is the Expo app.

**Prerequisites:** Docker is running, and the one-time setup below is done
(`.env.development`, `mosquitto/passwd`, `app/.env.development`).

> The app **cannot log in unless Postgres and the Auth API are up** —
> credentials are bcrypt-verified against the database. The stack starts
> both. Everything past the login screen (MQTT streaming) is unaffected.

### One-time setup (fresh laptop)

```bash
# 0. No system Mosquitto may hold ports 1883/9001 — retire it (sudo, once):
sudo systemctl disable --now mosquitto

# 1. Repo env (gitignored — see .env.example). Set MQTT_USER=sm, a real
#    MQTT_PASSWORD, JWT_SECRET, POSTGRES_PASSWORD:
cp .env.example .env.development

# 2. Broker credential file — the stack's broker is LOCKED (allow_anonymous
#    false), so it refuses to start without ./mosquitto/passwd:
MQPW="$(grep '^MQTT_PASSWORD=' .env.development | cut -d= -f2-)"
docker run --rm -v "$PWD/mosquitto:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -c -b /mosquitto/config/passwd sm "$MQPW"
docker run --rm -v "$PWD/mosquitto:/mosquitto/config" eclipse-mosquitto:2 \
  sh -c 'chown 1883:1883 /mosquitto/config/passwd && chmod 600 /mosquitto/config/passwd'

# 3. App env (copy app/.env.example → app/.env.development): set
#    EXPO_PUBLIC_BROKER_IP + EXPO_PUBLIC_API_URL to this laptop's LAN IP and
#    uncomment EXPO_PUBLIC_MQTT_USER / EXPO_PUBLIC_MQTT_PASSWORD with the same
#    server values — the locked broker rejects unauthenticated phone clients.
```

### Every run

```bash
# server side (returns immediately; the first run builds the image, ~2 min):
docker compose -f docker-compose.aws.yml --env-file .env.development \
  --profile local-db up -d --build

# client side (the only terminal):
cd app && npx expo start
```

`--profile local-db` starts the bundled Postgres service, and `--env-file` is
required on every compose call (compose auto-loads only `.env`, and profile
interpolation needs the file regardless).

Scan the QR code with Expo Go, log in as `patient@sleep.com` / `1234`, and
verify with `docker ps` — `sleep-postgres` must report `healthy` and every
`sleep-*` container `Up`. Home shows live vitals; the Network screen shows
measured delivery and estimated latency.

### Stack operations

| Action | Command |
|---|---|
| Replay the demo CSV fast (DB demos) | Set `PUBLISH_INTERVAL=0.05` in `.env.development`, then re-run `up -d` — only the publisher recreates |
| Watch a service | `docker logs -f sleep-publisher` (also `sleep-ingest`, `sleep-echo`) |
| Stop the stack | `docker compose -f docker-compose.aws.yml --env-file .env.development --profile local-db down` |
| Reset the database | Same `down -v` — schema reapplies from `postgres/init/` on the next boot |
| Recreate after env/code edits | Re-run `up -d --build` — compose only remakes changed containers |

Authenticated tap of the live pipeline (the broker is locked, so anonymous
`mosquitto_sub` is refused):

```bash
MQPW="$(grep '^MQTT_PASSWORD=' .env.development | cut -d= -f2-)"
docker run --rm --network host eclipse-mosquitto:2 \
  mosquitto_sub -h 127.0.0.1 -p 1883 -u sm -P "$MQPW" -t 'sleep/#' -v
```

To run any service by hand instead (host venv, system Mosquitto), follow
[`docs/RUN_TERMINAL.md`](docs/RUN_TERMINAL.md) — including switching the
active `DATABASE_URL` and `MQTT_HOST` lines in `.env.development` to their
`localhost` variants after you `docker compose down`.

---

## Running the app

```bash
cd app

# Start the Expo dev server
npx expo start

# Or run directly on a platform
npx expo run:android
npx expo run:ios
npx expo start --web
```

Scan the QR code with Expo Go on your phone, or press `a` for Android emulator / `i` for iOS simulator.

---

## Test credentials

| Role | Email | Password |
|---|---|---|
| Doctor | `doctor@sleep.com` | `1234` |
| Patient | `patient@sleep.com` | `1234` |

Password `1234` is stored as a **bcrypt hash (cost 12)** in
`users.password_hash` and verified server-side by the Auth API —
[`docs/AUTH_API.md`](docs/AUTH_API.md) covers endpoints, JWT claims, and the
security matrix. Both accounts are fixed on purpose: the project monitors a
single patient with a single watch.

Sessions persist across app restarts: the user object via `AsyncStorage`
and the 12-hour JWT via `expo-secure-store` (device Keychain/Keystore,
with an AsyncStorage fallback on web). Logout clears both.

---

## MQTT messages and QoS

Every reading is classified into one of four tiers (see the table in
[Overview](#overview)) and published as a JSON payload containing the vitals,
a classifier `reason` for alerts, cumulative session stats, and the QoS level
used. The app subscribes `sleep/#` at QoS 2 with `cleanSession: false`, so the
broker never downgrades critical traffic and queues QoS 1/2 messages while the
app is offline.

Full payload schema, field reference, QoS rationale, and reconnection
behaviour: [`docs/MQTT_SETUP.md`](docs/MQTT_SETUP.md).

---

## Project Structure

```
SleepMonitor/
├── app/                              # Expo React Native app (own project root)
│   ├── App.js                        # Root — auth state, role-based routing
│   ├── index.js                      # Expo entry point
│   ├── app.json                      # Expo config (new arch enabled, package IDs)
│   ├── .env.example                  # EXPO_PUBLIC_BROKER_IP + EXPO_PUBLIC_API_URL templates
│   ├── auth/
│   │   └── apiAuth.js                # DB-backed login (POST /auth/login via api/), AsyncStorage session + JWT
│   ├── context/
│   │   └── SleepContext.js           # Global MQTT state — useSleep() hook
│   ├── services/
│   │   ├── mqttService.js            # Paho WebSocket MQTT client + publish()
│   │   └── exportSessionReport.js    # Session PDF builder + share sheet (patient + doctor)
│   ├── data/
│   │   └── patients.js               # Seeded roster; one entry carries a patientId
│   ├── navigation/
│   │   └── DoctorNavigator.js        # Doctor tabs: Patients stack + Alerts
│   ├── components/
│   │   ├── VitalCard.js              # Reusable vital metric display card
│   │   └── EventLog.js               # Shared alert/event list (patient + doctor)
│   ├── hooks/
│   │   └── useNow.js                 # 1 s re-render tick (LIVE badges, last seen)
│   └── screens/
│       ├── LoginScreen.js
│       ├── HomeScreen.js             # Live vitals + SpO2 sparkline (patient)
│       ├── AlertsScreen.js           # Event log (thin wrapper around EventLog)
│       ├── ReportScreen.js           # Session statistics + PDF export (patient)
│       ├── NetworkScreen.js          # Broker status + measured metrics (patient)
│       └── doctor/
│           ├── PatientListScreen.js  # Roster — live values for the streaming patientId
│           ├── PatientDetailScreen.js# Patient detail — live overlay + report export
│           └── DoctorAlertsScreen.js # Alert inbox for the live session
│
├── data/                             # Datasets
│   ├── sleep_data.csv                # ML/training set (has sleep-stage labels)
│   ├── sleep_data_realistic.csv      # Demo + DB ingestion set
│   └── generate_data.py              # Writes sleep_data_realistic.csv
│
├── publisher/                 # MQTT publisher
│   ├── publisher.py                  # Session lifecycle, seq/publishedAt, stats
│   ├── tier_rules.py                 # Single source of truth: tier thresholds + QoS
│   └── echo.py                       # qos/ping → qos/pong latency relay
│
├── ingest/                           # MQTT → PostgreSQL ingest worker
├── api/                              # Auth backend — FastAPI, bcrypt + JWT (docs/AUTH_API.md)
├── postgres/init/01_schema.sql       # Database schema (applied on first boot)
├── benchmark/                        # Latency benchmark harness (single-clock)
├── docker-compose.yml                # PostgreSQL service (Docker)
├── .env.example                      # Python env template (copy to .env.development)
└── docs/                             # ARCHITECTURE, DATA_MODEL, DATABASE, AUTH_API, MQTT_SETUP, RUN_TERMINAL
```

---

## Documentation

| Doc | Contents |
|---|---|
| [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) | Project status, verification results, demo-day plan |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | App bootstrapping, state shape, component responsibilities |
| [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | Payload fields and app state mapping |
| [`docs/MQTT_SETUP.md`](docs/MQTT_SETUP.md) | Broker configuration, payload schema, QoS rationale, reconnection |
| [`docs/DATABASE.md`](docs/DATABASE.md) | Postgres schema, ingest worker, QoS delivery accounting; users + password_hash |
| [`docs/AUTH_API.md`](docs/AUTH_API.md) | Login API: endpoints, JWT design, bcrypt/HS256 security matrix |
| [`docs/RUN_TERMINAL.md`](docs/RUN_TERMINAL.md) | Docker-free, one-terminal-each run (host venv), incl. Mosquitto broker setup |
| [`docs/BENCHMARK_V1_HISTORY.md`](docs/BENCHMARK_V1_HISTORY.md) | History of the v1 latency benchmark |
| [`ai/README.md`](ai/README.md) | AI recommendation module: nightly guidance bands + demo mode |
| [`benchmark/README.md`](benchmark/README.md) | Latency benchmark harness: single-clock methodology, results |

---

## Known Limitations

| Issue | Impact | Planned Fix |
|---|---|---|
| ~~Mock authentication~~ | **Fixed — DB-backed login** (`api/` FastAPI): bcrypt (cost 12) in `users.password_hash`, 12h HS256 JWT; demo password `1234` is still weak, and dev transport is plain HTTP | Change demo password + rotate `JWT_SECRET` + add TLS (reverse proxy or `uvicorn --ssl-*`) before a real deployment |
| Doctor roster is mostly mock | Only the patient whose `patientId` is streaming shows live vitals; the Alerts tab and report export cover that single live session (one at a time) | Later: per-patient topics + backend for true multi-patient |
| No tests | No safety net for regressions | Add Jest unit tests + Maestro E2E |
| Android package is `com.anonymous.*` | Cannot be submitted to Play Store | Update `app.json` before release |
