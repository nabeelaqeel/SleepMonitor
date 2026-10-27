# B/C netem calibration gate

- stock config hash: `292cfed0d9783371`
- AF_UNIX config hash: `7b6ee792d96d49dd`
- 150 rows, 1 msg/s, delay-only netem, one run per experiment
- all six calibration runs complete: PASS (stock 3, AF_UNIX 3)

## Gate

| Criterion | stock | patched | Limit | Result |
|---|---:|---:|---:|:---|
| all 6 runs netem.applied == true and delay-only command | 3/3 runs (n=3) | 3/3 runs (n=3) | 6/6 | PASS |
| stock A t0 -> on_publish median >= 10 ms (artifact reproduced) | 24.12 ms (n=165) | — | >= 10.00 ms | PASS |
| patched A (t1 - on_publish) median between 35 and 70 ms | — | 52.06 ms (n=165) | 35.00-70.00 ms | PASS |
| A patched t0 -> on_publish median < 2 ms | 24.12 ms (n=165) | 0.43 ms (n=165) | 2.00 ms | PASS |
| QoS 0: patched t1−t0 median <= stock + 5 ms | 76.43 ms (n=165) | 52.49 ms (n=165) | stock + 5 = 81.43 ms | PASS |
| QoS 1: patched t1−t0 median <= stock + 5 ms | 74.73 ms (n=64) | 50.69 ms (n=64) | stock + 5 = 79.73 ms | PASS |
| QoS 2: patched t1−t0 median <= stock + 5 ms | 182.64 ms (n=165) | 159.78 ms (n=165) | stock + 5 = 187.64 ms | PASS |

**Overall gate: PASS**

## Per-QoS result (not a gate)

| QoS | Source | stock msg | patched msg | stock t1−t0 (ms) | patched t1−t0 (ms) | stock−patched offset (ms) | patched on_publish (ms) |
|---:|---|---:|---:|---:|---:|---:|---:|
| 0 | A | 165 | 165 | 76.43 | 52.49 | 23.94 | 0.43 |
| 1 | B/Important | 64 | 64 | 74.73 | 50.69 | 24.04 | 53.97 |
| 2 | C | 165 | 165 | 182.64 | 159.78 | 22.87 | 106.81 |

## Per-tier detail

| Exp | Tier | stock msg | patched msg | stock t1−t0 | patched t1−t0 | Δ | stock ack | patched ack |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| A | Background | 15 | 15 | 128.30 | 104.92 | -23.38 | 24.65 | 0.42 |
| A | Critical | 16 | 16 | 73.55 | 52.54 | -21.01 | 24.21 | 0.42 |
| A | Important | 64 | 64 | 75.53 | 52.04 | -23.49 | 23.76 | 0.43 |
| A | Normal | 70 | 70 | 76.33 | 50.78 | -25.55 | 24.01 | 0.43 |
| B | Background | 15 | 15 | 126.80 | 107.78 | -19.02 | 23.44 | 0.36 |
| B | Critical | 16 | 16 | 178.03 | 157.45 | -20.58 | 131.86 | 104.27 |
| B | Important | 64 | 64 | 74.73 | 50.69 | -24.04 | 75.21 | 53.97 |
| B | Normal | 70 | 70 | 73.73 | 52.71 | -21.02 | 21.95 | 0.45 |
| C | Background | 15 | 15 | 314.04 | 317.56 | +3.52 | 217.48 | 201.29 |
| C | Critical | 16 | 16 | 176.83 | 154.89 | -21.94 | 128.92 | 105.26 |
| C | Important | 64 | 64 | 181.42 | 157.03 | -24.40 | 129.38 | 102.99 |
| C | Normal | 70 | 70 | 180.33 | 159.03 | -21.30 | 128.91 | 106.60 |

QoS 0 comes from experiment A; QoS 1 from B/Important; QoS 2 from C. B's other tiers are shown for completeness but do not feed the gate.
