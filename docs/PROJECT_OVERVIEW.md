# Project Overview

A QoS-aware real-time sleep monitoring system built as a Final Year Project (FYP).

**Last updated:** 2026-10-26

---

## What It Is

A Python publisher reads a dataset (`data/sleep_data_realistic.csv` for demos),
uses `publisher/tier_rules.py` to assign each reading to one of four
clinical tiers, and publishes it over MQTT at a Quality-of-Service level matching
that tier's urgency. An Expo React Native app (`app/`) subscribes to the broker
over WebSocket and renders patient and doctor dashboards.

| Tier | Trigger Condition | MQTT Topic | QoS | Colour |
|---|---|---|---|---|
| Critical | SpO2 < 90% OR HR < 40 OR HR > 100 bpm | `sleep/critical` | 2 — Exactly once | Red |
| Important | 90 ≤ SpO2 < 95% OR 40 ≤ HR < 50 OR 90 < HR ≤ 100 bpm OR HRV < 20 ms | `sleep/important` | 1 — At least once | Amber |
| Normal | 95 ≤ SpO2 ≤ 100% AND 50 ≤ HR ≤ 90 bpm AND HRV ≥ 20 ms | `sleep/normal` | 0 — Best effort | Green |
| Background | All other readings + periodic session stats | `sleep/background` | 0 — Best effort | Grey |

**Thesis claim:** routing clinically urgent data at higher QoS improves the
reliability of critical-event delivery compared with uniform (non-prioritised)
transmission.

---

## Architecture

```
data/sleep_data_realistic.csv
      │
      ▼  classifies tier → selects QoS
publisher/ (publisher.py + tier_rules.py)
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
      └── DoctorNavigator → tabs: Patients (list → detail) + Alerts
```

### Role-based routing

`App.js` reads `AsyncStorage` for a persisted session on launch, then renders one
of three branches:

| State | Rendered UI |
|---|---|
| Not logged in | `LoginScreen` |
| `role === 'doctor'` | `DoctorNavigator` — tabs: Patients (list → detail, PDF export) and Alerts |
| `role === 'patient'` | `PatientNavigator` — bottom tabs: Home / Alerts / Report / Network |

---

## Repository Map

```
app/                        Expo React Native app (own project root)
  App.js                    auth gate → Login / PatientTabs / DoctorStack
  index.js                  Expo entry point
  app.json                  Expo config (new arch, package IDs)
  .env.example              EXPO_PUBLIC_BROKER_IP template (copy to .env.development)

  auth/apiAuth.js           database-backed login (bcrypt + JWT via the api/ FastAPI service), AsyncStorage session + token
  services/mqttService.js   Paho WebSocket client (broker host via EXPO_PUBLIC_BROKER_IP)
  context/SleepContext.js   global MQTT state, useSleep() hook

  screens/
    LoginScreen.js
    HomeScreen.js           live vitals + SpO2 sparkline
    AlertsScreen.js         Critical/Important event log
    ReportScreen.js         session stats, timeline, PDF export
    NetworkScreen.js        broker status + measured delivery/latency
    doctor/PatientListScreen.js    seeded patient list + live overlay
    doctor/PatientDetailScreen.js  patient detail + session PDF export
    doctor/DoctorAlertsScreen.js   live-session alert inbox

  components/VitalCard.js   reusable vital metric card
  components/EventLog.js    shared event list (patient + doctor)
  services/exportSessionReport.js  session PDF builder + share sheet
  data/patients.js          seeded doctor roster
  navigation/DoctorNavigator.js   doctor tabs (Patients stack + Alerts)

data/                       datasets + generator
  sleep_data.csv            primary ML/training dataset (sleep-stage labels)
  sleep_data_realistic.csv  demo + DB-ingestion dataset (no stage labels)
  generate_data.py          writes sleep_data_realistic.csv

publisher/           THE REAL PIPELINE
  publisher.py              reads CSV, owns session lifecycle, publishes MQTT
  tier_rules.py             single source of truth: tier thresholds + QoS
  echo.py                   qos/ping → qos/pong relay for the app latency probe
  requirements.txt

ingest/                     DATABASE INGEST
  worker.py                 MQTT → Postgres, persistent session, single writer
  db.py                     idempotent Postgres access layer
  requirements.txt

api/                        AUTH (FASTAPI, HOST VENV) — see docs/AUTH_API.md
  main.py                   FastAPI app — POST /auth/login, JWT issue, CORS
  db.py                     users access + idempotent bcrypt seeding (hash only when empty)
  security.py               bcrypt hash/verify, HS256 JWT (12h expiry)
  config.py                 loads .env.development first (DATABASE_URL, JWT_SECRET)
  requirements.txt

postgres/init/01_schema.sql database schema (seq, published_at, password_hash, delivery columns)
docker-compose.yml          postgres only
Makefile                    common dev tasks

benchmark/                  single-clock MQTT QoS benchmark (v2, measured)
  run_benchmark.py          real publisher/subscriber, netem, outage, resume, wire counters
  analyze_benchmark.py      join/dedupe, gates, recovery metrics, summaries, plots
  results_v2/               canonical 75-run main study (v2)
  results_v2_sensitivity/   canonical 12-run 1 msg/s study
  calibration_v2/           B/C stock-vs-AF_UNIX calibration (gate PASS)

.env.example                environment template (no secrets)
docs/                       ARCHITECTURE, DATA_MODEL, DATABASE, AUTH_API, MQTT_SETUP, PROJECT_OVERVIEW
```

