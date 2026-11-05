# MQTT QoS benchmark (research harness)

This directory contains the measurement harness that validates the MQTT tiering
claims with real traffic instead of the retired simulation (see §1 below). It
measures **one-way publish-to-subscriber latency**, **delivery**, **publisher-side acknowledgement time**, **outage
recovery** and **wire overhead** for the three QoS policies used in the project.

The harness is deliberately separate from the app's "Estimated latency (RTT/2)"
badge. The badge is a demo estimate computed from a round trip on a phone; it is
never a thesis result. This harness runs the publisher and the measuring
subscriber in **one process on one machine**, using the same monotonic clock, so
latency is simply `t1 - t0`. There is no RTT/2, no clock synchronisation error
and no simulated loss.

Nothing here changes the app, the ingest worker or the database.

---

## 1. History: the retired simulation

The original `evaluation.py` was a *simulation*, not a measurement (hard-coded
latency constants, unseeded random loss, 100 of 526 rows, wall-clock timing).
Its outputs must **not be cited** — that includes the +16.7 percentage-point
Critical-delivery claim and the 33 ms / 12-28-45 ms figures.

The repository now ships the measured harness only. The complete v1 history —
why the simulation was invalid, the frozen v1 results, the v1→v2 comparison
tables and the calibration evidence — lives in
[`docs/BENCHMARK_V1_HISTORY.md`](../docs/BENCHMARK_V1_HISTORY.md), preserved at
the git tag `benchmark-v1-frozen`.

---

## 2. Research questions

1. **A vs B** — does assigning QoS by clinical tier preserve important
   messages when the link is impaired?
2. **C vs A** — what does *uniform* QoS 2 cost in latency and wire overhead, and
   why is "just use QoS 2 for everything" not automatically the right policy?
3. **Outage** — when the subscriber disappears for 5 seconds, which messages
   survive, and at what latency?
4. **Pacing** — do the conclusions change if the publisher sends at 1 msg/s
   instead of 10 msg/s?
5. **Overhead** — how many extra bytes/packets per message does each policy
   cost on the loopback link?

---

## 3. Experiments

| ID | Policy | Topic | QoS per message |
|---|---|---|---|
| **A** | uniform baseline | `bench/uniform` | 0 for every message |
| **B** | clinical tiers | `bench/critical`, `bench/important`, `bench/normal`, `bench/background` | Critical 2, Important 1, Normal 0, Background 0 |
| **C** | uniform "safe" baseline | `bench/uniform` | 2 for every message |

The measuring subscriber always connects with its own client ID
(`bench-sub-<run_id>`) and subscribes to `bench/#` at **QoS 2** in every
experiment. The subscription requests the maximum; it does not upgrade the QoS
that the publisher chose. All benchmark topics are under `bench/`, so the app
and the ingest worker (which subscribe to `sleep/#` and `session/#`) never
record benchmark traffic.

Tier assignment is done with the shared rules module
(`python-publisher/tier_rules.py`), evaluated in strict order — the
benchmark runner and the production publisher use the exact same code:

- SpO2 < 90 OR HR < 40 OR HR > 100 → **Critical** (QoS 2 in B)
- 90 ≤ SpO2 < 95 OR 40 ≤ HR < 50 OR 90 < HR ≤ 100 OR HRV < 20 → **Important** (QoS 1 in B)
- 95 ≤ SpO2 ≤ 100 AND 50 ≤ HR ≤ 90 AND HRV ≥ 20 → **Normal** (QoS 0 in B)
- session statistics → **Background** (QoS 0 in B, emitted every 10 readings,
  mirroring the production publisher)

The live dataset contains **57 Critical / 191 Important / 278 Normal** readings
(10.8 % / 36.3 % / 52.9 %), SpO2 range 82.0–98.3.

### Why QoS 2 is expected to be slower

`tc netem` on `lo` delays every link traversal. A QoS 0 message traverses the
link twice before delivery (publisher → broker → subscriber). QoS 2 adds
PUBREC/PUBREL/PUBCOMP control traversals, and Mosquitto forwards the message
only after the QoS 2 handshake progresses, so the expected message latency is
roughly **two to three times** the QoS 0 value on the same impaired link.

Expected bands under the netem scenario (used as *soft* checks, never forced):

- QoS 0 / 1: **30–80 ms** median one-way
- QoS 2: **70–160 ms** median one-way
- smell test: QoS 2 median / QoS 0 median **≥ 1.5**

Under clean loopback the expectation is sub-millisecond to a few milliseconds,
with QoS 2 highest. TCP retransmits hide the 2 % netem packet loss at the
application layer, so the netem scenario is a *latency* test, not a loss test.
The outage scenario is the loss test.

---

## 4. Scenarios

| Scenario | What happens | Applied to |
|---|---|---|
| `clean` | no impairment | all experiments |
| `netem` | `sudo tc qdisc add dev lo root netem delay 25ms 10ms loss 2%` | all experiments |
| `outage-p25` | subscriber disconnects for 5 s at 25 % of the measured readings | all experiments |
| `outage-p50` | same, at 50 % | all experiments |
| `outage-p75` | same, at 75 % | all experiments |

Outage procedure: normal MQTT `DISCONNECT` (session survives, broker queues
QoS 1/2), wait 5 s, reconnect with the **same client ID** and
`clean_start=False`. The driver disconnects **before** publishing the first
message of the audited window, so the nominal window starts at the stated row.
The reconnect is checked with `session_present`; a missing session is a hard
failure. Messages are still published throughout the outage, so the window
contains real traffic. Actual window membership is still decided from the
monotonic disconnect/reconnect timestamps. `queue_qos0_messages` is false on this
broker, so QoS 0 traffic published while the subscriber is away is discarded,
exactly as it would be in production.

