# Database & Ingest Pipeline

How MQTT readings are persisted to PostgreSQL, and how end-to-end QoS
delivery is measured.

**Last updated:** 2026-10-13
**Branch:** `project/phase2`

---

## Overview

The database layer adds a durable store and a delivery-accounting mechanism
beneath the existing MQTT pipeline. It is deliberately split into three parts:

| Piece | Runtime | Responsibility |
|---|---|---|
| `docker-compose.yml` | Docker | Runs PostgreSQL 16 on `:5432` and applies the schema on first boot |
| `ingest/worker.py` | Host venv | Subscribes to the broker, writes readings/alerts to Postgres |
| `python-publisher/publisher.py` | Host venv | Owns the session lifecycle and tags every reading with `sessionId` / `seq` |

Mosquitto is **not** containerised here — it already runs natively on the host
bound to `:1883` (TCP) and `:9001` (WebSocket), so exposing it again via Docker
would clash.

### Data flow

```
python-publisher/publisher.py
      │  session/start ──────────────┐
      │  sleep/{critical,important,normal} (QoS 2/1/0, seq, publishedAt)
      │  sleep/background (QoS 0)      │
      │  session/end (+ totalReadings) │
      │  MQTT Last Will → session/end  │   (crash safety)
      ▼                                │
Mosquitto broker  :1883                │  persistent session
      │  TCP                           │  (clean_start=False,
      ▼                                │   SessionExpiryInterval=3600)
ingest/worker.py  ─── queue.Queue ────►│  Paho network thread enqueues
      │                                │  single writer thread drains
      ▼                                │
PostgreSQL  :5432  (sessions, readings, alerts, session_stats)
```

---

## Quick Start

```bash
# 1. Postgres (first run applies postgres/init/01_schema.sql automatically)
cp .env.example .env.development         # first time only; edit the password
docker compose --env-file .env.development up -d

# 2. Python deps (host venv — gitignored)
python3 -m venv .venv-dev
.venv-dev/bin/pip install -r ingest/requirements.txt -r python-publisher/requirements.txt

# 3. Ingest worker (leave running)
.venv-dev/bin/python ingest/worker.py

# 4. Publisher — in another shell, with env exported
set -a && . ./.env.development && set +a
CSV_PATH=sleep_data_realistic.csv LOOP_CSV=false PUBLISH_INTERVAL=0.05 \
  .venv-dev/bin/python python-publisher/publisher.py

# 5. Inspect
docker exec sleep-postgres psql -U sleep_user -d sleep_monitor \
  -c "SELECT * FROM session_stats;"
```

The worker must run from the repository root so that `load_dotenv(".env.development")`
resolves; it imports `db.py` from the `ingest/` package relative to the script.

---

## Configuration

`docker-compose.yml` reads the `POSTGRES_*` variables. The worker reads the rest.
`.env.example` is committed; `.env.development` is gitignored (`.gitignore:35`).

| Variable | Used by | Purpose |
|---|---|---|
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | compose | Container bootstrap |
| `DATABASE_URL` | worker | Host-side DSN (`postgresql://user:pw@localhost:5432/db`) |
| `MQTT_HOST` / `MQTT_PORT` | worker, publisher | Broker address |
| `MQTT_USER` / `MQTT_PASSWORD` | worker, publisher | Empty for the anonymous local broker |
| `INGEST_CLIENT_ID` | worker | Fixed client ID required to resume the persistent session |
| `SESSION_EXPIRY` | worker | MQTTv5 `SessionExpiryInterval` (seconds) — how long the broker queues QoS 1/2 while the worker is down |
| `FLUSH_INTERVAL` / `FLUSH_MAX` | worker | Batch flush trigger (seconds / rows) |
| `PATIENT_UUID` | worker | FK target; matches the seeded patient (`…0002`) |
| `DEVICE_ID` | worker, publisher | Session device label |
| `CSV_PATH` | publisher | Dataset path (relative to the working directory) |
| `LOOP_CSV` / `PUBLISH_INTERVAL` | publisher | Replay once (`false`) or loop; seconds between rows |