---

## Component Status

| Component | Status | Notes |
|---|---|---|
| App authentication | Working | DB-backed login: bcrypt in `users.password_hash`, 12h JWT from the `api/` FastAPI service; session persisted via `AsyncStorage`. API must be running before login |
| Patient — Home | Working | Live vitals, SpO2 sparkline, tier card |
| Patient — Alerts | Working | Filterable event log |
| Patient — Network | Working | Delivery measured from `seq` vs publisher `stats`; latency is estimated `RTT/2` via `echo.py` |
| Patient — Report | Untested | Timeline chart + PDF export (`expo-print` / `expo-sharing`); on-device check pending |
| Doctor dashboards | Partial | Seeded roster with a live overlay, plus an Alerts tab and session PDF export for the live patient; one patient streams at a time (true multi-patient needs per-patient topics) |
| MQTT client | Working | Per-install persisted client ID, `cleanSession: false`, `sleep/#` + `qos/pong` at QoS 2, exponential-backoff reconnect |
| Python publisher | Working | Runs; owns session lifecycle + `seq`/`publishedAt`. HRV restored — the demo dataset's third vital was mislabeled `rr` and every reading fell back to 35 ms (Issue 3, resolved) |
| Classifier | Working | The real pipeline uses `publisher/tier_rules.py` — SpO2 + HR + HRV thresholds in one shared module; the legacy simulation classifier is retired (removed) |
| Mosquitto broker | Working | System install on `:1883` / `:9001` (anonymous, localhost) |
| PostgreSQL schema | Working | Extended with `seq`, `published_at`, unique keys, delivery columns |
| Ingest worker | Working | `ingest/worker.py` — MQTT → Postgres, verified end-to-end (see `docs/DATABASE.md`) |
| Single-clock benchmark | Complete (v2) | 75/75 main + 12/12 sensitivity runs; 0 hard-gate failures; 7 netem band warnings + 1 `$SYS` note; paho wake-up offset calibrated (AF_UNIX, gate PASS) |
| Benchmark v1 (simulation + frozen stock-paho runs) | Removed | Code and results deleted from `main`; frozen at the `benchmark-v1-frozen` tag, history in `docs/BENCHMARK_V1_HISTORY.md` |
| Repository hygiene | Clean | `.venv/` untracked, 1060 → ~40 tracked files, app moved to `app/`, datasets to `data/` (with the generator); benchmark reduced to the canonical v2 study |
| Docker / compose | Partial | `docker-compose.yml` on this branch runs Postgres only; the full stack is parked |
| CI/CD pipeline | Parked | Not on this branch; on `feature/docker-cicd-infra`; commercial-AWS design, incompatible with AWS Academy Learner Lab |
| Latency metrics | Measured (two levels) | App shows the live `RTT/2` estimate; authoritative one-way numbers come from the single-clock benchmark v2 |

Status legend: **Working** · **Partial** · **Untested** · **Stub** · **Retired** · **Complete** · **Misleading** · **Fabricated** · **Not live** · **Parked**

---

## Repository State

```
master (557e0d7)                            tested prototype — tagged fyp1 — pushed
  ├── feature/docker-cicd-infra (fcd4fcc)   36 files — parked archive (Docker / CI / AWS)
  └── project/phase2 (HEAD)                 active work branch (current)
```

- Remote is named **`SleepMonitor`** — matching the GitHub repo name. There is no `origin`.
- Tag `fyp1` → `557e0d7` (tested prototype; contains no Docker, CI, or AWS).
- `project/phase2` branches from `master` and carries the project files forward from
  `fcd4fcc`: the Report timeline + PDF export, doctor screens, `sleepTimeline` state,
  the `publisher/` pipeline, and project docs. Infra files (Docker, compose,
  CI, AWS docs) are left parked on `feature/docker-cicd-infra`.
