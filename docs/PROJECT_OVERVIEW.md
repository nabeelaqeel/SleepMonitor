# Project Overview

A QoS-aware real-time sleep monitoring system built as a Final Year Project (FYP).

**Last updated:** 2026-10-13

---

## What It Is

A Python classifier reads `sleep_data.csv`, assigns each reading to one of four
clinical tiers, and publishes it over MQTT at a Quality-of-Service level matching
that tier's urgency. An Expo React Native app subscribes to the broker over
WebSocket and renders patient and doctor dashboards.

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
sleep_data.csv (631 lines, columns: sr,rr,t,lm,bo,rem,sr,hr,sl)
      │
      ▼  classifies tier → selects QoS
python-publisher/ (publisher.py + classifier.py)
      │
      │  TCP :1883
      ▼
Mosquitto broker  (laptop LAN IP, e.g. 192.168.0.29)
      │
      │  WebSocket :9001
      ▼
services/mqttService.js  (Paho JS client)
      │
      ▼
context/SleepContext.js  (React Context — single source of truth)
      │
      ├── HomeScreen     live vitals + SpO2 sparkline
      ├── AlertsScreen   filterable Critical/Important event log
      ├── ReportScreen   session statistics + timeline + PDF export
      ├── NetworkScreen  broker status + per-topic QoS metrics
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

Full system layout. Lines tagged `[infra]` exist only on `feature/docker-cicd-infra`.

```
App.js                      auth gate → Login / PatientTabs / DoctorStack
index.js                    Expo entry point
app.json                    Expo config (new arch, package IDs)

auth/mockAuth.js            hardcoded credentials + AsyncStorage session
services/mqttService.js     Paho WebSocket client (BROKER_IP hardcoded, line 8)
context/SleepContext.js     global MQTT state, useSleep() hook

screens/
  LoginScreen.js
  HomeScreen.js             live vitals + SpO2 sparkline
  AlertsScreen.js           Critical/Important event log
  ReportScreen.js           session stats, timeline, PDF export
  NetworkScreen.js          broker status + per-topic QoS metrics
  doctor/PatientListScreen.js    mock patient list
  doctor/PatientDetailScreen.js  mock patient detail

components/VitalCard.js     reusable vital metric card
navigation/DoctorNavigator.js

python-publisher/           THE REAL PIPELINE
  publisher.py              reads CSV, owns session lifecycle, publishes MQTT
  classifier.py             tier rules (SpO2 thresholds only)
  Dockerfile, requirements.txt

ingest/                     DATABASE INGEST (new)
  worker.py                 MQTT → Postgres, persistent session, single writer
  db.py                     idempotent Postgres access layer
  requirements.txt

backend-api/                STUB — Dockerfile only, src/ is empty        [infra]
mosquitto/                  broker config + Dockerfile                  [infra]
postgres/init/01_schema.sql database schema (seq, published_at, delivery columns)
docker-compose.yml          postgres only (this branch); full stack is   [infra]
Makefile                    common dev tasks                           [infra]
.env.example                environment template (no secrets)

evaluation.py               A/B QoS experiment harness
evaluation_results.json     output of evaluation.py
classifier.py (root)        MISNAMED — an MQTT experiment script, not a classifier
test.py, generate_data.py   scratch scripts
sleep_data.csv              primary dataset
sleep_data_realistic.csv    alternate dataset (different schema)

docs/                       ARCHITECTURE, DATA_MODEL, DATABASE, MQTT_SETUP (+ DOCKER, AWS_MIGRATION [infra])
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
| Doctor dashboards | Not live | Hardcoded `MOCK_PATIENTS`; not connected to MQTT |
| MQTT client | Working | Per-install persisted client ID, `cleanSession: false`, `sleep/#` + `qos/pong` at QoS 2, exponential-backoff reconnect |
| Python publisher | Partial | Runs; owns session lifecycle + `seq`/`publishedAt`. HRV still always 35 (Issue 3) |
| Classifier | Inconsistent | `python-publisher/classifier.py` uses SpO2 only; `evaluation.py` uses SpO2 + HR + HRV |
| Mosquitto broker | Working | System install on `:1883` / `:9001` (anonymous, localhost) |
| `backend-api` | Stub | No source, no `package.json` — Docker build fails |
| PostgreSQL schema | Working | Extended with `seq`, `published_at`, unique keys, delivery columns |
| Ingest worker | Working | `ingest/worker.py` — MQTT → Postgres, verified end-to-end (see `docs/DATABASE.md`) |
| `evaluation.py` | Misleading | Produces output, but the numbers are simulated constants |
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
- `.claude/` is gitignored. `.venv/` is accidentally tracked (1013 files).

