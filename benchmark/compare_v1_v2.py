#!/usr/bin/env python3
"""Compare the frozen v1 study with the AF_UNIX-socketpair v2 study.

v1 is the stock-paho baseline. v2 patches paho's cross-thread wake-up
socketpair to AF_UNIX. Wire counters are not directly comparable: v1 has no
idle sample and its counters may include unquantified background loopback
traffic from the agent session. The clean-wire table is therefore marked
cross-session and indicative only.

Usage:
    python3 benchmark/compare_v1_v2.py
    python3 benchmark/compare_v1_v2.py --out-dir /tmp/compare
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from analyze_benchmark import (
    BENCH_DIR, TIERS, analyse_run, die, load_study, published_qos, read_run,
)

METHOD_KEYS = [
    "dataset_sha256", "classifier_sha256", "dataset_rows",
    "pacing_interval_s", "warmup_rows", "background_every",
    "tier_qos", "netem", "outage_seconds", "outage_fractions", "mqtt",
]


def load_runs(directory, label):
    metas, cfg_hash = load_study(directory, label)
    config = metas[0]["config"]
    if "tier_qos" not in config:
        die(f"{label} config is missing tier_qos; refusing the comparison")
    flagged = sorted(
        meta["run_id"] for meta in metas
        if (meta.get("idle") or {}).get("flagged"))
    if flagged:
        die(f"{label} has {len(flagged)} flagged run(s) above the idle "
            f"threshold; delete and rerun them, do not compare them: "
            f"{', '.join(flagged)}")

    tier_rows, summaries = [], []
    for meta in metas:
        sent, recv = read_run(meta, directory)
        rows, summary, _ = analyse_run(meta, sent, recv)
        tier_rows.extend(rows)
        summaries.append(summary)
    return (metas, cfg_hash, config, pd.DataFrame(tier_rows),
            pd.DataFrame(summaries))


def check_comparable(v1_config, v2_config):
    for key in METHOD_KEYS:
        if v1_config.get(key) != v2_config.get(key):
            die(f"v1 and v2 differ on {key}: "
                f"{v1_config.get(key)!r} != {v2_config.get(key)!r}")
    if v2_config.get("socketpair") != "af_unix":
        die(f"v2 socketpair={v2_config.get('socketpair')!r}; expected 'af_unix'")
    if v1_config.get("socketpair") not in (None, "stock"):
        die(f"v1 socketpair={v1_config.get('socketpair')!r}; expected stock/absent")


def netem_latency(v1_tier, v2_tier):
    cols = ["experiment", "tier"]
    def agg(frame, prefix):
        data = frame[frame["scenario"] == "netem"]
        out = data.groupby(cols)["lat_median_ms"].agg(
            n_runs="count", median="median", minimum="min", maximum="max"
        ).reset_index()
        return out.rename(columns={
            "n_runs": f"{prefix}_n_runs",
            "median": f"{prefix}_median_ms",
            "minimum": f"{prefix}_min_ms",
            "maximum": f"{prefix}_max_ms",
        })

    merged = agg(v1_tier, "v1").merge(agg(v2_tier, "v2"), on=cols, how="outer")
    merged["qos"] = [published_qos(row.experiment, row.tier)
                     for row in merged.itertuples()]
    merged["delta_ms"] = merged["v2_median_ms"] - merged["v1_median_ms"]
    merged["tier"] = pd.Categorical(merged["tier"], TIERS, ordered=True)
    return merged.sort_values(["experiment", "tier"]).reset_index(drop=True)


def clean_wire(v1_runs, v2_runs):
    def agg(frame, prefix):
        data = frame[frame["scenario"] == "clean"]
        out = data.groupby("experiment").agg(
            n_runs=("run_id", "count"),
            bytes_per_msg_median=("wire_bytes_per_msg", "median"),
            bytes_per_msg_min=("wire_bytes_per_msg", "min"),
            bytes_per_msg_max=("wire_bytes_per_msg", "max"),
            packets_per_msg_median=("wire_packets_per_msg", "median"),
            packets_per_msg_min=("wire_packets_per_msg", "min"),
            packets_per_msg_max=("wire_packets_per_msg", "max"),
            primary=("wire_primary", lambda s: ",".join(
                sorted({str(v) for v in s.dropna()})) or "raw"),
        ).reset_index()
        return out.rename(columns={
            "n_runs": f"{prefix}_n_runs",
            "bytes_per_msg_median": f"{prefix}_bytes_per_msg_median",
            "bytes_per_msg_min": f"{prefix}_bytes_per_msg_min",
            "bytes_per_msg_max": f"{prefix}_bytes_per_msg_max",
            "packets_per_msg_median": f"{prefix}_packets_per_msg_median",
            "packets_per_msg_min": f"{prefix}_packets_per_msg_min",
            "packets_per_msg_max": f"{prefix}_packets_per_msg_max",
            "primary": f"{prefix}_primary",
        })

    merged = agg(v1_runs, "v1").merge(agg(v2_runs, "v2"),
                                     on="experiment", how="outer")
    merged["delta_bytes_per_msg"] = (merged["v2_bytes_per_msg_median"]
                                     - merged["v1_bytes_per_msg_median"])
    return merged.sort_values("experiment").reset_index(drop=True)


def fmt(value, digits=2):
    if pd.isna(value):
        return "—"
    return f"{value:.{digits}f}"


def markdown(v1_hash, v2_hash, v1_config, v2_config, netem, wire):
    lines = [
        "# v1 vs v2 benchmark comparison",
        "",
        f"- v1: `{v1_hash[:16]}` (method {v1_config.get('method_version')}, "
        f"socketpair={v1_config.get('socketpair', 'stock/absent')})",
        f"- v2: `{v2_hash[:16]}` (method {v2_config.get('method_version')}, "
        f"socketpair={v2_config.get('socketpair')}, "
        f"paho={v2_config.get('paho_mqtt')})",
        "",
        "## Netem latency",
        "",
        "Per-run tier medians, then median [min–max] across runs. "
        "v1 and v2 are separate sessions.",
        "",
        "| Exp | Tier | QoS | v1 median (ms) [min–max] | v2 median (ms) [min–max] "
        "| Δ v2−v1 (ms) | runs v1/v2 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in netem.itertuples():
        lines.append(
            f"| {row.experiment} | {row.tier} | {row.qos} "
            f"| {fmt(row.v1_median_ms)} [{fmt(row.v1_min_ms)}–{fmt(row.v1_max_ms)}] "
            f"| {fmt(row.v2_median_ms)} [{fmt(row.v2_min_ms)}–{fmt(row.v2_max_ms)}] "
            f"| {fmt(row.delta_ms)} | {int(row.v1_n_runs)}/{int(row.v2_n_runs)} |")
    lines += [
        "",
        "## Clean wire counters",
        "",
        "**Cross-session, indicative only.** v1 has no idle-loopback sample, "
        "so its counters may include unquantified background traffic from the "
        "agent/IDE session. v2 stores raw and idle-corrected counters; raw is "
        "primary. A flagged v2 run (idle above threshold) must be deleted and "
        "rerun, not corrected. Sensitivity wire counters (1 msg/s) are not "
        "quoted here.",
        "",
        "| Exp | v1 B/msg [min–max] | v2 B/msg [min–max] | Δ B/msg "
        "| v1 pkt/msg | v2 pkt/msg | v2 primary | runs v1/v2 |",
        "|---|---:|---:|---:|---:|---:|---|---:|",
    ]
    for row in wire.itertuples():
        lines.append(
            f"| {row.experiment} "
            f"| {fmt(row.v1_bytes_per_msg_median)} "
            f"[{fmt(row.v1_bytes_per_msg_min)}–{fmt(row.v1_bytes_per_msg_max)}] "
            f"| {fmt(row.v2_bytes_per_msg_median)} "
            f"[{fmt(row.v2_bytes_per_msg_min)}–{fmt(row.v2_bytes_per_msg_max)}] "
            f"| {fmt(row.delta_bytes_per_msg)} "
            f"| {fmt(row.v1_packets_per_msg_median)} "
            f"| {fmt(row.v2_packets_per_msg_median)} "
            f"| {row.v2_primary} | {int(row.v1_n_runs)}/{int(row.v2_n_runs)} |")
    lines += [
        "",
        "The netem table is a session-level comparison, not a paired test: "
        "v1 and v2 were not interleaved.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-dir", default=str(BENCH_DIR / "results"))
    parser.add_argument("--v2-dir", default=str(BENCH_DIR / "results_v2"))
    parser.add_argument("--out-dir",
                        default=str(BENCH_DIR / "comparison_v1_v2"))
    args = parser.parse_args(argv)

    v1_dir, v2_dir = Path(args.v1_dir), Path(args.v2_dir)
    out_dir = Path(args.out_dir)
    (v1_metas, v1_hash, v1_config, v1_tier,
     v1_runs) = load_runs(v1_dir, "v1")
    (v2_metas, v2_hash, v2_config, v2_tier,
     v2_runs) = load_runs(v2_dir, "v2")
    check_comparable(v1_config, v2_config)

    netem = netem_latency(v1_tier, v2_tier)
    wire = clean_wire(v1_runs, v2_runs)

    out_dir.mkdir(parents=True, exist_ok=True)
    netem.to_csv(out_dir / "v1_vs_v2_netem.csv", index=False)
    wire.to_csv(out_dir / "v1_vs_v2_clean_wire.csv", index=False)
    report = markdown(v1_hash, v2_hash, v1_config, v2_config, netem, wire)
    (out_dir / "v1_vs_v2.md").write_text(report)

    print(f"v1: {len(v1_metas)} runs, hash {v1_hash[:16]}")
    print(f"v2: {len(v2_metas)} runs, hash {v2_hash[:16]}")
    print(f"\n{report}")
    print(f"Wrote comparison files to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