- Cleanup done: `.venv/` is untracked and gitignored (files kept locally),
  `CLAUDE.md` is untracked (like `.claude/`), and the legacy root files
  (`classifier.py`, `test.py`, `evaluation_results.json`) plus the stub
  `backend-api/` are deleted. The repo is reorganised: `app/`, `data/`
  (datasets + generator), `benchmark/`.
- Benchmark v2 is the canonical study (`results_v2/`,
  `results_v2_sensitivity/`); the v1 code and frozen outputs were removed
  from `main` and preserved at the `benchmark-v1-frozen` tag — see
  `docs/BENCHMARK_V1_HISTORY.md`.

---

## Known Issues

Ranked by impact on the FYP.

### 1. Latency values are fabricated and directionally wrong — ✅ Resolved
Previously `app/context/SleepContext.js:117` hardcoded `12 / 28 / 45 ms` (and inverted
vs real MQTT behaviour), with the same figures in `NetworkScreen.js` and `README.md`.

**Fix:** the app now samples round-trip time via a ping/echo probe. It publishes a
`qos/ping` every second (cycling QoS 2 → 1 → 0), `publisher/echo.py` republishes
it to `qos/pong`, and the context times the trip with the monotonic `performance.now()`
clock and stores the window **median** of `RTT/2`. Both timestamps are on the phone, so
clock skew cancels. Delivery is likewise measured from distinct `seq` vs the publisher's
`stats` delta. The app labels these strictly as **estimates**; the thesis figures come
from the single-clock benchmark.

### 2. Evaluation measures a different classifier than the app runs — ✅ Resolved by replacement
The retired simulation (`evaluation.py` — line refs preserved at the
`benchmark-v1-frozen` tag; history in `docs/BENCHMARK_V1_HISTORY.md`)
classified using SpO2 **and** heart rate **and**
HRV. `publisher/tier_rules.py` now implements the same three signals
in one shared module, so the shipped rules and the simulated evaluation agree.
The simulated evaluation is retired;
the single-clock benchmark imports `publisher/tier_rules.py`, so its
tiers describe the pipeline that actually runs.

**Impact:** none on v1 benchmark results; no shared-classifier extraction is
needed for the thesis measurement. The stale classifier remains only in the
historical simulation.

### 3. HRV is always 35 — ✅ Resolved
`publisher/publisher.py` extracts

```python
hrv = float(row.get("hrv", 35))
```

and the committed `data/sleep_data_realistic.csv` had **no `hrv` column** — its
third vital was labeled `rr`, a leftover of an earlier generator version that
misnamed the HRV series (apnea episodes push it to 10–18: exactly the RMSSD ms
pattern; a respiration rate never behaves that way). The generator source was
later renamed to `hrv`, but the CSV was never regenerated, so every published
reading carried the constant fallback `35` — from 2026-10-16 to 2026-11-05 —
while SpO2/HR/motion kept varying normally, hiding the miss.

**Resolution:** the file was regenerated in place with `data/generate_data.py`
(seed 42). The value stream is byte-identical to the old file — only the header
changed, to `minute,spo2,hr,hrv,motion,event` (`bo`→`spo2`, `rr`→`hrv`). The
publisher default `CSV_PATH` now points at this file, `.env.development` loading
is anchored at the repo root (it used to load only when launched from the repo
root), `load_csv` warns loudly when a loaded CSV has no `hrv` column, and
`EXPECTED_DATASET_SHA256` in `benchmark/run_benchmark.py` was updated
deliberately (the completed calibration runs recorded under
`benchmark/calibration_v2/` keep the old hash as history). The tier
distribution is unchanged (57 Critical / 191 Important / 278 Normal): in this
dataset HRV < 20 ms always coincides with the apnea SpO2 drop that already
triggers the tier, but real `hrv` values now reach the payload, the database
and the nightly `rmssd_*` features. The earlier suggestion `row.get("rr", 35)`
relied on the mislabeled column name and is superseded.

> True HRV (RMSSD) is a watch-side computation from beat-to-beat intervals.
> The pipeline treats `hrv` as pass-through everywhere (payload schema,
> `tier_rules`, `SleepContext`, `ai/features.py`); when a real watch streams,
> only field mapping is needed — an RMSSD computation module is added only if
> it reports raw IBI/PPG instead of a ready-made value.

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

