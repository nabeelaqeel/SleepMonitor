# Project Overview

A QoS-aware real-time sleep monitoring system built as a Final Year Project (FYP).

**Last updated:** 2026-10-16

---

## What It Is

A Python publisher reads a dataset (`data/sleep_data_realistic.csv` for demos),
uses `python-publisher/classifier.py` to assign each reading to one of four
clinical tiers, and publishes it over MQTT at a Quality-of-Service level matching
that tier's urgency. An Expo React Native app (`app/`) subscribes to the broker
over WebSocket and renders patient and doctor dashboards.

| Tier | SpO2 Threshold | MQTT Topic | QoS | Colour |
|---|---|---|---|---|
| Critical | < 90% | `sleep/critical` | 2 — Exactly once | Red |
| Important | 90–94% | `sleep/important` | 1 — At least once | Amber |
| Normal | ≥ 95% | `sleep/normal` | 0 — Best effort | Green |
| Background | Stats / batch | `sleep/background` | 0 — Best effort | Grey |

**Thesis claim:** routing clinically urgent data at higher QoS improves the
reliability of critical-event delivery compared with uniform (non-prioritised)
transmission.

---

## Architecture

```
data/sleep_data_realistic.csv
      │
      ▼  classifies tier → selects QoS
python-publisher/ (publisher.py + classifier.py)
      │
      │  TCP :1883
      ▼
Mosquitto broker  (laptop LAN IP, e.g. 192.168.68.68)
      │
      │  WebSocket :9001
      ▼
app/services/mqttService.js  (Paho JS client)
      │
      ▼
app/context/SleepContext.js  (React Context — single source of truth)
      │
      ├── HomeScreen     live vitals + SpO2 sparkline
      ├── AlertsScreen   filterable Critical/Important event log
      ├── ReportScreen   session statistics + timeline + PDF export
      ├── NetworkScreen  broker status + measured delivery/latency
      └── DoctorNavigator → PatientListScreen → PatientDetailScreen
```

### Role-based routing

`App.js` reads `AsyncStorage` for a persisted session on launch, then renders one
of three branches:

| State | Rendered UI |
|---|---|
| Not logged in | `LoginScreen` |
| `role === 'doctor'` | `DoctorNavigator` — stack: Patient List → Patient Detail |
| `role === 'patient'` | `PatientNavigator` — bottom tabs: Home / Alerts / Report / Network |

---

## Repository Map

```
app/                        Expo React Native app (own project root)
  App.js                    auth gate → Login / PatientTabs / DoctorStack
  index.js                  Expo entry point
  app.json                  Expo config (new arch, package IDs)
  .env.example              EXPO_PUBLIC_BROKER_IP template (copy to .env.development)

  auth/mockAuth.js          hardcoded credentials + AsyncStorage session
  services/mqttService.js   Paho WebSocket client (broker host via EXPO_PUBLIC_BROKER_IP)
  context/SleepContext.js   global MQTT state, useSleep() hook

  screens/
    LoginScreen.js
    HomeScreen.js           live vitals + SpO2 sparkline
    AlertsScreen.js         Critical/Important event log
    ReportScreen.js         session stats, timeline, PDF export
    NetworkScreen.js        broker status + measured delivery/latency
    doctor/PatientListScreen.js    mock patient list
    doctor/PatientDetailScreen.js  mock patient detail

  components/VitalCard.js   reusable vital metric card
  navigation/DoctorNavigator.js

data/                       datasets
  sleep_data.csv            primary ML/training dataset (sleep-stage labels)
  sleep_data_realistic.csv  demo + DB-ingestion dataset (no stage labels)

python-publisher/           THE REAL PIPELINE
  publisher.py              reads CSV, owns session lifecycle, publishes MQTT
  classifier.py             tier rules (SpO2 thresholds only)
  echo.py                   qos/ping → qos/pong relay for the app latency probe
  requirements.txt

ingest/                     DATABASE INGEST
  worker.py                 MQTT → Postgres, persistent session, single writer
  db.py                     idempotent Postgres access layer
  requirements.txt

postgres/init/01_schema.sql database schema (seq, published_at, delivery columns)
docker-compose.yml          postgres only
Makefile                    common dev tasks

ml/                         dataset generation (+ upcoming risk model)
  generate_data.py          writes data/sleep_data_realistic.csv
benchmark/                  evaluation harness
  evaluation.py             A/B QoS experiment harness (to be rewritten, single-clock)

.env.example                environment template (no secrets)
docs/                       ARCHITECTURE, DATA_MODEL, DATABASE, MQTT_SETUP, PROJECT_OVERVIEW
```

---

## Component Status

