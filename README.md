# SleepMonitor

A QoS-aware real-time sleep monitoring system built as a Final Year Project (FYP). The mobile app receives live physiological data (SpO2, heart rate, HRV, motion) from an external Python classifier via MQTT and displays it to patients and doctors with role-based dashboards.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
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

The Python classifier reads `sleep_data.csv`, assigns a tier, and publishes JSON payloads to the Mosquitto broker. The React Native app subscribes over WebSocket and renders live vitals, an event log, session reports, and network diagnostics.

---

## Architecture

```
sleep_data.csv
      │
      ▼
Python Classifier (external)
  Reads rows → applies SpO2 thresholds → publishes JSON
      │
      │  TCP :1883
      ▼
Mosquitto Broker  (your laptop LAN IP)
      │
      │  WebSocket :9001
      ▼
mqttService.js  (Paho JS client)
      │
      ▼
SleepContext.js  (React Context — single source of truth)
      │
      ├── HomeScreen    — live vitals + SpO2 sparkline
      ├── AlertsScreen  — filterable Critical/Important event log
      ├── ReportScreen  — session statistics + tier distribution
      └── NetworkScreen — broker status + per-topic delivery rates
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
- **Expo CLI** — `npm install -g expo-cli` or use `npx expo`
- **Expo Go** app on your phone (iOS / Android), or an emulator
- **Mosquitto** MQTT broker installed on your laptop
- **Python 3** with `paho-mqtt` installed (for the classifier/publisher)
- **Docker** + **Docker Compose** (for the PostgreSQL ingest database — optional)
- Your laptop and phone must be on the **same Wi-Fi network**

---

## Installation

```bash
# Clone the repo
git clone <repo-url>
cd SleepMonitor

# Install dependencies
npm install
```

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

Edit `services/mqttService.js` line 8:

```js
const BROKER_IP = '192.168.x.x';  // replace with your actual LAN IP
```

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

# 4. Run the ingest worker (leave running)
.venv-dev/bin/python ingest/worker.py

# 5. In another shell, run the publisher against the realistic dataset
set -a && . ./.env.development && set +a
CSV_PATH=sleep_data_realistic.csv LOOP_CSV=false PUBLISH_INTERVAL=0.05 \
  .venv-dev/bin/python python-publisher/publisher.py

# 6. Inspect the results
docker exec sleep-postgres psql -U sleep_user -d sleep_monitor \
  -c "SELECT * FROM session_stats;"
```

`session_stats.missing_readings` measures QoS 0 loss: with the worker stopped during a run, only the QoS 1/2 messages are redelivered on restart. To re-apply schema changes, wipe the volume with `docker compose --env-file .env.development down -v`.

See [`docs/DATABASE.md`](docs/DATABASE.md) for the schema, payload fields, and design details.

---

## Running the App

```bash
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
├── App.js                          # Root — auth state, role-based routing
├── index.js                        # Expo entry point
├── app.json                        # Expo config (new arch enabled, package IDs)
├── sleep_data.csv                  # Dataset for the classifier (has sleep-stage labels)
├── sleep_data_realistic.csv        # Dataset used for demos + DB ingestion
│
├── auth/
│   └── mockAuth.js                 # In-memory login, AsyncStorage session persistence
│
├── context/
│   └── SleepContext.js             # Global MQTT state — useSleep() hook
│
├── services/
│   └── mqttService.js              # Paho WebSocket MQTT client (configure BROKER_IP here)
│
├── navigation/
│   └── DoctorNavigator.js          # Stack navigator for the doctor role
│
├── components/
│   └── VitalCard.js                # Reusable vital metric display card
│
├── screens/
│   ├── LoginScreen.js
│   ├── HomeScreen.js               # Live vitals + SpO2 sparkline (patient)
│   ├── AlertsScreen.js             # Event log, Critical/Important filter (patient)
│   ├── ReportScreen.js             # Session statistics + QoS summary (patient)
│   ├── NetworkScreen.js            # Broker status + per-topic metrics (patient)
│   └── doctor/
│       ├── PatientListScreen.js    # Patient list (mock data — Phase 2)
│       └── PatientDetailScreen.js  # Individual patient vitals (mock data — Phase 2)
│
├── python-publisher/               # MQTT publisher + tier classifier (the real pipeline)
├── ingest/                         # MQTT → PostgreSQL ingest worker
├── postgres/init/01_schema.sql     # Database schema (applied on first boot)
├── docker-compose.yml              # PostgreSQL service (Docker)
├── .env.example                    # Environment template (copy to .env.development)
└── docs/                           # ARCHITECTURE, DATA_MODEL, DATABASE, MQTT_SETUP
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

| QoS | Guarantee | Latency (est.) | Used for |
|---|---|---|---|
| 2 | Exactly once (4-way handshake) | ~12 ms | Critical — apnea events; must not be lost or duplicated |
| 1 | At least once (PUBACK) | ~28 ms | Important — borderline readings; duplicates tolerable |
| 0 | Best effort (fire and forget) | ~45 ms | Normal + Background — high-frequency routine data |

> **Important:** The Paho client currently subscribes without an explicit QoS option, so subscriptions default to QoS 0. To get end-to-end QoS 2 on the critical topic, update `mqttService.js` to subscribe with `{ qos: 2 }`.

---

## Known Limitations

| Issue | Impact | Planned Fix |
|---|---|---|
| `BROKER_IP` is hardcoded | App breaks on a different network | Move to env var / settings screen |
| No reconnection logic | Connection silently dies after dropout | Add exponential-backoff reconnect in `onConnectionLost` |
| `connected` flag never resets | NetworkScreen shows "Connected" even after dropout | Reset to `false` in `onConnectionLost` |
| Subscribe QoS defaults to 0 | QoS 2 guarantee only applies publisher→broker, not broker→app | Pass explicit `{ qos: N }` per topic |
| Mock authentication | Passwords hardcoded in source; no expiry | Replace with Supabase Auth or Clerk |
| Doctor screens use static data | Patient list and vitals are not live | Phase 2: subscribe per-patient MQTT topics + backend |
| Latency values are simulated | NetworkScreen shows fixed figures, not real RTT | Embed `publishedAt` timestamp; compute on receipt |
| Delivery rates are hardcoded | Not measured from real packet loss | Track sequence numbers or use MQTT diagnostics |
| `mqtt` package installed but unused | Unnecessary bundle weight | `npm uninstall mqtt` |
| `react-native-vector-icons` unused | `@expo/vector-icons` (Expo built-in) is used instead | Remove from `package.json` |
| No tests | No safety net for regressions | Add Jest unit tests + Maestro E2E |
| Android package is `com.anonymous.*` | Cannot be submitted to Play Store | Update `app.json` before release |