### 6. Evaluation runs against unused topics — ✅ Resolved by replacement
The retired simulation published and subscribed on `eval/*`
(`evaluation.py:81-85` at the `benchmark-v1-frozen` tag). The app
subscribes only to `sleep/*`. The legacy simulation is retired; the benchmark
uses `bench/*` topics and a dedicated measuring subscriber, so benchmark
traffic never enters the app topics. End-to-end app delivery is checked
separately on-device.

**Impact:** none on v1 benchmark results. Benchmark and product traffic are
deliberately isolated.

### 7. Payload timestamp cannot be used for timing — ✅ Resolved
`publisher/publisher.py` now emits an epoch-millisecond `publishedAt` field
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
Expo app moved to `app/`, datasets to `data/` (with `generate_data.py`), and
`evaluation.py` to `benchmark/` (later removed entirely with v1 — see
`docs/BENCHMARK_V1_HISTORY.md`). The unused `mqtt` and
`react-native-vector-icons`
npm dependencies were removed. Tracked files: 1060 → ~40.

### 10. No automated tests
No Jest unit tests, no end-to-end tests.

### 11. Netem absolute latency includes a paho wake-up offset — ✅ Measured, bypassed in v2
`paho-mqtt 2.1.0` uses an internal AF_INET socketpair on `127.0.0.1` for
cross-thread wake-ups. With `tc netem` on `lo`, the one-byte wake-up is delayed
too, so v1 (stock paho) netem absolute latency included roughly **23 ms** of
client-side offset. The cause is supported by source inspection, a runtime
check and a calibration: the v2 stock-vs-AF_UNIX B/C calibration measured the
offset at **22.9–24.0 ms** for every QoS level and switched the harness to a
non-loopback **AF_UNIX** socketpair by default, so v2 netem values carry no
client-side offset. Clean latency was never affected. See
`benchmark/README.md` §16 and `docs/BENCHMARK_V1_HISTORY.md`.

---

## Roadmap

| Priority | Work | Rationale |
|---|---|---|
| 1 | AI recommendation module (`ai/`: Random-Forest risk model — probability → Healthy / Monitor / See Doctor → QoS 0/1/2) | Core deliverable — replaces fixed SpO2 thresholds with a calibrated risk score (`CalibratedClassifierCV`, SpO2 < 88 rule override, hybrid PhysioNet + scaled `data/generate_data.py` data) |
| 2 | Single-clock latency benchmark — ✅ Complete (v2) | The panel's explicit ask — authoritative numbers for the write-up. 75/75 main + 12/12 sensitivity runs, AF_UNIX offset calibrated (gate PASS), 0 hard gates; v1 withdrawn to `benchmark-v1-frozen` |
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
3. **Statistics must be reported, not a single number:** per-run median and p95,
   min–max across repetitions, and delivery/loss by tier. (The app shows a
   window median; the benchmark reports the study-level distribution without
   pooling messages into a false confidence interval.)

The single-clock benchmark now implements the controlled comparison. **v2**
has 75 complete main runs (3 experiments × 5 conditions × 5 repetitions) and
12 sensitivity runs (clean and netem only), with 0 hard-gate failures and
100 % delivery in clean/netem.
The main 10 msg/s study is the stress case; the 1 msg/s sensitivity study is
the production-like pacing check. Netem latencies carry no client-side
wake-up offset in v2 (Issue 11 above); clean values and relative QoS
comparisons are the defensible numbers. The benchmark's `bench/*` traffic
is isolated from the app's `sleep/*` topics, and the app's `RTT/2` readout
remains an on-device estimate, not a thesis result.

---

## Related Documents

| Document | Contents |
|---|---|
| `README.md` | Quick start + Docker full-stack run, QoS tier table, structure, limitations |
| `docs/RUN_TERMINAL.md` | Docker-free, terminal-by-terminal run (host venv), incl. Mosquitto setup |
| `docs/ARCHITECTURE.md` | App bootstrapping, state shape, component responsibilities |
| `docs/DATA_MODEL.md` | Payload fields and app state mapping |
| `docs/DATABASE.md` | Postgres schema, ingest worker, QoS delivery accounting; users + password_hash |
| `docs/AUTH_API.md` | Login API: runbook, endpoints, JWT design, bcrypt/HS256 security summary |
| `docs/MQTT_SETUP.md` | Broker configuration, topic layout, payload schema, QoS rationale |
| `docs/DOCKER.md` | Containers, image tagging, CI/CD, branching *(on `feature/docker-cicd-infra`)* |
| `docs/AWS_MIGRATION.md` | Target AWS architecture *(on `feature/docker-cicd-infra`)* |