netem is applied only for netem runs and is always removed:
after each run, on SIGINT/SIGTERM/SIGHUP, and by preflight if an earlier crash
left it behind. The exact command, broker version and resolved broker settings
are stored in every run's metadata.

### The outage window is deterministic — read the audit first

The dataset order is fixed, so the 50-reading window at 25 %, 50 % and 75 % is
the same in every repetition. The harness prints this audit before a matrix and
stores it as `results/window_audit.json`:

| Position | Rows | Critical | Important | Normal |
|---|---|---|---|---|
| 25 % | 132–181 | **0** | 9 | 41 |
| 50 % | 263–312 | **2** | 14 | 34 |
| 75 % | 394–443 | **15** | 22 | 13 |

Across all 477 possible 50-reading windows the critical count ranges 0–21
(mean 5.8); 108 windows contain no critical reading at all. This is a property
of the dataset, not of the protocol, and it is why the 25 % outage is kept:
it honestly shows a window where no clinical-tier message was at stake.

The three positions expose **17 distinct Critical readings** in total. With five
repetitions **per experiment**, one experiment contributes **85 Critical-message
exposures** (255 attempts across A, B and C). None of them are independent
samples: the same 17 messages are replayed. Outage results are therefore framed
as *protocol validation on clinical tiers*, not as a population-level survival
estimate.

---

## 5. Matrix and pacing

**Main study** — 3 experiments × 5 conditions × 5 repetitions = **75 runs**.
Each run publishes the full **526-row** dataset once at **0.1 s** apart
(10 msg/s), plus 10 warm-up readings and 52 background-stat messages. Expected
wall time: ~100–120 minutes including drain and `$SYS` checks.

**Sensitivity study** — 3 experiments × 2 conditions (clean, netem) × 2
repetitions × the first **100 rows** at **1.0 s** apart = **12 runs**.
It answers "does the conclusion depend on publisher rate?" and is compared with
the main study restricted to the same first 100 rows.

**Warm-ups** — the first 10 rows are published before the measured window,
logged with `warmup=1` and excluded from every statistic. They are extra
messages, not part of the 526. The measured window starts after the subscriber
is subscribed and both clients are connected.

**Pacing** — publish times follow an absolute schedule
(`t_start + k × interval`), not `sleep(interval)` after each send, so scheduler
delays do not accumulate. Achieved mean interval is checked within ±5 % of the
configured value; achieved p95 is recorded in the run metadata.

**Order** — runs are repetition-major. Within a repetition, both the condition
order and the experiment order are rotated: repetition 1 runs clean → netem →
outage positions with A/B/C, repetition 2 runs netem → outage → clean with
B/C/A, repetition 3 starts at the 25 % outage, and so on (five-cycle rotation
of conditions, three-cycle rotation of experiments). Over the matrix every
experiment and every condition occupies early, middle and late slots, so a
machine-level drift (thermal, background load) cannot line up with one QoS
policy or one scenario.

**Same data, same order** — every run of a given row count uses the identical
CSV prefix, classifier and tier sequence. No randomisation of message content
or order.

---

## 6. Dataset and reconciliation

| | retired simulation | this harness (main) | sensitivity |
|---|---|---|---|
| File | `data/sleep_data.csv` | `data/sleep_data_realistic.csv` | same file, first 100 rows |
| Rows used | first 100 | all 526 | first 100 |
| Trigger | simulated | live MQTT | live MQTT |

`data/sleep_data_realistic.csv`:

- 526 rows, sha256 `10e9df7fc38087b8caad72aebdee3975f752da3dd4bd5d79f7aa7aa1b3de64de`
  (the driver refuses to start if this file changes)
- 57 Critical / 191 Important / 278 Normal
- real payload size, same field names and value rounding as
  `python-publisher/publisher.py` (session id, patient id, seq, timestamps,
  tier, SpO2, heart rate, HRV, motion, reason, QoS, topic, stats)

**Reconciliation.** The thesis draft's numbers came from 100 simulated messages
drawn from the 630-row legacy file using a stale classifier. The live system
replays 526 messages from a different file through the real classifier and a
real broker. The old 100-row simulation and the new 526-row measurement are not
the same experiment; no old percentage should be carried over. The 1 msg/s
sensitivity study deliberately restricts both sides to the first 100 rows so
that pacing is the only difference.

**Background payload caveat.** Production background payloads have no `seq`
field. The harness adds one to background messages (readings already have it)
so that every message can be joined by `(run_id, seq)`. This affects ~1.5 % of
messages and adds a few bytes; it is recorded here rather than hidden.

---

## 7. Measurement, logs and statistics

### One clock, one direction

Both clients live in the driver process. For each message:

- `t0 = time.monotonic_ns()` immediately before `client.publish(...)`
- the subscriber records `t1 = time.monotonic_ns()` at the top of `on_message`
- latency = `(t1 - t0) / 1e6` ms — one-way, same clock
- `on_publish` records `ack = time.monotonic_ns()` when the broker's
  PUBACK (QoS 1) or PUBCOMP (QoS 2) is processed

There is **no RTT/2** anywhere in the harness, and no wall-clock arithmetic in
the latency path. Wall-clock ISO timestamps exist only for run bookkeeping.

### Logs

No file I/O happens inside MQTT callbacks. Two logs are written at the end of
each run, atomically:

`sent_<run_id>.csv`

```
run_id, experiment, scenario, position, rep, seq, row, kind, tier, qos,
t0_ns, ack_ns, warmup
```

`recv_<run_id>.csv`

```
run_id, seq, t1_ns
```

