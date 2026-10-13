# Data Model

## MQTT Message Payload

All four MQTT topics share the same JSON payload schema. The publisher constructs and sends this; `SleepContext.js` parses and consumes it.

### Full Schema

```json
{
  "sessionId":   "9b87cfb7-5159-4eed-9722-edecd5d4de3f",
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

`sleep/background` messages carry `sessionId` and `publishedAt` but **no `seq`**;
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

The Python publisher applies the following threshold logic to each sensor reading:

| Condition | Tier | Topic | QoS |
|---|---|---|---|
| SpO2 < 90% | Critical | `sleep/critical` | 2 |
| SpO2 90–94% | Important | `sleep/important` | 1 |
| SpO2 ≥ 95% (active reading) | Normal | `sleep/normal` | 0 |
| Periodic stats flush | Background | `sleep/background` | 0 |

Additional signals (heart rate outside 40–100 BPM, HRV < 20 ms) may supplement SpO2 for tier escalation, but SpO2 is the primary discriminator.

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

---

## sleep_data.csv Schema

The CSV file is read by the Python classifier and replayed row-by-row to simulate a live sensor session.

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

## sleep_data_realistic.csv Schema

The dataset used for live demos and DB ingestion. It is generated by
`generate_data.py` and is simpler and self-consistent (no duplicate headers).

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
  critical:    { count: number, latency: number },
  important:   { count: number, latency: number },
  normal:      { count: number, latency: number },
  background:  { count: number, latency: number },
}
```

`connected` is set to `true` on the first received message and never reset (see known limitations in README). `latency` is a static value looked up from `data.qos`, not a measured round-trip time:

| `data.qos` | Latency shown |
|---|---|
| 2 | 12 ms |
| 1 | 28 ms |
| 0 | 45 ms |