---

## Known Issues

Ranked by impact on the FYP.

### 1. Latency values are fabricated and directionally wrong — ✅ Resolved
Previously `context/SleepContext.js:117` hardcoded `12 / 28 / 45 ms` (and inverted
vs real MQTT behaviour), with the same figures in `NetworkScreen.js` and `README.md`.

**Fix:** the app now samples round-trip time via a ping/echo probe. It publishes a
`qos/ping` every second (cycling QoS 2 → 1 → 0), `python-publisher/echo.py` republishes
it to `qos/pong`, and the context times the trip with the monotonic `performance.now()`
clock and stores the window **median** of `RTT/2`. Both timestamps are on the phone, so
clock skew cancels. Delivery is likewise measured from distinct `seq` vs the publisher's
`stats` delta. The app labels these strictly as **estimates**; the thesis figures come
from the single-clock benchmark.

### 2. Evaluation measures a different classifier than the app runs
`evaluation.py:44-57` classifies using SpO2 **and** heart rate **and** HRV.
`python-publisher/classifier.py:23-41` uses **SpO2 only** (the other parameters
are accepted but never used).

**Impact:** evaluation results do not describe the system that actually runs.
**Fix:** extract one shared classifier and import it from both.

### 3. HRV is always 35
`python-publisher/publisher.py:106`

```python
hrv = float(row.get("hrv", 35))
```

`sleep_data.csv` has no `hrv` column (its columns are `sr,rr,t,lm,bo,rem,sr,hr,sl`),
so every message carries the fallback `35`. The correct column is `rr`.

**Impact:** one of the four displayed vitals is constant.
**Fix:** `row.get("rr", 35)`.

### 4. `backend-api` is a stub but is wired into compose
`backend-api/` contains only a `Dockerfile` and `.dockerignore`; `src/` is empty
and there is no `package.json`. The Dockerfile runs `COPY package.json
package-lock.json ./`, `npm ci`, `npm run build`, and `CMD node dist/index.js` —
all of which fail.

**Impact:** `docker compose up --build` cannot succeed.
**Fix:** implement the API, or remove it from `docker-compose.yml` until then.

### 5. End-to-end QoS is not actually enforced — ✅ Resolved
`services/mqttService.js` previously subscribed without a QoS option (defaulting to QoS 0).

**Fix:** the client now subscribes `sleep/#` at QoS 2 (effective QoS = min(publish QoS, 2))
and connects with `cleanSession: false`, so QoS 1/2 messages are queued while the app is
offline and redelivered on reconnect. Delivery is measured per tier, so the end-to-end
guarantee is visible in the app and verifiable by disconnecting/reconnecting the app
while the publisher runs.

### 6. Evaluation runs against unused topics
`evaluation.py:81-85` publishes and subscribes on `eval/*`. The app subscribes
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

### 9. Repository clutter
Root `classifier.py` is a misnamed MQTT experiment script (not a classifier),
`test.py` is a 5-line scratch file, and two CSVs with incompatible schemas exist.

**Fix:** delete or move into a `scripts/` directory.

### 10. No automated tests
No Jest unit tests, no end-to-end tests.

---

## Roadmap

| Priority | Work | Rationale |
|---|---|---|
| 1 | Finish app features (Report timeline, PDF export, doctor screens) | Core deliverable |
| 2 | Single-clock latency benchmark (Issues 1, 6, 7) | The panel's explicit ask — the **authoritative** numbers |
| 3 | Unify the classifier (Issue 2) and fix HRV (Issue 3) | Validity of the whole evaluation |
| 4 | Resolve `backend-api` (Issue 4) | System integrity |
| 5 | AWS deployment via GitHub Container Registry + SSH | Learner Lab cannot use the current ECR pipeline |

> App-side latency (Issue 1), end-to-end QoS (Issue 5), `publishedAt` (Issue 7), and
> connection state (Issue 8) are now implemented. The app's `RTT/2` readout is an
> on-device **indicator**, not a thesis result.

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