Join key: `(run_id, seq)`. QoS 1 retransmissions can produce repeated `seq`
rows in `recv`; analysis sorts by `t1_ns` and keeps the first delivery, then
reports the duplicate count. Delivery % is `joined / sent` for the same
measured message set. `warmup=1` rows are excluded before any statistic.
`kind=reading` rows carry a dataset `row`; `kind=background` rows do not.

Each run also writes `meta_<run_id>.json` **last**: status, config hash,
dataset/classifier hashes, netem command, achieved pacing, drain details,
outage timestamps and `session_present`, wire deltas, `$SYS` check, broker
version/config, MQTT settings, git/env info. A complete marker therefore only
exists after both logs are safely on disk.

### Statistics

All statistics are computed **per run first** (per tier × scenario × position):

- delivery = `received_unique / sent`
- median and p95 one-way latency
- median and p95 ack time; % of acks ≤ 50 ms
- for outage runs: the same metrics restricted to messages whose `t0` falls
  inside the actual monotonic `[t_off, t_on)` window, plus the recovery delay
  after reconnect (`t1 - t_on`) and the maximum in-window latency

The five repetitions are then summarised as **median [min–max]** across runs.
Messages from different repetitions are **not pooled** into a single confidence
interval, and no p-value is computed: the repetitions share the same fixed
dataset and the same machine. Run-level medians keep the repetition visible;
ranges show run-to-run spread honestly.

The outage window is defined from the actual disconnect/reconnect monotonic
timestamps, not from a nominal row index, so a slow reconnect is reflected in
the data.

### Acknowledgement gate

`on_publish` measures the broker's acknowledgement to the **publisher**, not
end-to-end delivery. It feeds one clinical check: on **clean** runs, Critical
(and Important) messages should be acked within **50 ms**. Under netem the same
number is reported as a finding but is **not** a gate — a slow ack is expected
and is part of the QoS 2 cost story.

### Wire overhead

`ip -j -s link show lo` is read twice per run: after warm-ups and after the
drain. The delta is divided by the number of measured messages (readings +
background). Only **TX** counters are used: loopback mirrors every packet into
RX, so counting both would double the value.

- **Clean runs are the headline number.** They include MQTT control traffic
  (CONNECT/SUBSCRIBE/PINGREQ) and TCP/IP headers.
- **Loopback counters are host-wide.** Every process using `lo` during the
  measured window contributes, not just the benchmark. Close the agent/IDE and
  all other localhost services during runs; compare A/B/C relatively rather
  than treating the values as absolute energy or per-connection costs.
- **Historical (v1) wire counts are not clean background measurements.** The v1
  study had no idle-loopback sample, so its counts may include unquantified
  background traffic from the agent/IDE session. **Do not quote sensitivity
  (1 msg/s) wire counters at all** — the fixed background rate dominates that
  comparison. The v1 numbers are preserved in
  [`docs/BENCHMARK_V1_HISTORY.md`](../docs/BENCHMARK_V1_HISTORY.md) with this
  caveat attached.
- **The v2 session records an idle sample.** A 10 s preflight and a 5 s per-run
  sample use the same `ip -j -s link show lo` counters as the wire buckets
  above. Raw wire counters are primary;
  idle-corrected counters are stored for diagnosis only. A run whose idle rate
  exceeds the threshold (packets/s) is **flagged**: it must be deleted and
  rerun, not
  corrected. Analysis hard-fails while any flagged run remains and reports the
  flagged count. The threshold is supplied with `--idle-max-pps`, derived from
  the user's measured idle baseline with the agent/IDE closed, and is recorded
  in `matrix.json` and every run's metadata. The per-run sample is taken after
  the previous run's teardown and `$SYS` watcher disconnect, and before the next
  clients connect or netem is applied.
- **netem/outage runs are reported separately.** Retransmissions and queued
  redelivery inflate their counters; they answer "what does this scenario cost
  on the wire", not "what does a message cost".
- This is not a battery or energy measurement.

---

## 8. Broker under test

Verified at recon time and re-checked at run time:

| Item | Value |
|---|---|
| Broker | Mosquitto `2.0.18-1build3`, native systemd (`/usr/sbin/mosquitto`) |
| Listener | `127.0.0.1:1883` (plus 9001); anonymous allowed |
| Containerised MQTT | none (the only container is `sleep-postgres` on 5432) |
| `persistence` | `true` |
| `per_listener_settings` | `false` (default) |
| `max_queued_messages` | 1000 (default) |
| `queue_qos0_messages` | `false` (default) |
| `max_inflight_messages` | 20 (default) |

The driver stores the raw `grep` of `/etc/mosquitto`, the active directives and
the resolved effective values in every run's metadata. The **resolved** values
are part of the config hash. Preflight refuses to start if MQTT appears to be
containerised, if a leftover netem qdisc cannot be removed, or if netem runs
were requested without working sudo.

**Scope of the claim.** These are measurements of a local native broker over
loopback, with netem as the impaired link. They do **not** include Wi-Fi, an
EC2 network path, the Garmin API, the gateway, the Expo app's JS thread, or
Postgres ingest. EC2 latency and jitter may differ; the same harness must be
re-run there before any cloud claim. The app's RTT/2 badge remains a demo
estimate and is not validated by this benchmark.

---

## 9. Session hygiene

MQTT v5 is used throughout:

- **Initial CONNECT (both clients):** `clean_start=True` with
  `SessionExpiryInterval=300`. This guarantees a fresh subscription and avoids
  inheriting a stale session from an aborted attempt with the same deterministic
  run ID. The session is persistent from that point on.