| Component | Status | Notes |
|---|---|---|
| App authentication | Working | Mock credentials, persisted via `AsyncStorage` |
| Patient — Home | Working | Live vitals, SpO2 sparkline, tier card |
| Patient — Alerts | Working | Filterable event log |
| Patient — Network | Working | Delivery measured from `seq` vs publisher `stats`; latency is estimated `RTT/2` via `echo.py` |
| Patient — Report | Untested | Timeline chart + PDF export (`expo-print` / `expo-sharing`); on-device check pending |
| Doctor dashboards | Partial | Mock roster with a live overlay: the entry whose `patientId` matches the live stream shows LIVE vitals; the others stay seeded records (one patient streams at a time) |
| MQTT client | Working | Per-install persisted client ID, `cleanSession: false`, `sleep/#` + `qos/pong` at QoS 2, exponential-backoff reconnect |
| Python publisher | Partial | Runs; owns session lifecycle + `seq`/`publishedAt`. HRV still always 35 (Issue 3) |
| Classifier | Inconsistent | `python-publisher/classifier.py` uses SpO2 only; `benchmark/evaluation.py` uses SpO2 + HR + HRV |
| Mosquitto broker | Working | System install on `:1883` / `:9001` (anonymous, localhost) |
| PostgreSQL schema | Working | Extended with `seq`, `published_at`, unique keys, delivery columns |
| Ingest worker | Working | `ingest/worker.py` — MQTT → Postgres, verified end-to-end (see `docs/DATABASE.md`) |
| `benchmark/evaluation.py` | Misleading | Produces output, but the numbers are simulated constants |
| Repository hygiene | Clean | `.venv/` untracked, 1060 → ~40 tracked files, app moved to `app/`, datasets to `data/` |
| Docker / compose | Partial | `docker-compose.yml` on this branch runs Postgres only; the full stack is parked |
| CI/CD pipeline | Parked | Not on this branch; on `feature/docker-cicd-infra`; commercial-AWS design, incompatible with AWS Academy Learner Lab |
| Latency metrics | Measured (est.) | Live `RTT/2` estimate from ping/echo; authoritative figures still come from the single-clock benchmark |

Status legend: **Working** · **Partial** · **Untested** · **Stub** · **Misleading** · **Fabricated** · **Not live** · **Parked**

---

## Repository State

```
master (557e0d7)                            tested prototype — tagged fyp1 — pushed
  ├── feature/docker-cicd-infra (fcd4fcc)   36 files — parked archive (Docker / CI / AWS)
  └── project/phase2 (HEAD)                 active work branch (current)
```

- Remote is named **`fyp-SleepMonitor`**, not `origin`.
- Tag `fyp1` → `557e0d7` (tested prototype; contains no Docker, CI, or AWS).
- `project/phase2` branches from `master` and carries the project files forward from
  `fcd4fcc`: the Report timeline + PDF export, doctor screens, `sleepTimeline` state,
  the `python-publisher/` pipeline, and project docs. Infra files (Docker, compose,
  CI, AWS docs) are left parked on `feature/docker-cicd-infra`.
- Cleanup done: `.venv/` is untracked and gitignored (files kept locally),
  `CLAUDE.md` is untracked (like `.claude/`), and the legacy root files
  (`classifier.py`, `test.py`, `evaluation_results.json`) plus the stub
  `backend-api/` are deleted. The repo is reorganised: `app/`, `data/`,
  `ml/`, `benchmark/`.

---

## Known Issues

Ranked by impact on the FYP.

### 1. Latency values are fabricated and directionally wrong — ✅ Resolved
Previously `app/context/SleepContext.js:117` hardcoded `12 / 28 / 45 ms` (and inverted
vs real MQTT behaviour), with the same figures in `NetworkScreen.js` and `README.md`.

**Fix:** the app now samples round-trip time via a ping/echo probe. It publishes a
`qos/ping` every second (cycling QoS 2 → 1 → 0), `python-publisher/echo.py` republishes
it to `qos/pong`, and the context times the trip with the monotonic `performance.now()`
clock and stores the window **median** of `RTT/2`. Both timestamps are on the phone, so
clock skew cancels. Delivery is likewise measured from distinct `seq` vs the publisher's
`stats` delta. The app labels these strictly as **estimates**; the thesis figures come
from the single-clock benchmark.

### 2. Evaluation measures a different classifier than the app runs
`benchmark/evaluation.py:44-57` classifies using SpO2 **and** heart rate **and** HRV.
`python-publisher/classifier.py:23-41` uses **SpO2 only** (the other parameters
are accepted but never used).

**Impact:** evaluation results do not describe the system that actually runs.
**Fix:** extract one shared classifier and import it from both.

### 3. HRV is always 35
`python-publisher/publisher.py:106`

```python
hrv = float(row.get("hrv", 35))
```

`data/sleep_data.csv` has no `hrv` column (its columns are `sr,rr,t,lm,bo,rem,sr,hr,sl`),
so every message carries the fallback `35`. The correct column is `rr`.

**Impact:** one of the four displayed vitals is constant.
**Fix:** `row.get("rr", 35)`.

### 4. `backend-api` is a stub but is wired into compose — ✅ Resolved
`backend-api/` contained only a `Dockerfile` and `.dockerignore`; `src/` was empty
and there was no `package.json`. It has been deleted as part of the repository
cleanup. The Docker/CI stack remains parked on `feature/docker-cicd-infra`, so
nothing on this branch references it.

