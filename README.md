# SleepMonitor

A QoS-aware real-time sleep monitoring system built as a Final Year Project (FYP). The mobile app receives live physiological data (SpO2, heart rate, HRV, motion) from a Python publisher (`python-publisher/`) via MQTT and displays it to patients and doctors with role-based dashboards.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Run the Full Stack](#run-the-full-stack)
- [Broker Setup (Mosquitto)](#broker-setup-mosquitto)
- [Database & Ingest (PostgreSQL)](#database--ingest-postgresql)
- [Running the App](#running-the-app)
- [Test Credentials](#test-credentials)
- [Project Structure](#project-structure)
- [MQTT Topics and QoS](#mqtt-topics-and-qos)
- [Known Limitations](#known-limitations)

---

## Overview

SleepMonitor classifies sleep readings into four tiers and transmits them over MQTT with different Quality-of-Service (QoS) levels matching the clinical urgency of each event:

| Tier | SpO2 Threshold | MQTT Topic | QoS | Colour |
|---|---|---|---|---|
| Critical | < 90% | `sleep/critical` | 2 — Exactly once | Red |
| Important | 90–94% | `sleep/important` | 1 — At least once | Amber |
| Normal | ≥ 95% | `sleep/normal` | 0 — Best effort | Green |
| Background | Stats / batch | `sleep/background` | 0 — Best effort | Grey |

The Python publisher reads `data/sleep_data_realistic.csv`, assigns a tier, and publishes JSON payloads to the Mosquitto broker. The React Native app in `app/` subscribes over WebSocket and renders live vitals, an event log, session reports, and network diagnostics.

---

## Architecture

```
data/sleep_data_realistic.csv
      │
      ▼
Python Publisher  (python-publisher/)
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
- **Mosquitto** MQTT broker installed on your laptop
- **Python 3** with `paho-mqtt` installed (for the publisher and ingest worker)
- **Docker** + **Docker Compose** (for the PostgreSQL ingest database — optional)
- Your laptop and phone must be on the **same Wi-Fi network**

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

Python commands are all run **from the repository root** — the scripts resolve `.env.development` and dataset paths relative to it.

---

## Run the Full Stack

Five processes make up a complete demo. Only two are required for live data in
the app — the others add latency measurement and database persistence.

| # | Process | Optional? | Run from |
|---|---|---|---|
| 1 | PostgreSQL (Docker) | Optional — DB demo only | repo root |
| 2 | Ingest worker | Optional — DB demo only | repo root |
| 3 | Echo responder | Optional — latency readout only | repo root |
| 4 | Publisher | **Required** | repo root |
| 5 | Expo app | **Required** | `app/` |

Prerequisites: Mosquitto is running (a system service — no terminal needed), and
the one-time setup is done (`.env.development`, `.venv-dev/`, `app/.env.development`;
see [Installation](#installation) and [Broker Setup](#broker-setup-mosquitto)).

### Terminal 1 — PostgreSQL (optional)

```bash
docker compose --env-file .env.development up -d
docker ps --filter name=sleep-postgres   # wait until STATUS shows "healthy"
```

### Terminal 2 — Ingest worker (optional, leave running)

```bash
.venv-dev/bin/python ingest/worker.py
```

### Terminal 3 — Echo responder (optional, leave running)

```bash
.venv-dev/bin/python python-publisher/echo.py
```

It answers the app's latency probes. Without it the Network screen shows `—` for
latency; everything else keeps working.

### Terminal 4 — Publisher (leave running)

```bash
.venv-dev/bin/python python-publisher/publisher.py
```

You should see `Loaded 526 rows from data/sleep_data_realistic.csv`, then one line
per published reading. For a fast replay (handy for DB demos):

```bash
PUBLISH_INTERVAL=0.05 .venv-dev/bin/python python-publisher/publisher.py
```

### Terminal 5 — Expo app

```bash
cd app && npx expo start
```

Scan the QR code with Expo Go on your phone (same Wi-Fi), then log in as
`patient@sleep.com` / `1234`. Home shows live vitals; Network shows measured
delivery and estimated latency.

### Sanity check (optional)

```bash
# Raw MQTT tap — prints every message the broker routes
mosquitto_sub -h localhost -p 1883 -t "sleep/#" -v
```

Start order does not matter — the app can join a publisher session mid-stream
(the delivery baseline is recorded when the app joins).

---

## Broker Setup (Mosquitto)

### 1. Install Mosquitto

```bash
# Ubuntu / Debian
sudo apt install mosquitto mosquitto-clients

# macOS
brew install mosquitto
```

### 2. Enable the WebSocket listener

Create or edit `/etc/mosquitto/conf.d/sleepmonitor.conf` (Linux) or the equivalent on macOS:

```
listener 1883
allow_anonymous true

listener 9001
protocol websockets
allow_anonymous true
```

Restart the broker:

```bash
# Linux
sudo systemctl restart mosquitto

# macOS
brew services restart mosquitto
```

### 3. Update the broker IP in the app

Find your laptop's LAN IP address:

```bash
# Linux / macOS
ip addr show   # or: ifconfig | grep "inet "

# Windows
ipconfig       # look for IPv4 Address
```

Set the broker IP in `app/.env.development` (gitignored — copy `app/.env.example` to create it):

```bash
# app/.env.development
EXPO_PUBLIC_BROKER_IP=192.168.x.x
```

Expo inlines `EXPO_PUBLIC_*` variables at bundle time, so **restart `npx expo start`** after changing it. The app falls back to a built-in default if the variable is missing.

### 4. Verify the broker is routing messages

```bash
# Terminal 1 — subscribe to all sleep topics
mosquitto_sub -h <YOUR_IP> -p 1883 -t "sleep/#" -v

# Terminal 2 — publish a test message
mosquitto_pub -h <YOUR_IP> -p 1883 -t "sleep/normal" \
  -m '{"tier":"Normal","spo2":97,"heartRate":62,"hrv":40,"motion":0,"timestamp":"01:00 AM","reason":"","stats":{"critical":0,"important":0,"normal":1,"background":0,"total":1},"qos":0,"topic":"sleep/normal"}'
```

---

## Database & Ingest (PostgreSQL)

Optional durable store for the MQTT stream. A Python **ingest worker** subscribes to the broker and writes readings, alerts, and per-session QoS delivery stats to PostgreSQL. Mosquitto stays native — only Postgres runs in Docker.

**Flow:** `publisher → Mosquitto :1883 → ingest/worker.py → PostgreSQL :5432`

```bash
# 1. Config (first time only — .env.development is gitignored)
cp .env.example .env.development

# 2. Start PostgreSQL (schema applied automatically on first boot)
docker compose --env-file .env.development up -d

# 3. Python deps in a host venv
python3 -m venv .venv-dev
.venv-dev/bin/pip install -r ingest/requirements.txt -r python-publisher/requirements.txt

# 4. Run the ingest worker and publisher — terminals 2 and 4 of
#    "Run the Full Stack" in the README. For DB demos a fast replay is convenient:
LOOP_CSV=false PUBLISH_INTERVAL=0.05 \
  .venv-dev/bin/python python-publisher/publisher.py

# 5. Inspect the results
docker exec sleep-postgres psql -U sleep_user -d sleep_monitor \
  -c "SELECT * FROM session_stats;"
```

`session_stats.missing_readings` measures QoS 0 loss: with the worker stopped during a run, only the QoS 1/2 messages are redelivered on restart.

`echo.py` powers the app's estimated latency readout (it relays `qos/ping` → `qos/pong`). Without it, latency shows `—`. The broker should retain app sessions long enough to survive a disconnect — add `persistent_client_expiration 2h` to `/etc/mosquitto/mosquitto.conf` and restart Mosquitto so abandoned sessions are reaped while queued QoS 1/2 messages still survive.

To re-apply schema changes, wipe the volume with `docker compose --env-file .env.development down -v`.

See [`docs/DATABASE.md`](docs/DATABASE.md) for the schema, payload fields, and design details.

---

## Running the App

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

## Test Credentials

| Role | Email | Password |
|---|---|---|
| Doctor | `doctor@sleep.com` | `1234` |
| Patient | `patient@sleep.com` | `1234` |

Sessions persist across app restarts via `AsyncStorage`.

---

## Project Structure

```
SleepMonitor/
├── app/                              # Expo React Native app (own project root)
│   ├── App.js                        # Root — auth state, role-based routing
│   ├── index.js                      # Expo entry point
│   ├── app.json                      # Expo config (new arch enabled, package IDs)
│   ├── .env.example                  # EXPO_PUBLIC_BROKER_IP template
│   ├── auth/
│   │   └── mockAuth.js               # In-memory login, AsyncStorage session persistence
│   ├── context/
│   │   └── SleepContext.js           # Global MQTT state — useSleep() hook
│   ├── services/
│   │   └── mqttService.js            # Paho WebSocket MQTT client + publish()
│   ├── navigation/
│   │   └── DoctorNavigator.js        # Stack navigator for the doctor role
│   ├── components/
│   │   └── VitalCard.js              # Reusable vital metric display card
│   └── screens/
│       ├── LoginScreen.js
│       ├── HomeScreen.js             # Live vitals + SpO2 sparkline (patient)
│       ├── AlertsScreen.js           # Event log, Critical/Important filter (patient)
│       ├── ReportScreen.js           # Session statistics + QoS summary (patient)
│       ├── NetworkScreen.js          # Broker status + measured metrics (patient)
│       └── doctor/
│           ├── PatientListScreen.js  # Patient list (mock data — Phase 2)
│           └── PatientDetailScreen.js# Individual patient vitals (mock data — Phase 2)
│
├── data/                             # Datasets
│   ├── sleep_data.csv                # ML/training set (has sleep-stage labels)
│   └── sleep_data_realistic.csv      # Demo + DB ingestion set
│
├── python-publisher/                 # MQTT publisher
│   ├── publisher.py                  # Session lifecycle, seq/publishedAt, stats
│   ├── classifier.py                 # Tier rules (SpO2 thresholds)
│   └── echo.py                       # qos/ping → qos/pong latency relay
│
├── ingest/                           # MQTT → PostgreSQL ingest worker
├── postgres/init/01_schema.sql       # Database schema (applied on first boot)
├── ml/                               # Dataset generation (training work lands here)
├── benchmark/                        # Latency benchmark harness (single-clock)
├── docker-compose.yml                # PostgreSQL service (Docker)
├── .env.example                      # Python env template (copy to .env.development)
└── docs/                             # ARCHITECTURE, DATA_MODEL, DATABASE, MQTT_SETUP
```

---

## MQTT Topics and QoS

### Message Payload Schema

Every message published to any `sleep/*` topic is a JSON object:

```json
{
  "tier":      "Critical",
  "spo2":      88,
  "heartRate": 71,
  "hrv":       18,
  "motion":    0,
  "timestamp": "02:14 AM",
  "reason":    "SpO2 below critical threshold (88%)",
  "qos":       2,
  "topic":     "sleep/critical",
  "stats": {
    "critical":   5,
    "important":  12,
    "normal":     48,
    "background": 3,
    "total":      68
  }
}
```

| Field | Type | Description |
|---|---|---|
| `tier` | string | `Critical` / `Important` / `Normal` / `Background` |
| `spo2` | number | Blood oxygen saturation (%) |
| `heartRate` | number | Heart rate (BPM) |
| `hrv` | number | Heart rate variability — RMSSD (ms) |
| `motion` | number | Limb movement index (0 = low) |
| `timestamp` | string | Human-readable time, e.g. `"02:14 AM"` |
| `reason` | string | Classifier explanation (optional) |
| `qos` | number | QoS level used (0, 1, or 2) |
| `topic` | string | MQTT topic name echoed in payload |
| `stats` | object | Cumulative session counts per tier + total |

### QoS Rationale

| QoS | Guarantee | Est. latency (RTT/2) | Used for |
|---|---|---|---|
| 2 | Exactly once (4-way handshake) | measured live | Critical — apnea events; must not be lost or duplicated |
| 1 | At least once (PUBACK) | measured live | Important — borderline readings; duplicates tolerable |
| 0 | Best effort (fire and forget) | measured live | Normal + Background — high-frequency routine data |

> **Latency** figures in the app are **estimated** from round-trip ping/echo (`RTT/2`) via `python-publisher/echo.py`; they are an on-device indicator, not the thesis measurement. The authoritative figures come from the single-clock benchmark (producer and consumer timestamps on one host clock).

> **Note:** The app subscribes `sleep/#` at QoS 2 and connects with `cleanSession: false`, so the broker does not downgrade critical/important traffic and queues QoS 1/2 while the app is offline.

---

## Known Limitations

| Issue | Impact | Planned Fix |
|---|---|---|
| Mock authentication | Passwords hardcoded in source; no expiry | Replace with Supabase Auth or Clerk |
| Doctor screens use static data | Patient list and vitals are not live | Phase 2: subscribe per-patient MQTT topics + backend |
| No tests | No safety net for regressions | Add Jest unit tests + Maestro E2E |
| Android package is `com.anonymous.*` | Cannot be submitted to Play Store | Update `app.json` before release |