- **Outage reconnect (subscriber):** same client ID, `clean_start=False`,
  expiry 300. `session_present` must be true. QoS 1/2 messages queue at the
  broker and are delivered after reconnect; QoS 0 is dropped by configuration.
- **Final teardown (both clients):** DISCONNECT with
  `SessionExpiryInterval=0`, which deletes the session immediately. Nothing is
  left for Mosquitto's `persistent_client_expiration` to clean up later.
- **`$SYS` backstop:** `$SYS/broker/clients/inactive` is sampled between runs.
  It is compared with that run's **baseline**, not zero, because other clients
  may legitimately keep inactive persistent sessions. A value above baseline is
  a warning in the run metadata and in `sanity.txt`. The watcher is stopped
  after each run, before the next run's idle sample.
- **Crash safety:** SIGINT/SIGTERM/SIGHUP set an abort flag, remove netem and
  best-effort send expiry-0 DISCONNECTs. A hard kill can still leave a session
  for up to 300 s; preflight removes a leftover netem qdisc, and the next run
  with the same ID starts with `clean_start=True`, so stale state cannot enter
  the logs.

The `$SYS` watcher is a separate non-persistent client
(`bench-sys-<random>`), so it does not affect the inactive count. It is also
the source of the broker version string.

---

## 10. Resume and config hash

Run IDs are deterministic: `<experiment>-<condition>-r<rep>` (for example
`B-outage-p50-r03`). The driver:

- skips a planned run only if `meta_<run_id>.json` says `complete`, the
  config hash matches **and** both log files exist;
- reruns aborted/failed/partial runs;
- deletes that run's old files immediately before rerunning it;
- writes logs first and metadata last, each via `*.tmp` + atomic replace;
- refuses to mix methodologies: if complete runs in the directory carry a
  different config hash, it stops and lists them. `--force` reruns the planned
  runs under the new configuration (stale runs outside the plan are reported,
  not silently deleted).

**Hashed (methodology):** method version, runner script sha256, dataset sha256,
classifier sha256, dataset row count, pacing interval, socketpair mode
(`stock`/`af_unix`), paho-mqtt version, TCP_NODELAY flag, idle threshold
(`--idle-max-pps`), warm-up count, background cadence, netem command, outage
duration and positions, tier→QoS map, MQTT version/session/keepalive/inflight
settings, broker version and resolved queue/persistence settings.

**Not hashed (informational only):** git commit/branch/dirty flag, analysis
script hash, hostname, kernel, Python/pandas versions. Editing the analysis
or committing the runner does not invalidate already-collected runs; changing
the runner, dataset, classifier, socketpair mode, paho version, TCP_NODELAY,
idle threshold or broker does.

`results_quick_v2/` uses a different directory and sets `quick=true`; the
analysis script refuses any `results_quick*` directory. Quick runs are smoke
tests, never evidence.

---

## 11. Sanity gates

The analysis refuses to produce `summary.csv` or figures if a **hard gate**
fails. Soft failures are written to `sanity.txt` and reported as warnings; they
are findings, not automatically errors.

**Hard gates**

| Check | Why |
|---|---|
| Every planned run is present, complete and from one config hash | a missing or mixed run silently changes the comparison |
| Measured reading count equals the configured dataset rows | catches truncated publishes |
| No QoS 1 or QoS 2 message missing in any scenario | queued delivery is the protocol guarantee being tested |
| QoS 0 missing only in an outage window (plus ±2 boundary) | broker drops QoS 0 while the session is offline; the tolerance covers the asynchronous DISCONNECT landing |
| `session_present=true` after every outage reconnect | otherwise queued delivery did not happen |
| Every QoS>0 message has an ack timestamp | unmet publisher-side handshake |
| No received `seq` that is absent from the sent log | stale-session contamination |
| Achieved mean interval within ±5 % of configured | pacing sanity |
| No partial/quick/mixed directories | evidence integrity |
| No flagged runs (idle above threshold) | flagged runs must be deleted and rerun, not corrected |
| Each AF_UNIX A-netem run has `t0 -> on_publish` median < 2 ms | verifies the local wake-up path; pooled median is a note only |

**Soft expectations**

| Check | Expected |
|---|---|
| clean, all tiers | median < 8 ms |
| netem, QoS 0/1 | median 30–80 ms |
| netem, QoS 2 | median 70–160 ms |
| netem smell test | QoS 2 / QoS 0 median ≥ 1.5 |
| outage, QoS 0 in window | delivery ≤ 5 % |
| outage, QoS 1/2 in window | delivery ≥ 99 % |
| outage, recovered messages | report recovery delay (`t1 - t_on`) and max in-window latency; no gate |
| `$SYS/broker/clients/inactive` | not above that run's baseline |

Bands are evaluated per **published QoS**: Experiment A is QoS 0 for every
payload tier and Experiment C is QoS 2 for every payload tier. Only Experiment B
maps payload tier → QoS. This prevents a Critical-labelled QoS 0 message in A
from being judged against a QoS 2 expectation.

If a band is missed, the measured number is still reported. The harness never
adjusts a result to fit the expectation.

---

## 12. Running it

Prerequisites:

- Mosquitto running natively on `127.0.0.1:1883`
- `.venv-dev/` with paho-mqtt 2.x, pandas, numpy and matplotlib
- the live publisher and the ingest worker **stopped**; **close the agent/IDE
  and all other localhost services** during the B/C calibration and both v2
  matrices. Their loopback traffic is host-wide and would contaminate the
  idle check and wire counters
- working sudo for netem; the driver asks once, then uses `sudo -n` and
  refreshes the sudo timestamp in the background every four minutes so a long
  matrix does not lose netem permission mid-run