---

## Schema

Defined in `postgres/init/01_schema.sql` and applied automatically by the
Postgres image on **first** container start (i.e. when the `postgres_data`
volume is empty). To re-apply after editing, destroy the volume:
`docker compose --env-file .env.development down -v`.

### Changes made for the ingest pipeline

| Table | Added | Why |
|---|---|---|
| `readings` | `seq INT NOT NULL`, `published_at TIMESTAMPTZ`, `UNIQUE (session_id, seq)` | Idempotent inserts; real end-to-end latency |
| `alerts` | `seq INT NOT NULL`, `UNIQUE (session_id, seq)` | Same idempotency guarantee for alerts |
| `session_stats` | `expected_readings`, `received_readings`, `missing_readings` | QoS delivery accounting |

`readings.session_id` and `alerts.session_id` reference `sessions(session_id)`,
so the session row must exist before any reading is inserted — the worker
guarantees this (see below).

---

## Publisher Changes

The publisher now owns the session lifecycle. This was a deliberate choice:
the device is the only party that knows when a session truly begins and ends.

### New payload fields (every `sleep/*` reading)

| Field | Type | Purpose |
|---|---|---|
| `sessionId` | UUID string | Groups readings into a session; minted per process run |
| `seq` | integer | Monotonic per-session counter starting at 0; enables gap detection |
| `publishedAt` | integer (epoch ms) | Send time; the basis for real latency (`ts - published_at`) |

Background (`sleep/background`) messages carry `sessionId` and `publishedAt` but
**no `seq`** — they are statistics, not sensor readings, and the worker ignores
them entirely.

### Session events

| Topic | QoS | Payload |
|---|---|---|
| `session/start` | 1 | `{sessionId, event, patientId, deviceId, startedAt}` |
| `session/end` | 1 | `{sessionId, event, patientId, deviceId, endedAt, totalReadings, reason?}` |

`totalReadings` is `stats.total` — the exact number of readings the publisher
sent. The worker uses it as `expected_readings` so a dropped **trailing** run of
QoS 0 packets is still counted (deriving `expected` from `max(seq)+1` cannot see
them).

A **Last Will** is registered on `session/end` (QoS 1, retain off). If the
publisher process dies, the broker publishes it on the publisher's behalf, so the
session is still closed.

### Callback API fix

`mqtt.Client(...)` now receives `mqtt.CallbackAPIVersion.VERSION2` explicitly.
Paho 2.x otherwise defaults to VERSION1 and emits a `DeprecationWarning` — and
the existing `on_disconnect` signature is VERSION2-shaped, so under VERSION1 it
silently received the wrong arguments. `on_connect`/`on_disconnect` now test
`reason_code.is_failure`.

Authentication is applied only when `MQTT_USER` is non-empty, so the anonymous
local broker needs no credentials.

---

## Ingest Worker Design

### Persistent session