### 5. End-to-end QoS is not actually enforced — ✅ Resolved
`app/services/mqttService.js` previously subscribed without a QoS option (defaulting to QoS 0).

**Fix:** the client now subscribes `sleep/#` at QoS 2 (effective QoS = min(publish QoS, 2))
and connects with `cleanSession: false`, so QoS 1/2 messages are queued while the app is
offline and redelivered on reconnect. Delivery is measured per tier, so the end-to-end
guarantee is visible in the app and verifiable by disconnecting/reconnecting the app
while the publisher runs.

### 6. Evaluation runs against unused topics
`benchmark/evaluation.py:81-85` publishes and subscribes on `eval/*`. The app subscribes
only to `sleep/*`, so the experiment never exercises the app.

**Impact:** the evaluation and the product are disconnected.
**Fix:** run the experiment over the real `sleep/*` topics.

### 7. Payload timestamp cannot be used for timing — ✅ Resolved
`python-publisher/publisher.py` now emits an epoch-millisecond `publishedAt` field
alongside the human-readable `timestamp`. The app's live latency uses the ping/echo
probe rather than `publishedAt`, because the phone and laptop clocks are not
synchronised and one-way deltas would be dominated by skew.

### 8. Connection state is never invalidated — ✅ Resolved
`onConnectionLost` now sets `connected = false`, the status is surfaced to the context,
and the client reconnects with exponential backoff (1 s → 10 s cap) on a stable per-install
client ID.

### 9. Repository clutter — ✅ Resolved
Root `classifier.py` (a misnamed MQTT experiment script, not a classifier),
`test.py` (a 5-line scratch file), `evaluation_results.json` (simulated
constants), the stub `backend-api/`, and the Docker leftovers were deleted.
`.venv/` (1013 files, committed by accident) is untracked and gitignored, the
Expo app moved to `app/`, datasets to `data/`, `generate_data.py` to `ml/`, and
`evaluation.py` to `benchmark/`. The unused `mqtt` and `react-native-vector-icons`
npm dependencies were removed. Tracked files: 1060 → ~40.

### 10. No automated tests
No Jest unit tests, no end-to-end tests.

---

## Roadmap

| Priority | Work | Rationale |
|---|---|---|
| 1 | Data processing → Random-Forest risk model (`ml/`: probability → Healthy / Monitor / See Doctor → QoS 0/1/2) | Core deliverable — replaces fixed SpO2 thresholds with a calibrated risk score (`CalibratedClassifierCV`, SpO2 < 88 rule override, hybrid PhysioNet + scaled `generate_data.py` data) |
| 2 | Single-clock latency benchmark (rewrite `benchmark/evaluation.py`; optional `tc netem` impairment) | The panel's explicit ask — the **authoritative** numbers for the write-up |
| 3 | On-device end-to-end demo (app disconnect/reconnect delivery + latency) | Confirms the QoS claim under interruption |
| 4 | AWS deployment via GitHub Container Registry + SSH | Learner Lab cannot use the current ECR pipeline |
| 5 | Automated tests (Issue 10) | Regression safety net |

> App-side latency (Issue 1), the `backend-api` stub (Issue 4), end-to-end QoS
> (Issue 5), `publishedAt` (Issue 7), connection state (Issue 8), and repository
> clutter (Issue 9) are now resolved. The app's `RTT/2` readout is an on-device
> **indicator**, not a thesis result.

### Latency measurement approach

Three properties must hold for the result to be defensible:

1. **A real publish timestamp** (epoch ms) must travel in the payload. ✅ (`publishedAt`)
2. **Clock synchronisation** must be either eliminated (measure round-trip time)
   or bounded (NTP-sync both hosts and report the measured offset as uncertainty).
   The publisher and broker run on the same host, so the only real network hop is
   broker → phone. The app's `RTT/2` probe eliminates skew entirely; the
   single-clock benchmark (producer + consumer timestamps on one host clock) is the
   source of truth for the write-up.
3. **Statistics must be reported, not a single number:** mean, median, p95, max,
   jitter (standard deviation), and loss rate, per QoS level. (The app shows a
   window median; the single-clock benchmark should report the full set.)

The strongest experiment is to compare QoS 0 / 1 / 2 under controlled network
impairment (`tc netem delay … loss …`): higher QoS should show higher delivery
and slightly higher latency. This directly tests the thesis claim.

---

## Related Documents

| Document | Contents |
|---|---|
| `README.md` | Setup, running instructions, payload schema, limitations |
| `docs/ARCHITECTURE.md` | App bootstrapping, state shape, component responsibilities |
| `docs/DATA_MODEL.md` | Payload fields and app state mapping |
| `docs/DATABASE.md` | Postgres schema, ingest worker, QoS delivery accounting |
| `docs/MQTT_SETUP.md` | Broker configuration and topic layout |
| `docs/DOCKER.md` | Containers, image tagging, CI/CD, branching *(on `feature/docker-cicd-infra`)* |
| `docs/AWS_MIGRATION.md` | Target AWS architecture *(on `feature/docker-cicd-infra`)* |