- an idle baseline measured from `ip -j -s link show lo` while those
  services are closed. The full main and sensitivity matrices require it as
  `--idle-max-pps` (packets/second); calibration may run record-only. The
  threshold is not guessed in the repository
- **flagged runs (idle above threshold) must be deleted and rerun, not
  corrected.** The analysis reports the flagged count and refuses to write
  summaries while any flagged run remains

```bash
# offline check: prints the deterministic outage windows, touches no broker
.venv-dev/bin/python benchmark/run_benchmark.py --audit-windows

# smoke test: 3 short clean runs in results_quick_v2/ (analysis refuses this dir)
.venv-dev/bin/python benchmark/run_benchmark.py --quick
```

B/C netem calibration (first v2 step; must pass before the matrices):

```bash
# 6 runs: A/B/C × stock/AF_UNIX, 1 msg/s, 150 rows, delay-only netem (~17 min)
# record-only calibration (idle threshold optional):
benchmark/calibration_v2/run_bc_netem.sh

# or enforce a threshold after measuring the idle baseline:
IDLE_MAX_PPS=<threshold pps> benchmark/calibration_v2/run_bc_netem.sh
```

The gate checks all six runs, A-patched `t0 -> on_publish` median `< 2 ms`, and
patched `t1-t0` median `<= stock + 5 ms` for QoS 0, 1 and 2. Three
vacuous-pass guards also apply: all six metas must show `netem.applied=true`
with the delay-only command; stock A `t0 -> on_publish` median must be
`>= 10 ms`; patched A `t1 - on_publish` median must be `35–70 ms`. If the
stock A artifact is below 10 ms, the gate is **INCONCLUSIVE**, not PASS. QoS 0
is sampled from A, QoS 1 from B/Important, QoS 2 from C; message counts are
printed with the per-QoS offset. A failed or inconclusive gate stops the rerun.
Full main and sensitivity matrices refuse to start without `--idle-max-pps`;
calibration and quick smoke runs may omit it. In the full matrices, the A
`t0 -> on_publish` `< 2 ms` check is applied **per A-netem run** (warm-up rows
excluded); the pooled median is a note only. `gate/gate.md` prints each stock
and patched median as `value (n=messages)` with the exact limit.

```bash
# v2 main study: 75 runs (~100-120 min), resumable, AF_UNIX by default
.venv-dev/bin/python benchmark/run_benchmark.py \
    --idle-max-pps <threshold pps>

# v2 pacing study: 12 runs at 1 msg/s into results_v2_sensitivity/
.venv-dev/bin/python benchmark/run_benchmark.py --sensitivity \
    --idle-max-pps <threshold pps>

# analysis (main + sensitivity, if present)
.venv-dev/bin/python benchmark/analyze_benchmark.py
```

Optional B-clean TCP_NODELAY test (no sudo, client-side only):

```bash
.venv-dev/bin/python benchmark/run_benchmark.py \
    --experiments B --scenarios clean --reps 3 --tcp-nodelay \
    --out-dir benchmark/results_v2_tcp_nodelay \
    --idle-max-pps <threshold pps>
```

A negative TCP_NODELAY result does **not** rule out broker-side effects: the
flag only removes Nagle on the two benchmark clients, not on Mosquitto or the
TCP stack. Keep it as a diagnostic, not as evidence against a broker-side
queueing explanation.

If the process is interrupted, rerun the **same** command: completed runs with
the same config hash are skipped, partial runs are redone. Use `--force` only
when you intend to overwrite every planned run under the current methodology.
After an unclean exit, verify teardown before restarting:

```bash
tc qdisc show dev lo        # must not contain "netem"
```

The frozen v1 study is no longer analysed in-repo; see
`docs/BENCHMARK_V1_HISTORY.md` and the `benchmark-v1-frozen` tag instead.

```bash
# restore the full frozen v1 state into the working tree if ever needed:
git checkout benchmark-v1-frozen -- benchmark/
```

Other analysis flags: `--no-sensitivity`, `--no-plots`, `--main-dir`,
`--sensitivity-dir` (for archived or alternative result directories). Runner
flags: `--socketpair stock` (stock calibration mode), `--netem-delay-only`,
`--out-dir`, `--idle-max-pps`, `--calibration`.

---

## 13. Outputs

```text
benchmark/results_v2/
  matrix.json                 plan, config, idle threshold/preflight, broker,
                              env, status
  window_audit.json           deterministic outage-window composition
  sent_*.csv  recv_*.csv  meta_*.json
  summary.csv                 per experiment × scenario × position × tier,
                              median [min-max] across repetitions
  summary_per_run.csv         per-run tier metrics (repetition visible)
  runs.csv                    run-level counts, pacing, wire, session checks
  outage_critical.csv         Critical-tier delivery, recovery max (t1 - t_on)
                              and max in-window latency per outage position
  wire_summary.csv            TX bytes/packets per message, by experiment/scenario
  sensitivity_comparison.csv  first-100-rows comparison, 0.1 s vs 1.0 s
  sanity.txt                  hard gates, soft warnings, notes
  analysis_meta.json          inputs, hashes, environment, flagged-run count, plot status
  figures/
    fig_latency_ecdf_{clean,netem,outage}.png
    fig_latency_box_clean_netem.png
    fig_delivery_clean_netem.png
    fig_outage_recovery.png
    fig_outage_timeline.png
    fig_ack_times.png
    fig_wire_clean.png
    fig_sensitivity.png

benchmark/results_v2_sensitivity/    same layout, 1 msg/s, not mixed with main
benchmark/results_quick_v2/          smoke test only; analysis refuses it
benchmark/results_v2_tcp_nodelay/    optional B/clean diagnostic
benchmark/calibration_v2/bc_netem/
  stock/  af_unix/                   six calibration runs and metas
  gate/gate.md  gate.csv            B/C gate decision
  gate/per_qos.csv  gate/per_tier.csv
```