The worker connects with MQTTv5, `clean_start=False`, and
`SessionExpiryInterval=SESSION_EXPIRY` using the fixed `INGEST_CLIENT_ID`. The
broker therefore **queues QoS 1 and QoS 2 messages while the worker is offline**
and redelivers them on reconnect. QoS 0 is best-effort and is not queued
(mosquitto's `queue_qos0_messages` defaults to false).

### Threading

Paho's network thread only decodes JSON and pushes items onto a `queue.Queue`.
The main thread is the **single writer** to Postgres, so no DB locking is needed.
Readings and alerts are buffered and flushed on `FLUSH_MAX` rows or
`FLUSH_INTERVAL` seconds, whichever comes first.

### Idempotency

All inserts use `ON CONFLICT DO NOTHING` on `(session_id, seq)`. Redelivery after
a reconnect, or a worker restart, can never create duplicates.

### Session integrity

* On `session/start` the worker upserts the `sessions` row *before* any reading.
* If the worker joins mid-session (misses `session/start`), the first reading for
  an unknown `sessionId` triggers an implicit session upsert using its
  `publishedAt` as `started_at`, satisfying the foreign key.
* On `session/end` it aggregates `readings` and `alerts`, writes `session_stats`,
  and sets `sessions.ended_at`.

### Shutdown

`SIGINT`/`SIGTERM` flush buffered rows and exit **without** ending the session —
the publisher owns that. An open session means the broker still holds anything
undelivered. `session/start` and `session/end` are the only ways a session opens
or closes.

---

## QoS Delivery Accounting

`session_stats` is where the thesis claim becomes measurable:

```
expected_readings = publisher's totalReadings (exact)
received_readings = rows actually persisted
missing_readings  = expected - received        (QoS 0 packets lost in transit)
```

Because QoS 1/2 are protected by the broker's persistent session, `missing` should
account for QoS 0 losses — unless the worker is down past `SESSION_EXPIRY`, in
which case QoS 1/2 begin to be lost too.

Per-reading latency is available directly from the table:

```sql
SELECT tier,
       round(avg(extract(epoch FROM (ts - published_at)) * 1000)::numeric, 1) AS avg_latency_ms,
       count(*)
FROM readings
WHERE published_at IS NOT NULL
GROUP BY tier;
```

> **Caveat:** `publishedAt` comes from the publisher host clock and `ts` from the
> database host clock. On one machine they agree; across hosts, clock skew must
> be bounded (NTP) or eliminated (round-trip measurement) before the latency
> figure is defensible. See `PROJECT_OVERVIEW.md` → Latency measurement approach.

---

## Verification

Two full replays of `sleep_data_realistic.csv` (526 rows) were run.

**Scenario A — worker up throughout:**

| Metric | Result |
|---|---|
| `readings` | 526 |
| Tier split (Normal / Important / Critical) | 278 / 191 / 57 |
| `alerts` (Critical + Important) | 248 |
| `expected / received / missing` | 526 / 526 / 0 |
| Duplicate `(session_id, seq)` | 0 |
| `sessions.ended_at` | set |

**Scenario B — worker stopped, publisher replays, worker restarted:**

The broker queued the QoS 1/2 messages and redelivered them on reconnect; the
QoS 0 Normals were dropped.

| Metric | Result |
|---|---|
| `expected_readings` | 526 |
| `received_readings` | 248 (= 57 Critical + 191 Important) |
| `missing_readings` | 278 (= the QoS 0 Normal readings) |
| Duplicate `(session_id, seq)` | 0 |

Scenario B is the concrete demonstration that prioritised QoS improves delivery
of urgent data under an unreliable consumer.

---

## Files

| Path | Status | Role |
|---|---|---|
| `docker-compose.yml` | new | Postgres-only service, healthcheck, named volume |
| `.env.example` | new | Committed template (`.env.development` is gitignored) |
| `ingest/worker.py` | new | MQTT → Postgres ingest worker |
| `ingest/db.py` | new | Idempotent Postgres access layer |
| `ingest/requirements.txt` | new | `paho-mqtt`, `psycopg2-binary`, `python-dotenv` |
| `postgres/init/01_schema.sql` | modified | `seq`, `published_at`, unique keys, delivery columns |
| `python-publisher/publisher.py` | modified | Session lifecycle, `seq`/`publishedAt`, VERSION2, LWT |
| `.gitignore` | modified | `.venv-dev/`, `__pycache__/`, `*.py[cod]` |

---

## Known Limitations / Next Steps

* **Tail loss when `totalReadings` is absent.** The `max(seq)+1` fallback cannot
  detect a dropped trailing QoS 0 run. The publisher always sends `totalReadings`,
  so this only applies to a Last-Will close with no clean `session/end`.
* **HRV is still a constant.** `publisher.py` uses `row.get("hrv", 35)` and
  `sleep_data_realistic.csv` has no `hrv` column (`minute,bo,hr,rr,motion,event`).
  Deferred by design.
* **`.env.development` is reused** as the compose env-file and the worker's
  dotenv source; a production setup should separate these.
* **No automated tests.** Verified manually via the two scenarios above.
