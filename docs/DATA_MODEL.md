# Data Model

## MQTT Message Payload

All four MQTT topics share the same JSON payload schema. The publisher constructs and sends this; `SleepContext.js` parses and consumes it.

### Full Schema

```json
{
  "sessionId":   "9b87cfb7-5159-4eed-9722-edecd5d4de3f",
  "patientId":   "patient-001",
  "seq":         42,
  "publishedAt": 1760342451533,
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

### Field Reference

| Field | Type | Required | Description |
|---|---|---|---|
| `sessionId` | string (UUID) | Yes | Session the reading belongs to; minted per publisher run. Used by the ingest worker as one half of the dedup key `(session_id, seq)` |
| `patientId` | string | Yes | Identifies the monitored patient (e.g. `"patient-001"`). The app's doctor roster matches this to light up the LIVE entry |
| `seq` | number | Yes | Monotonic per-session counter starting at 0. Gaps reveal QoS 0 loss |
| `publishedAt` | number | Yes | Publish time as epoch milliseconds. Enables real end-to-end latency (`ts - published_at`) |
| `tier` | string | Yes | `"Critical"` / `"Important"` / `"Normal"` / `"Background"` — drives all UI logic |
| `spo2` | number | Yes | Blood oxygen saturation (%) |
| `heartRate` | number | Yes | Heart rate in BPM |
| `hrv` | number | Yes | Heart rate variability — RMSSD in milliseconds |
| `motion` | number | No | Limb/body movement index. Defaults to `0` if absent |
| `timestamp` | string | Yes | Formatted time string displayed in the event log (e.g. `"02:14 AM"`) |
| `reason` | string | No | Human-readable classifier explanation. Defaults to `""` if absent |
| `qos` | number | Yes | QoS level used (0, 1, or 2). Used by the app to assign a display latency value |
| `topic` | string | Yes | MQTT topic name, echoed inside the payload and shown in the event log |
| `stats` | object | No | Cumulative session counters maintained by the publisher |

`sleep/background` messages carry `sessionId`, `patientId` and `publishedAt` but **no `seq`**;
the ingest worker ignores them (session statistics are computed from the readings
themselves). See `docs/DATABASE.md`.

### Session Lifecycle Messages

The publisher owns the session lifecycle and publishes to a separate `session/#`
topic namespace, so the app's per-topic statistics are unaffected.

| Topic | QoS | Fields |
|---|---|---|
| `session/start` | 1 | `sessionId`, `event: "start"`, `patientId`, `deviceId`, `startedAt` |
| `session/end` | 1 | `sessionId`, `event: "end"`, `patientId`, `deviceId`, `endedAt`, `totalReadings`, `reason` (optional) |

A **MQTT Last Will** is registered on `session/end` (QoS 1) so a crashed publisher
still closes its session. `totalReadings` is the exact reading count, used by the
worker to compute delivery loss.

### `stats` Sub-object

The publisher is the authoritative counter. It embeds cumulative totals in every message so the app always has an up-to-date session summary without counting locally.

| Field | Type | Description |
|---|---|---|
| `stats.critical` | number | Total Critical-tier messages published this session |
| `stats.important` | number | Total Important-tier messages |
| `stats.normal` | number | Total Normal-tier messages |
| `stats.background` | number | Total Background-tier messages |
| `stats.total` | number | Sum of all four tiers |

---

## Tier Classification

The shared rules live in **`python-publisher/tier_rules.py`** — the single source
of truth imported by the publisher, the benchmark runner and the benchmark
analysis. Edit the thresholds there and every consumer picks the change up.

Rules are evaluated strictly in this order, so overlapping ranges always
resolve the same way (HR 45 → Important, never Normal; HR 105 → Critical,
not Important):

| # | Condition | Tier | Topic | QoS |
|---|---|---|---|---|
| 1 | SpO2 < 90% OR HR < 40 bpm OR HR > 100 bpm | Critical | `sleep/critical` | 2 |
| 2 | SpO2 90–94% OR HR 40–50/90–100 bpm OR HRV < 20 ms | Important | `sleep/important` | 1 |
| 3 | SpO2 95–100% AND HR 50–90 bpm | Normal | `sleep/normal` | 0 |
| 4 | All other readings (out-of-band values) | Background | `sleep/background` | 0 |

Boundary convention: the checks are exclusive on the Critical side
(SpO2 = 90%, HR = 40/100 bpm land in **Important**) and inclusive on the
Normal side (SpO2 = 95%, HR = 50/90 bpm land in **Normal**). SpO2 = 100 is
Normal because many sensors clamp exactly at 100%. HRV < 20 ms escalates to
Important even when SpO2 and HR look fine. Motion is accepted for the ML
upgrade path but not used by the rule-based tiers.

---

## SleepContext State — Derived from Payload

The table below maps each payload field to the context state it updates:

| Payload field | Context state updated |
|---|---|
| `tier`, `spo2`, `heartRate`, `hrv`, `motion`, `timestamp`, `reason` | `currentData` |
| `stats.*` | `sessionStats` |
| `spo2` | `spo2History` (appended, last 10 kept) |
| `tier`, `spo2`, `heartRate`, `timestamp`, `reason`, `topic` | `eventLog` (Critical and Important only) |
| `tier`, `qos` | `networkStats` (count + latency) |
| `patientId` | `patientSnapshots` (per-patient last reading — the doctor roster's LIVE overlay) |

---

## `data/sleep_data.csv` Schema

The CSV file is read by the Python publisher (and later by the ML pipeline) and replayed row-by-row to simulate a live sensor session.

### Column Headers

```
sr, rr, t, lm, bo, rem, sr, hr, sl
```

> **Known defect:** The header `sr` appears in both column 1 and column 7. `pandas.read_csv()` silently renames column 7 to `sr.1`. The Python publisher should reference columns by position or rename column 7 in the file.

### Column Definitions

| Position | Header | Likely Meaning | Observed Range | Notes |
|---|---|---|---|---|
| 1 | `sr` | SpO2 raw / Signal Ratio | 45–96 | Primary SpO2 proxy for tier classification |
| 2 | `rr` | Respiratory Rate (breaths/min) | 16–26 | Slightly above clinical normal (12–20) |
| 3 | `t` | Temperature (°F, normalised) | 85–99 | Plausible skin/oral temperature range |
| 4 | `lm` | Limb Movement index | 4–17 | Dimensionless; higher = more movement |
| 5 | `bo` | Blood Oxygen % (processed SpO2) | 82–96 | Recommended column for SpO2 — post-processing applied |
| 6 | `rem` | REM-related index / score | 61–100 | Probability or feature score, not raw REM time |
| 7 | `sr` *(duplicate)* | Stage Ratio / Secondary Signal | 0–9 | Duplicate header; reference as `sr.1` in pandas |
| 8 | `hr` | Heart Rate (BPM) | 50–76 | Resting sleep HR; plausible range |
| 9 | `sl` | Sleep Stage Label | 0–4 | Integer class label (see below) |

### Sleep Stage Labels (`sl` column)

| Value | Stage |
|---|---|
| 0 | Deep Sleep (N3 — Slow Wave Sleep) |
| 1 | Light Sleep (N1/N2) |
| 2 | REM Sleep |
| 3 | NREM (combined or N2) |
| 4 | Awake / Wake |

### Recommended Publisher Column Usage

Use `bo` (column 5) as the primary SpO2 input for tier classification, as it represents the processed blood oxygen percentage. Use `hr` (column 8) for heart rate. Derive HRV and motion from `lm` or `rr` if needed.

---

## `data/sleep_data_realistic.csv` Schema

The dataset used for live demos and DB ingestion. It is 526 rows (one session
minute per row) and is simpler and self-consistent (no duplicate headers).

> **Generator drift (reconcile during the ML phase):** the committed file's
> column 4 is `rr` (respiratory rate, 12–22), but the current
> `data/generate_data.py` emits `minute,spo2,hr,hrv,motion,event` — i.e. `spo2`
> instead of `bo` and `hrv` (10–55 ms) instead of `rr`. The publisher handles
> both spellings (`bo`→`spo2` fallback), so both files replay correctly, but a
> regenerated CSV is **not** byte-identical to the committed one. Pick one
> naming convention when building the ML pipeline.

### Column Headers

```
minute, bo, hr, rr, motion, event
```

### Column Definitions

| Header | Meaning | Observed Range | Notes |
|---|---|---|---|
| `minute` | Session minute index | 1–526 | Row/time index; not published |
| `bo` | Blood oxygen (SpO2 %) | 82–99 | Primary tier input via the publisher's `bo` → spo2 mapping |
| `hr` | Heart rate (BPM) | 50–76 | Published as `heartRate` |
| `rr` | Respiratory rate | 12–22 | Not currently published |
| `motion` | Movement index | 0.0–0.4 | Publisher reads `lm` first, falling back to `motion` |
| `event` | Ground-truth label | `normal` / `apnea` | 467 normal, 59 apnea — available for ML training |

### Publisher Compatibility

`python-publisher/publisher.py` maps this file with no column-renaming needed:

* `spo2` ← `bo`
* `heartRate` ← `hr`
* `motion` ← `row.get("lm", row.get("motion", 0))` → falls back to `motion`
* `hrv` ← missing → the constant `35` (a known issue; the file has no HRV column)

Tier distribution when replayed: 278 Normal, 191 Important, 57 Critical (526 rows).

---

## SleepContext — eventLog Entry Shape

```js
{
  id:       string,   // String(Date.now()) at receive time
  tier:     string,   // 'Critical' or 'Important'
  time:     string,   // data.timestamp from payload (e.g. '02:14 AM')
  spo2:     number,
  hr:       number,
  duration: string,   // always '—' in Phase 1 (not yet calculated)
  topic:    string,   // MQTT topic name
  reason:   string,
}
```

The log is newest-first and capped at 50 entries. Only Critical and Important events are logged — Normal and Background are discarded at ingestion time in `SleepContext`.

---

## SleepContext — networkStats Shape

```js
{
  connected:   boolean,
  critical:    { count: number, delivery: number|null },
  important:   { count: number, delivery: number|null },
  normal:      { count: number, delivery: number|null },
  background:  { count: number, delivery: number|null },
}
```

`connected` reflects the live connection state (set on connect, cleared on loss while the client reconnects). `count` is the number of **distinct** `seq` values received for that tier since the app joined the session; `delivery` is measured, not hardcoded:

```
delivery = round(count / (stats[tier] - baseline) × 100)     // capped at 100
baseline = stats[tier] - 1  at the first message for that tier
```

The baseline is captured at join, so a late-joining app starts near 100%; it resets when `data.sessionId` changes.

## SleepContext — latencyStats Shape

```js
{
  0: { ms: number|null, samples: number },
  1: { ms: number|null, samples: number },
  2: { ms: number|null, samples: number },
}
```

Estimated latency (**RTT/2**) per QoS level. `ms` is the **window median** of completed round trips (rounded to 2 dp), `samples` the number of live samples. Samples older than 15 s are dropped; an empty window yields `null`, which the UI renders as `—`. These are on-device estimates — the authoritative latency figures come from the single-clock benchmark.