`results_v2_sensitivity/` has the same log/meta layout; its `summary.csv` is
not mixed with the main study.

---

## 14. How to report the numbers

- State the scenario first: clean, netem or outage. Never average across them.
- Report **median [min–max] across the five runs**, not a pooled CI.
- For netem, show QoS 0/1 and QoS 2 separately; the ratio is the apparent
  cost of exactly-once semantics. The old "provisional until the B/C offset
  is measured" caveat applies to the withdrawn v1 stock-paho numbers only —
  the v2 offsets are measured (§16).
- For outage, report the **in-window** delivery per tier and position, the
  recovery delay after reconnect (`t1 - t_on`), and the maximum in-window
  latency. Do not use a `p95 ≥ 4 s` gate: a message published late in the
  window has less than 4 s left before reconnect. The windows are
  deterministic; the 25 % window contains no Critical reading. Frame Critical
  recovery as protocol validation on the 17 distinct clinical messages, not as
  a survival probability.
- For v2, netem latencies carry no client-side wake-up offset (the AF_UNIX
  socketpair does not traverse `lo`) and the stock-vs-AF_UNIX wake-up cost was
  measured for every QoS level (22.9–24.0 ms — §16); the ~23 ms offset figures
  apply only to the withdrawn v1 stock-paho numbers
  (`docs/BENCHMARK_V1_HISTORY.md`). Clean values remain the most defensible
  absolutes; treat netem numbers as a relative comparison on an impaired link.
- Ack ≤ 50 ms belongs to clean runs; report netem ack numbers as a finding.
- Wire overhead belongs to clean runs; label netem/outage counters as inflated.
- The in-app RTT/2 badge is not a benchmark result.

---

## 15. Observed results (v2)

The canonical v2 study contains **75/75** complete main runs (one config hash,
`92495c94ffd3db92…`, method 2.0.0, AF_UNIX socketpair, idle threshold enforced)
and **12/12** complete sensitivity runs (hash `ab682dc10c28688f…`). The
analysis reports **0 hard-gate failures**, **0 flagged runs** (idle above
threshold) and **8 soft warnings**: one `$SYS` baseline note and seven netem
band misses, listed in `results_v2/sanity.txt` and discussed below.

All values are medians across the five main-study repetitions unless stated
otherwise. Delivery is unique subscriber receipt after joining on
`(run_id, seq)`. The publisher-side paho wake-up offset is measured, not
guessed (A/QoS 0 patched `t0 -> on_publish` 0.43 ms; per-QoS stock-vs-patched
offsets 22.9–24.0 ms — §16). The AF_UNIX values below carry no client-side
socketpair overhead on either side.

| Condition | Exp | QoS policy | Median one-way latency by tier (ms) | p95 by tier (ms) | Delivery |
|---|---|---|---|---|---|
| Clean | A | QoS 0 everywhere | C 0.84 · I 0.84 · N 0.84 · Bg 1.05 | 1.02–1.13 | 100 % |
| Clean | B | C 2 · I 1 · N 0 · Bg 0 | C 1.68 · I 0.86 · N 0.83 · Bg 1.07 | C 42.5 · I 1.12 · N 1.00 · Bg 41.6 | 100 % |
| Clean | C | QoS 2 everywhere | C 1.73 · I 1.73 · N 1.74 · Bg 2.07 | 2.03–2.23 | 100 % |
| Netem (offset calibrated — §16) | A | QoS 0 everywhere | C 62.2 · I 56.3 · N 57.3 · Bg 115.9 | 321–417 | 100 % |
| Netem (offset calibrated — §16) | B | C 2 · I 1 · N 0 · Bg 0 | C 282.7 · I 61.1 · N 59.3 · Bg 115.5 | C 721.7 · I 341.6 · N 357.2 · Bg 386.7 | 100 % |
| Netem (offset calibrated — §16) | C | QoS 2 everywhere | C 423.9 · I 428.2 · N 427.4 · Bg 478.2 | 854–961 | 100 % |

The netem **QoS 2 / QoS 0 median ratio (C/A) is 7.34** on the same impaired
loopback link. It passes the ≥ 1.5 smell test and exceeds the "two to three
times" rule of thumb: a QoS 2 message waits for PUBREC/PUBREL/PUBCOMP
traversals and, under uniform QoS 2 (C), queues behind every other
handshake in flight. The soft band misses (QoS 2 above the 70–160 ms band,
Background above the 30–80 ms band) are recorded as warnings, not failures.
The 10 msg/s netem values are a stress case; the 1 msg/s sensitivity study is
the production-like pacing check.

**Outage delivery and recovery.** Recovery is reported as `t1 - t_on` for
messages delivered after the subscriber reconnects. The per-run maximum
in-window latency across the delivered B/C messages was **3.4–4.9 s**; it is
the time from publish to receipt for the last message published before the
reconnect. The recovery columns give the median per-run maximum for the
indicated group; `[min–max]` is across the five repetitions.

| Position | Critical readings in window | A (QoS 0) | B (QoS 1/2) | C (QoS 2) | B recovery max (Critical; Important at 25 %) | C recovery max (Critical; all tiers at 25 %) |
|---|---|---|---|---|---|---|
| 25 % | 0 | 55 lost/run | 9/9 Important delivered | 55/55 delivered | 1.2 ms [0.9–1.4] | 5.1 ms [4.6–46.9] |
| 50 % | 2 | 55 lost/run | 16/16 Critical + Important delivered | 55/55 delivered | 42.0 ms [41.6–42.8] | 2.3 ms [2.2–3.1] |
| 75 % | 15 | 55 lost/run | 37/37 Critical + Important delivered | 55/55 delivered | 44.9 ms [44.3–45.2] | 4.8 ms [4.3–5.1] |

