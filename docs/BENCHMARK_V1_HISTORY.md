# Benchmark v1 — history and why it was superseded

The repository now ships **only the v2 (measured) benchmark**. The v1 code and
frozen outputs were removed from `main` on 2026-11-04 to keep one canonical
version; this document preserves the reasoning and the comparison tables so
the thesis narrative does not lose the evolution story.

## Where the v1 state is preserved

Everything deleted on that date is frozen in the git tag
**`benchmark-v1-frozen`** (commit `ae10e015cf1ce74fd6440320c9d087975390205b`).

Inspection commands (nothing is restored into the working tree):

```bash
git show benchmark-v1-frozen:benchmark/evaluation.py   # any single file
git show benchmark-v1-frozen:benchmark/results/		   # directory listing
```

Restoring the v1 state into the working tree (stages the old files):

```bash
git checkout benchmark-v1-frozen -- benchmark/
```

Relevant identifiers, for citation:

| Study | Config hash | Notes |
|---|---|---|
| v1 main (75 runs, 10 msg/s) | `bf3a74609898e4c1…` | stock paho, no idle threshold
| v1 sensitivity (12 runs, 1 msg/s) | `22ec36f2a9eb25db…` | stock paho
| v1 A-only socketpair calibration | run 2026-10-25 UTC | 6-lineage `paho_socketpair/` |
| v2 main (75 runs, 10 msg/s) | `92495c94ffd3db92…` | AF_UNIX socketpair, idle check |
| v2 sensitivity (12 runs, 1 msg/s) | `ab682dc10c28688f…` | AF_UNIX |
| v2 B/C calibration (stock hashes `292cfed0d9783371…`, AF_UNIX `7b6ee792d96d49dd…`) | 6 runs | gate: PASS |

## Why v1 (`evaluation.py`) was replaced

`evaluation.py` was a *simulation*, not a measurement: latency was a table of
hard-coded constants (12 / 28 / 45 ms), loss was unseeded `random` coin flips
(0 % / 2 % / 16 %), only 100 of the 526 dataset rows ran, pacing was
`sleep(0.05)`, the clock was wall time, and the embedded classifier was a
stale SpO2+HR+HRV copy. Delivery bookkeeping collected received messages but
never used them.

The famous "+16.7 percentage-point Critical delivery" figure was one unseeded
draw in which simulated Experiment A happened to lose 5 of 30 critical
messages while Experiment B lost none — a single simulation draw, not a
reproducible result. Along with it, the **33 ms** latency figure and the
12 / 28 / 45 ms constants are retired and must not be cited.

The v2 harness measures instead: one process hosts the publisher and the
measuring subscriber, latency is `t1 − t0` on one monotonic clock, loss is
real MQTT/TCP behaviour under `tc netem`, all 526 dataset rows run, and the
classifier is the shipped `python-publisher/tier_rules.py`. See
`benchmark/README.md` for the full methodology.

## Frozen v1 results (for the record, never for comparison citation)

The v1 study completed **75/75** main runs and **12/12** sensitivity runs with
0 hard-gate failures (12 soft netem-band warnings). With stock paho the netem
latencies (which include an uncorrected ~23 ms paho wake-up offset for QoS 0)
were A ≈ 87–148 ms, B Critical ≈ 366 ms, C ≈ 430–492 ms; delivery was 100 %
in every scenario and in-window QoS 1/2 delivery was 100 % during outages,
while all in-window QoS 0 traffic (55 messages/run) was lost in Experiment A's
session-less outage.

Clean wire counters from v1 were measured with stock paho and include the
internal socketpair wake traffic, so they are **upper bounds**:
**A 1108 B / 6.10 pkts, B 1274 / 8.93, C 1842 / 19.58 per message.**

## v1 → v2 comparison (cross-session, indicative only)

From the deleted `comparison_v1_v2/` tables. v1 and v2 are separate sessions,
not a paired test; treat deltas as indicative.

Netem one-way latency medians (ms), median [min–max] across runs:

| Exp | Tier | QoS | v1 | v2 | Δ v2−v1 |
|---|---|---:|---:|---:|---:|
| A | Critical | 0 | 88.94 [85.99–124.52] | 62.15 [55.84–73.00] | −26.79 |
| A | Important | 0 | 94.92 [86.97–109.36] | 56.28 [55.14–58.24] | −38.65 |
| A | Normal | 0 | 86.72 [82.02–94.36] | 57.25 [55.79–61.12] | −29.47 |
| A | Background | 0 | 148.03 [134.56–158.29] | 115.94 [107.91–118.21] | −32.09 |
| B | Critical | 2 | 366.21 [319.85–428.26] | 282.71 [255.94–331.78] | −83.49 |
| B | Important | 1 | 95.90 [87.78–132.34] | 61.06 [55.86–64.24] | −34.85 |
| B | Normal | 0 | 100.39 [87.01–124.42] | 59.33 [56.79–63.49] | −41.06 |
| B | Background | 0 | 142.34 [140.92–199.45] | 115.54 [109.65–121.24] | −26.80 |
| C | Critical | 2 | 457.26 [452.03–646.01] | 423.88 [396.71–482.33] | −33.38 |
| C | Important | 2 | 430.05 [419.14–443.59] | 428.15 [418.50–527.28] | −1.90 |
| C | Normal | 2 | 461.97 [436.98–518.05] | 427.42 [409.29–513.20] | −34.55 |
| C | Background | 2 | 491.94 [482.49–514.00] | 478.17 [450.24–531.42] | −13.77 |

Clean wire counters (cross-session, v1 stock = upper bound; v2 raw):

| Exp | v1 B/msg | v2 B/msg | Δ B/msg | v1 pkt/msg | v2 pkt/msg |
|---|---:|---:|---:|---:|---:|
| A | 1108.35 | 995.77 | −112.58 | 6.10 | 4.00 |
| B | 1273.81 | 1084.67 | −189.14 | 8.93 | 5.54 |
| C | 1841.79 | 1411.91 | −429.88 | 19.58 | 11.47 |

The latency improvements are consistent with removing the paho socketpair
wake-up offset (A) and with AF_UNIX wake-ups no longer contending with the
measured traffic; part of the wire reduction is exactly that socketpair
traffic, as the socketpair calibration showed.

## Historical calibration numbers (kept because they are method evidence)

- **A/QoS 0 netem wake-up offset (v1 calibration, 1 msg/s, delay-only):**
  stock `t0 → ack_ns` 22.9 ms vs AF_UNIX 0.3 ms (p95 32.8 vs 0.4 ms). Rerun in
  the v2 B/C calibration: stock A `t0 → on_publish` 24.12 ms reproduced, patched
  0.43 ms. Per-QoS offsets measured: **QoS 0 23.94 ms, QoS 1 24.04 ms,
  QoS 2 22.87 ms** (patched ≤ stock + 5 ms for all three; gate PASS).
- **Clean socketpair wire cost (paired v1 calibration):** removing the AF_INET
  wake socketpair reduced A/B/C by **120.1 / 196.1 / 418.8 B per message** and
  **2.07 / 3.49 / 8.06 packets per message** (stock minus patched).
- The B-clean ~42 ms p95 tail is reproducible but unexplained; v1 and v2 both
  show it with the same six Critical / four Background sequences, so it is not
  the socketpair.
