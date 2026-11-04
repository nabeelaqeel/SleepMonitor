# v1 vs v2 benchmark comparison

- v1: `bf3a74609898e4c1` (method 1.0.0, socketpair=stock/absent)
- v2: `92495c94ffd3db92` (method 2.0.0, socketpair=af_unix, paho=2.1.0)

## Netem latency

Per-run tier medians, then median [min–max] across runs. v1 and v2 are separate sessions.

| Exp | Tier | QoS | v1 median (ms) [min–max] | v2 median (ms) [min–max] | Δ v2−v1 (ms) | runs v1/v2 |
|---|---|---:|---:|---:|---:|---:|
| A | Critical | 0 | 88.94 [85.99–124.52] | 62.15 [55.84–73.00] | -26.79 | 5/5 |
| A | Important | 0 | 94.92 [86.97–109.36] | 56.28 [55.14–58.24] | -38.65 | 5/5 |
| A | Normal | 0 | 86.72 [82.02–94.36] | 57.25 [55.79–61.12] | -29.47 | 5/5 |
| A | Background | 0 | 148.03 [134.56–158.29] | 115.94 [107.91–118.21] | -32.09 | 5/5 |
| B | Critical | 2 | 366.21 [319.85–428.26] | 282.71 [255.94–331.78] | -83.49 | 5/5 |
| B | Important | 1 | 95.90 [87.78–132.34] | 61.06 [55.86–64.24] | -34.85 | 5/5 |
| B | Normal | 0 | 100.39 [87.01–124.42] | 59.33 [56.79–63.49] | -41.06 | 5/5 |
| B | Background | 0 | 142.34 [140.92–199.45] | 115.54 [109.65–121.24] | -26.80 | 5/5 |
| C | Critical | 2 | 457.26 [452.03–646.01] | 423.88 [396.71–482.33] | -33.38 | 5/5 |
| C | Important | 2 | 430.05 [419.14–443.59] | 428.15 [418.50–527.28] | -1.90 | 5/5 |
| C | Normal | 2 | 461.97 [436.98–518.05] | 427.42 [409.29–513.20] | -34.55 | 5/5 |
| C | Background | 2 | 491.94 [482.49–514.00] | 478.17 [450.24–531.42] | -13.77 | 5/5 |

## Clean wire counters

**Cross-session, indicative only.** v1 has no idle-loopback sample, so its counters may include unquantified background traffic from the agent/IDE session. v2 stores raw and idle-corrected counters; raw is primary. A flagged v2 run (idle above threshold) must be deleted and rerun, not corrected. Sensitivity wire counters (1 msg/s) are not quoted here.

| Exp | v1 B/msg [min–max] | v2 B/msg [min–max] | Δ B/msg | v1 pkt/msg | v2 pkt/msg | v2 primary | runs v1/v2 |
|---|---:|---:|---:|---:|---:|---|---:|
| A | 1108.35 [1106.00–1111.82] | 995.77 [995.53–997.34] | -112.58 | 6.10 | 4.00 | raw | 5/5 |
| B | 1273.81 [1261.70–1281.70] | 1084.67 [1084.43–1084.67] | -189.14 | 8.93 | 5.54 | raw | 5/5 |
| C | 1841.79 [1837.17–1844.66] | 1411.91 [1411.91–1412.15] | -429.88 | 19.58 | 11.47 | raw | 5/5 |

The netem table is a session-level comparison, not a paired test: v1 and v2 were not interleaved.