The 25 % window has no Critical reading by dataset construction, so its
Critical recovery column is not meaningful; B shows its Important QoS 1
messages and C shows all delivered tiers. B's QoS 0 Normal/Background traffic
was lost while offline (46, 39 and 18 messages at 25/50/75 %). A lost all 55
in-window QoS 0 messages at every position. The in-window QoS 1/2 delivery
rate was 100 % for both B and C.

**Sensitivity (1 msg/s, first 100 rows).** Clean medians were 0.78–1.70 ms.
Netem A medians were 52.2–55.2 ms; B/C QoS 2 medians were 154.2–230.2 ms.
Against the same rows of the 10 msg/s main study, the 1 msg/s netem B/C QoS 2
medians are 0.33–0.60× the main values, i.e. the 10 msg/s netem numbers are
substantially worse. The sensitivity plan covers only the clean and netem
scenarios (§5) — no outage runs at 1 msg/s, so no outage claim is made at
this pacing. The netem gap is a pacing/queueing effect, not evidence that
slower publishing is always faster; clean medians match the main study
(≈ 0.93–1.01×).

**Wire overhead (AF_UNIX canonical, no socketpair overhead).** Clean TX
counters were **A 995.8 B / 4.00 packets per message**, **B 1084.7 / 5.54**,
**C 1411.9 / 11.47**. These are host-wide loopback counters; the idle check
(`--idle-max-pps`) passed with 0 flagged runs, so no background-traffic
contamination was detected in the canonical session. For contrast, the
historical stock-paho v1 counters (A 1108 · B 1274 · C 1842 B/msg) included
the internal socketpair wake traffic — the paired calibration attributed
~120 / 196 / 419 B of it to the socketpair (§16) — and are kept as upper
bounds in [`docs/BENCHMARK_V1_HISTORY.md`](../docs/BENCHMARK_V1_HISTORY.md).
At 10 msg/s the wake bytes can coalesce or retransmit — this is a hypothesis —
so netem wire ratios remain provisional.

### Deviations from the plan

The planned outage soft check `p95 >= 4 s` was replaced **after the v1 data
was seen**, because it was mis-specified: messages published late in the 5 s
window wait less than 4 s before reconnect, so a low p95 does not mean poor
recovery. Recovery is now reported as `t1 - t_on` and maximum in-window
latency; the outage hard-gate failure count remained 0 in v1 and v2. The v2
analysis carries **7 netem band warnings** and one `$SYS` note (see the soft
list above).

---

## 16. Known limitation: paho wake-up offset

**Cause supported by source inspection and a runtime check.** The offset is
measured for A/QoS 0 in the v1 calibration (that plan covered A only) and — in
the v2 B/C calibration — directly for QoS 0, 1 and 2 (gate PASS, table below).

**Status:** v1 = stock paho (frozen at the `benchmark-v1-frozen` tag). The v2
harness patches paho's cross-thread socketpair to a non-blocking **AF_UNIX
socketpair** by default; `--socketpair stock` is retained for calibration. The
v2 B/C netem calibration **passed all gates** before the main matrices ran;
the stock inputs and v1 raw calibration outputs remain at the
`benchmark-v1-frozen` tag, run 2026-10-25 UTC (26 Oct local).

`paho-mqtt 2.1.0` uses an internal socketpair for cross-thread wake-ups.
Source inspection shows `_socketpair_compat()` creating **AF_INET TCP**
sockets and `_packet_queue()` sending a one-byte wake-up; a runtime check
found the sockets bound on `127.0.0.1`. With `tc netem` on `lo`, that
wake-up byte is delayed like the MQTT traffic, so each publish can carry an
extra loopback delay before the network loop thread wakes and writes the
packet. The v1 calibration isolated this for A/QoS 0 only; the v2 B/C
calibration (below) extends the measurement to QoS 1 and 2 as well.

(a) **A/QoS 0 netem offset: ~23 ms median, measured** (v1 socketpair
calibration, 2026-10-25; raw outputs are preserved at the
`benchmark-v1-frozen` tag). `t0 -> ack_ns` was **22.9 ms stock vs 0.3 ms
AF_UNIX** (median; p95 **32.8 vs 0.4 ms**). Stock pre values ranged from
15.9–33.3 ms and patched from 0.17–0.41 ms, so the distributions do not
overlap. The `ack_ns -> t1_ns` post phase was ~50 ms in both modes (median
50.5 vs 48.7 ms), so the offset is in the publisher-side wake-up, not the
delivery path. This is 20 readings from one run; its p95 is coarse and the
result applies to A/QoS 0 only. In clean runs, patched medians were only
~0.10–0.15 ms below stock, a small shift.

**B/C under netem were NOT tested in v1.** The v1 calibration netem plan
contains only A, and there are no B/C netem raw files. Do not apply the 23 ms
figure to B/C by assumption. **The v2 B/C calibration measured it directly**
(1 msg/s, delay-only netem, one stock run and one AF_UNIX run per
experiment; stock hash `292cfed0d9783371…`, AF_UNIX hash `7b6ee792d96d49dd…`,
gate PASS — see `calibration_v2/bc_netem/gate/gate.md`):

| QoS | Source | stock t1−t0 (ms) | patched t1−t0 (ms) | stock−patched offset |
|---:|---|---:|---:|---:|
| 0 | A | 76.43 | 52.49 | 23.94 |
| 1 | B/Important | 74.73 | 50.69 | 24.04 |
| 2 | C | 182.64 | 159.78 | 22.87 |

The offset is **≈ 23–24 ms for every QoS level** in this calibration, and the
A artifact reproduces (stock `t0 -> on_publish` 24.12 ms, patched 0.43 ms).
All six runs show `netem.applied=true` with the delay-only command and each
patched median is `<= stock + 5 ms`, so the AF_UNIX change does not slow the
measured path; it only uncovers the wake-up delay that the stock path
previously carried.

(b) **QoS 0 `t1 - ack` ≈ 51 ms is network-only, from the 1 msg/s A-netem runs
only.** It must not be generalised to 10 msg/s or to QoS 1/2. It is a
consistency check on the loopback path after paho reports the local send
complete (`on_publish`), not a universal network latency.

(c) **Clean wire counters.** The v2 canonical clean counts (A 995.8 B /
4.00 packets, B 1084.7 / 5.54, C 1411.9 / 11.47 per message) come from the
AF_UNIX session with the idle check enforced, so the wake-up socketpair does
**not** contribute to the counters by default: the AF_UNIX pair writes stay
off the loopback interface, unlike paho's stock AF_INET wake socket. No
background contamination above the threshold was detected. They are still
**host-wide loopback counters, not MQTT-only**, and
absolute counters vary between sessions. For the historical contrast: the
stock-paho counts (A 1108 · B 1274 · C 1842 B/msg) were **upper bounds** — the
paired stock-vs-AF_UNIX calibration attributed **120.1 / 196.1 / 418.8 bytes**
and **2.07 / 3.49 / 8.06 packets per message** to the socketpair itself,
**7–23 %** of the stock counts. At 10 msg/s, wake bytes can coalesce or
retransmit — this is a **hypothesis**, not a measured finding.

(d) **The B-clean ~42 ms tail is unexplained and is not the socketpair.** The
B-clean Critical and Background p95 tails are ~42 ms—the median across runs of
the per-run p95. Their median latencies are only ~1–2 ms; only ~10 specific
messages account for the tail. In the full stock-vs-AF_UNIX clean calibration,
Critical p95 was **42.8 ms stock vs 43.1 ms patched**, and Background **41.3
vs 41.6 ms**. The same six Critical sequences (**151, 261, 272, 481, 492,
503**) and four Background sequences (**119, 185, 438, 570**) account for the
>10 ms points in both modes and in all five canonical stock runs. The effect
is reproducible but its cause remains unexplained; do not attribute it to
paho.

(e) **Retired simulated figures.** The old **+16.7 percentage-point**
Critical-delivery claim and the **33 ms** latency figure are retired, together
with the 12 / 28 / 45 ms constants of the deleted `evaluation.py` simulation.
See [`docs/BENCHMARK_V1_HISTORY.md`](../docs/BENCHMARK_V1_HISTORY.md).

---

## 17. Limitations

- **One host, one loopback, one broker, one subscriber.** No Wi-Fi, no EC2, no
  fan-out, no TLS/auth, no database ingest, no phone JS thread.
- **Fixed dataset order.** Messages are correlated in time (a desaturation
  episode is a run of Critical rows), and the outage windows are deterministic.
  The 17 distinct Critical readings are not a random sample.
- **netem is an approximation.** Delay/jitter/loss on `lo` exercise queueing and
  the QoS handshake, but TCP retransmission hides packet loss; Wi-Fi roaming,
  signal fade and NAT timeouts are not modelled.
- **Accelerated main pacing.** The app publishes about one reading per second
  in production. The main study runs at 10 msg/s so that 75 full-dataset runs
  fit in one session; the 1 msg/s sensitivity study is the production-like
  pacing check on the first 100 rows. The main study is the stress case, not a
  claim about production cadence.
- **Ack is not delivery.** `on_publish` measures broker acknowledgement, not
  subscriber receipt; the subscriber join is the delivery measure.
- **Wire counters are not energy.** They include MQTT/TCP control traffic and
  are TX-only loopback counters. The v2 session records an idle sample and
  requires an `--idle-max-pps` threshold; runs above it are flagged and must
  be deleted and rerun, but the raw value stays primary.
- **TCP_NODELAY is a client-side diagnostic only.** A negative B-clean result
  does not rule out broker-side queueing: the flag changes Nagle on the two
  benchmark clients, not Mosquitto, its event loop, or the kernel's TCP stack.
- **Five repetitions.** Ranges are descriptive, not inferential. No p-values.
- **Background `seq` deviation** is the only payload-schema difference from
  production and is documented above.
- **The retired simulation** (`evaluation.py`) **is removed from the
  repository.** Its history is frozen at the `benchmark-v1-frozen` tag and
  summarised in `docs/BENCHMARK_V1_HISTORY.md`. Do not quote its outputs.

---

## 18. Files

| File | Role |
|---|---|
| `run_benchmark.py` | driver: publisher, measuring subscriber, `$SYS` watcher, netem, drain, resume, wire counters, AF_UNIX socketpair, idle preflight |
| `analyze_benchmark.py` | join/dedupe, per-run statistics, gates, outage and sensitivity analysis, plots |
| `calibration_v2/run_bc_netem.sh` | six-run B/C stock-vs-AF_UNIX delay-only calibration |
| `calibration_v2/analyze_bc_netem.py` | B/C gate and per-QoS offset report |
| *(v1 code and frozen outputs)* | removed from `main`; frozen at the `benchmark-v1-frozen` tag, history in `../docs/BENCHMARK_V1_HISTORY.md` |
| `README.md` | this document |
