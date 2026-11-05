#!/usr/bin/env python3
"""
Analysis for the single-clock MQTT QoS benchmark.

Reads benchmark/results_v2/ (main study) and, if present,
benchmark/results_v2_sensitivity/ (1 msg/s pacing study). It refuses any
quick-smoke directory. Both are archived results from the original dataset
revision (flat-HRV fallback 35; their matrices record the pre-regeneration
dataset hash — see benchmark/README.md §6 for the hashes). Runs against the
regenerated dataset (real HRV) default to benchmark/results_v3* and must be
passed here explicitly.

Per run: join sent (t0, ack) with received (t1) on (run_id, seq),
deduplicate received rows by seq (QoS 1 retransmissions), compute
one-way latency = (t1 - t0) / 1e6 ms.

Across runs: median and [min-max] range over the five repetitions;
messages are never pooled into a single confidence interval.
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

BENCH_DIR = Path(__file__).resolve().parent
TIERS = ["Critical", "Important", "Normal", "Background"]

sys.path.insert(0, str(BENCH_DIR.parent / "publisher"))

from tier_rules import TIER_QOS  # noqa: E402


def safe_median(series):
    values = series.dropna()
    return values.median() if len(values) else float("nan")


def published_qos(experiment, tier, tier_qos=None):
    """A publishes everything at QoS 0, C everything at QoS 2; B is tiered.

    tier_qos is the tier→QoS map recorded in the study's own config
    (config["tier_qos"]); it falls back to the current tier_rules.py map
    for archives recorded before the map was embedded in the results.
    """
    if experiment == "A":
        return 0
    if experiment == "C":
        return 2
    return (tier_qos or TIER_QOS)[tier]
TIER_COLORS = {"Critical": "#d62728", "Important": "#ff7f0e",
               "Normal": "#2ca02c", "Background": "#7f7f7f"}


def die(msg, code=2):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load_study(directory, name):
    directory = Path(directory)
    if directory.name.startswith("results_quick"):
        die(f"refusing {directory.name} — smoke-test data is not evidence")
    metas = []
    for path in sorted(directory.glob("meta_*.json")):
        try:
            meta = json.loads(path.read_text())
        except Exception as exc:
            die(f"cannot read {path}: {exc}")
        if meta.get("quick"):
            die(f"{path} is marked quick=true; refusing the whole directory")
        if meta.get("status") != "complete":
            die(f"{path} has status={meta.get('status')}; refusing partial studies")
        metas.append(meta)
    if not metas:
        die(f"no complete runs found in {directory}")
    hashes = {m.get("config_hash") for m in metas}
    if len(hashes) != 1:
        detail = "\n".join(f"  {h[:16]}  {m['run_id']}" for h in sorted(hashes)
                           for m in metas if m.get("config_hash") == h)
        die(f"{name}: mixed config hashes — runs come from different methodologies:\n{detail}")
    return metas, hashes.pop()


def read_run(meta, directory):
    run_id = meta["run_id"]
    sent_path = Path(directory) / f"sent_{run_id}.csv"
    recv_path = Path(directory) / f"recv_{run_id}.csv"
    if not sent_path.exists() or not recv_path.exists():
        die(f"missing logs for {run_id} in {directory}")
    sent = pd.read_csv(sent_path)
    recv = pd.read_csv(recv_path)
    sent["seq"] = pd.to_numeric(sent["seq"]).astype("int64")
    sent["t0_ns"] = pd.to_numeric(sent["t0_ns"]).astype("int64")
    sent["qos"] = pd.to_numeric(sent["qos"]).astype(int)
    sent["warmup"] = pd.to_numeric(sent["warmup"]).astype(int)
    sent["row"] = pd.to_numeric(sent["row"], errors="coerce")
    sent["ack_ns"] = pd.to_numeric(sent["ack_ns"], errors="coerce")
    recv["seq"] = pd.to_numeric(recv["seq"]).astype("int64")
    recv["t1_ns"] = pd.to_numeric(recv["t1_ns"]).astype("int64")
    return sent, recv


def analyse_run(meta, sent, recv):
    """Return (per-run tier metrics, per-run summary, message frame)."""
    run_id = meta["run_id"]
    measured = sent[sent["warmup"] == 0].copy()
    unique = recv.sort_values("t1_ns").drop_duplicates("seq", keep="first")
    duplicates = int(len(recv) - len(unique))
    merged = measured.merge(unique, on="seq", how="left")
    merged["delivered"] = merged["t1_ns"].notna()
    merged["latency_ms"] = (merged["t1_ns"] - merged["t0_ns"]) / 1e6
    merged["ack_ms"] = (merged["ack_ns"] - merged["t0_ns"]) / 1e6

    outage = meta.get("outage") or {}
    t_off, t_on = outage.get("t_off_ns"), outage.get("t_on_ns")
    if t_off is not None and t_on is not None:
        merged["in_window"] = (merged["t0_ns"] >= t_off) & (merged["t0_ns"] < t_on)
        merged["recovery_ms"] = (merged["t1_ns"] - t_on) / 1e6
    else:
        merged["in_window"] = False
        merged["recovery_ms"] = np.nan
    merged.loc[~merged["in_window"], "recovery_ms"] = np.nan

    missing_ack_qos_positive = int(
        ((merged["qos"] > 0) & merged["ack_ns"].isna()).sum())
    missing = merged[~merged["delivered"]]
    missing_qos_positive = int((missing["qos"] > 0).sum())
    missing_qos0 = int((missing["qos"] == 0).sum())
    orphan_recv = int(len(set(unique["seq"]) - set(sent["seq"])))

    rows = []
    for tier in TIERS:
        g = merged[merged["tier"] == tier]
        if g.empty:
            continue
        delivered = g[g["delivered"]]
        acks = g["ack_ms"].dropna()
        gw = g[g["in_window"]]
        gw_delivered = gw[gw["delivered"]]
        gw_recovery = gw_delivered["recovery_ms"].dropna()
        rows.append({
            "run_id": run_id, "experiment": meta["experiment"],
            "scenario": meta["scenario"], "position": meta.get("position"),
            "rep": meta["rep"], "tier": tier,
            "n_sent": int(len(g)), "n_recv": int(len(delivered)),
            "delivery_pct": 100.0 * len(delivered) / len(g) if len(g) else np.nan,
            "lat_median_ms": delivered["latency_ms"].median(),
            "lat_p95_ms": (delivered["latency_ms"].quantile(0.95)
                           if len(delivered) else np.nan),
            "ack_median_ms": acks.median() if len(acks) else np.nan,
            "ack_p95_ms": acks.quantile(0.95) if len(acks) else np.nan,
            "ack_within_50pct": (100.0 * (acks <= 50).mean() if len(acks) else np.nan),
            "n_sent_in": int(len(gw)), "n_recv_in": int(len(gw_delivered)),
            "delivery_in_pct": (100.0 * len(gw_delivered) / len(gw)
                                if len(gw) else np.nan),
            "lat_in_max_ms": (gw_delivered["latency_ms"].max()
                              if len(gw_delivered) else np.nan),
            "recovery_median_ms": (gw_recovery.median()
                                   if len(gw_recovery) else np.nan),
            "recovery_max_ms": (gw_recovery.max()
                                if len(gw_recovery) else np.nan),
            "missing_ack_qos_positive": missing_ack_qos_positive,
            "orphan_recv": orphan_recv,
            "duplicates": duplicates,
        })

    reading_t0 = measured.loc[measured["kind"] == "reading", "t0_ns"].to_list()
    diffs = np.diff(np.asarray(reading_t0, dtype=np.int64)) / 1e6 if len(reading_t0) > 1 else np.array([])
    wire = meta.get("wire") or {}
    summary = {
        "run_id": run_id, "experiment": meta["experiment"],
        "scenario": meta["scenario"], "position": meta.get("position"),
        "rep": meta["rep"],
        "sent_measured": int(len(measured)),
        "sent_readings": int((measured["kind"] == "reading").sum()),
        "recv_unique": int(merged["delivered"].sum()),
        "recv_raw": int(len(recv)),
        "duplicates": duplicates,
        "invalid_payloads": int(meta["counts"].get("invalid_payloads", 0)),
        "missing_ack_qos_positive": missing_ack_qos_positive,
        "missing_qos_positive": missing_qos_positive,
        "missing_qos0": missing_qos0,
        "orphan_recv": orphan_recv,
        "achieved_mean_interval_ms": float(np.mean(diffs)) if len(diffs) else np.nan,
        "achieved_p95_interval_ms": float(np.percentile(diffs, 95)) if len(diffs) else np.nan,
        "outage_window_lost": int((merged["in_window"]
                                   & (merged["qos"] == 0)).sum()),
        "session_present": outage.get("session_present"),
        "outage_error": outage.get("error"),
        "sys_inactive": (meta.get("sys") or {}).get("inactive"),
        "sys_baseline": (meta.get("sys") or {}).get("baseline"),
        "sys_warned": bool((meta.get("sys") or {}).get("warned")),
        "wire_bytes_per_msg": wire.get("bytes_per_msg"),
        "wire_packets_per_msg": wire.get("packets_per_msg"),
        "wire_primary": wire.get("primary"),
        "idle_packets_per_s": (meta.get("idle") or {}).get("packets_per_s"),
        "idle_flagged": bool((meta.get("idle") or {}).get("flagged")),
        "started_at_utc": meta.get("started_at_utc"),
        "drain_seconds": (meta.get("drain") or {}).get("seconds"),
    }
    merged["run_id"] = run_id
    merged["experiment"] = meta["experiment"]
    merged["scenario"] = meta["scenario"]
    merged["position"] = meta.get("position")
    merged["rep"] = meta["rep"]
    return rows, summary, merged


def aggregate(runs):
    group = ["experiment", "scenario", "position", "tier"]
    frame = pd.DataFrame(runs)
    metrics = {
        "n_runs": ("run_id", "count"),
        "n_sent_median": ("n_sent", "median"),
        "n_recv_median": ("n_recv", "median"),
        "delivery_pct_median": ("delivery_pct", "median"),
        "delivery_pct_min": ("delivery_pct", "min"),
        "delivery_pct_max": ("delivery_pct", "max"),
        "lat_median_ms_median": ("lat_median_ms", "median"),
        "lat_median_ms_min": ("lat_median_ms", "min"),
        "lat_median_ms_max": ("lat_median_ms", "max"),
        "lat_p95_ms_median": ("lat_p95_ms", "median"),
        "lat_p95_ms_min": ("lat_p95_ms", "min"),
        "lat_p95_ms_max": ("lat_p95_ms", "max"),
        "ack_median_ms_median": ("ack_median_ms", "median"),
        "ack_median_ms_min": ("ack_median_ms", "min"),
        "ack_median_ms_max": ("ack_median_ms", "max"),
        "ack_within_50pct_median": ("ack_within_50pct", "median"),
        "ack_within_50pct_min": ("ack_within_50pct", "min"),
        "ack_within_50pct_max": ("ack_within_50pct", "max"),
        "n_sent_in_median": ("n_sent_in", "median"),
        "n_recv_in_median": ("n_recv_in", "median"),
        "delivery_in_pct_median": ("delivery_in_pct", "median"),
        "delivery_in_pct_min": ("delivery_in_pct", "min"),
        "delivery_in_pct_max": ("delivery_in_pct", "max"),
        "lat_in_max_ms_median": ("lat_in_max_ms", "median"),
        "lat_in_max_ms_min": ("lat_in_max_ms", "min"),
        "lat_in_max_ms_max": ("lat_in_max_ms", "max"),
        "recovery_median_ms_median": ("recovery_median_ms", "median"),
        "recovery_max_ms_median": ("recovery_max_ms", "median"),
        "recovery_max_ms_min": ("recovery_max_ms", "min"),
        "recovery_max_ms_max": ("recovery_max_ms", "max"),
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        agg = frame.groupby(group, dropna=False).agg(**metrics).reset_index()
    return frame, agg


def a_netem_on_publish_gate(frames, config, hard, notes):
    if config.get("socketpair") != "af_unix":
        notes.append("A-netem t0 -> on_publish gate skipped: "
                     f"socketpair={config.get('socketpair')!r}")
        return
    if config.get("netem") is None:
        notes.append("A-netem t0 -> on_publish gate skipped: netem not requested")
        return
    netem_frames = [f for f in frames if f["scenario"].iloc[0] == "netem"]
    a_frames = [f for f in netem_frames if f["experiment"].iloc[0] == "A"]
    if not a_frames:
        hard.append("A-netem: no A netem runs in the study")
        return

    pooled = []
    for frame in a_frames:
        run_id = frame["run_id"].iloc[0]
        if "warmup" in frame.columns:
            frame = frame[frame["warmup"] == 0]
        values = frame["ack_ms"].dropna()
        if values.empty:
            hard.append(f"{run_id}: no t0 -> on_publish samples")
            continue
        pooled.append(values)
        median = float(values.median())
        if median >= 2.0:
            hard.append(f"{run_id}: A-netem t0 -> on_publish median "
                        f"{median:.2f} ms (n={len(values)}) >= 2 ms")

    if pooled:
        all_values = pd.concat(pooled, ignore_index=True)
        notes.append(f"A-netem pooled t0 -> on_publish median: "
                     f"{all_values.median():.2f} ms (n={len(all_values)}, "
                     f"{len(pooled)} run(s) with samples; note only)")


def recorded_qos_mismatches(frames, tier_qos):
    """Find runs whose sent experiment-B qos values contradict the map."""
    findings = []
    for f in frames:
        sent_b = f[f["experiment"] == "B"]
        if sent_b.empty:
            continue
        expected = sent_b["tier"].map(tier_qos)
        if expected.isna().any():
            findings.append((str(sent_b["run_id"].iloc[0]),
                             "unknown tier in sent log"))
            continue
        mismatch = int((sent_b["qos"].astype(int)
                        != expected.astype(int)).sum())
        if mismatch:
            findings.append((str(sent_b["run_id"].iloc[0]), mismatch))
    return findings


def sanity_checks(run_df, agg, frames, config):
    hard, soft, notes = [], [], []
    interval_ms = config["pacing_interval_s"] * 1000.0
    expected_rows = config["dataset_rows"]
    # The study is judged by the tier→QoS map recorded at run time, not by
    # whichever map tier_rules.py defines today. Old archives are compared
    # against the recorded map (informationally below); the recorded map
    # itself is validated against the messages that were actually sent.
    tier_qos = config.get("tier_qos") or TIER_QOS
    if tier_qos != TIER_QOS:
        notes.append(f"recorded tier→QoS map {tier_qos} differs from the "
                     f"current tier_rules.py map {TIER_QOS}")
    for run_id, detail in recorded_qos_mismatches(frames, tier_qos):
        hard.append(f"{run_id}: {detail} violating the recorded tier→QoS map "
                    f"{tier_qos}")

    for row in run_df.itertuples():
        rid = row.run_id
        if row.sent_readings != expected_rows:
            hard.append(f"{rid}: {row.sent_readings} measured readings, expected {expected_rows}")
        if row.orphan_recv:
            hard.append(f"{rid}: {row.orphan_recv} received seqs absent from the sent log "
                        f"(stale session contamination?)")
        if row.missing_ack_qos_positive:
            hard.append(f"{rid}: {row.missing_ack_qos_positive} QoS>0 messages never acked")
        if row.invalid_payloads:
            hard.append(f"{rid}: {row.invalid_payloads} payloads without a numeric seq")
        if row.achieved_mean_interval_ms and abs(row.achieved_mean_interval_ms - interval_ms) / interval_ms > 0.05:
            hard.append(f"{rid}: achieved mean interval "
                        f"{row.achieved_mean_interval_ms:.1f} ms vs {interval_ms:.0f} ms")
        if row.missing_qos_positive:
            hard.append(f"{rid}: {row.missing_qos_positive} QoS>0 message(s) lost "
                        f"(queued delivery is part of the protocol)")
        tolerance = 2 if row.scenario == "outage" else 0
        allowed_qos0 = int(row.outage_window_lost)
        if not (max(0, allowed_qos0 - tolerance) <= int(row.missing_qos0)
                <= allowed_qos0 + tolerance):
            hard.append(f"{rid}: {row.missing_qos0} QoS 0 messages missing; "
                        f"expected {allowed_qos0} window loss(es) ±{tolerance} "
                        f"for the async DISCONNECT boundary")
        if row.scenario == "outage":
            if row.outage_error:
                hard.append(f"{rid}: outage worker failed: {row.outage_error}")
            elif row.session_present is not True:
                hard.append(f"{rid}: broker did not resume the persistent session "
                            f"(session_present={row.session_present})")
        if row.sys_warned:
            soft.append(f"{rid}: $SYS inactive={row.sys_inactive} above baseline "
                        f"{row.sys_baseline}")

    flagged = run_df[run_df["idle_flagged"]]
    notes.append(f"flagged runs (idle above threshold): {len(flagged)}")
    if len(flagged):
        flagged_ids = sorted(flagged["run_id"].tolist())
        hard.append(
            f"{len(flagged_ids)} flagged run(s) exceeded the idle threshold; "
            f"delete and rerun them, do not use corrected counters: "
            f"{', '.join(flagged_ids)}")

    clean = agg[agg["scenario"] == "clean"]
    for row in clean.itertuples():
        if row.lat_median_ms_median >= 8:
            soft.append(f"clean {row.experiment}/{row.tier}: median "
                        f"{row.lat_median_ms_median:.2f} ms exceeds 8 ms")

    netem = agg[agg["scenario"] == "netem"]
    for row in netem.itertuples():
        qos = published_qos(row.experiment, row.tier, tier_qos)
        if qos <= 1:
            low, high = 30.0, 80.0
        else:
            low, high = 70.0, 160.0
        if not (low <= row.lat_median_ms_median <= high):
            soft.append(f"netem {row.experiment}/{row.tier}: median "
                        f"{row.lat_median_ms_median:.1f} ms outside expected "
                        f"{low:.0f}-{high:.0f} ms for QoS {qos}")

    a_netem_on_publish_gate(frames, config, hard, notes)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        delivered = pd.concat([f[f["delivered"]] for f in frames],
                              ignore_index=True)
    med = (delivered.groupby(["scenario", "experiment"])["latency_ms"]
           .median().unstack("experiment"))
    if "netem" in med.index and "A" in med.columns and "C" in med.columns:
        ratio = med.loc["netem", "C"] / med.loc["netem", "A"]
        notes.append(f"netem QoS2/QoS0 median ratio (C/A): {ratio:.2f} "
                     f"(smell test expects >= 1.5)")
        if ratio < 1.5:
            soft.append(f"netem QoS2/QoS0 ratio {ratio:.2f} < 1.5 — inspect the link model")

    outage = agg[(agg["scenario"] == "outage") & agg["position"].notna()]
    for row in outage.itertuples():
        qos = published_qos(row.experiment, row.tier, tier_qos)
        if qos == 0:
            if row.delivery_in_pct_median > 5:
                soft.append(f"outage {row.experiment}/{row.tier}/p{int(row.position*100):02d}: "
                            f"QoS 0 delivery {row.delivery_in_pct_median:.1f}% > 5%")
        else:
            if row.delivery_in_pct_median < 99:
                soft.append(f"outage {row.experiment}/{row.tier}/p{int(row.position*100):02d}: "
                            f"QoS {qos} in-window delivery "
                            f"{row.delivery_in_pct_median:.1f}% < 99%")
    if len(outage):
        notes.append("outage recovery is reported as max(t1 - t_on) and max "
                     "in-window latency; there is no p95>=4s gate, because "
                     "messages published late in the window wait less than 4s")
    return hard, soft, notes


def outage_critical(frames, tier_df):
    records = []
    for (experiment, position), group in tier_df[tier_df["scenario"] == "outage"].groupby(
            ["experiment", "position"]):
        crit = group[group["tier"] == "Critical"]
        subset = pd.concat([
            f[(f["experiment"] == experiment) & (f["position"] == position)
              & (f["tier"] == "Critical") & (f["in_window"])]
            for f in frames if f["scenario"].iloc[0] == "outage"
        ], ignore_index=True)
        distinct = int(subset["row"].dropna().nunique())
        records.append({
            "experiment": experiment, "position": position,
            "distinct_critical_rows": distinct,
            "exposures": int(crit["n_sent_in"].sum()),
            "deliveries": int(crit["n_recv_in"].sum()),
            "delivery_in_pct_median": safe_median(crit["delivery_in_pct"]),
            "delivery_in_pct_min": crit["delivery_in_pct"].min(),
            "delivery_in_pct_max": crit["delivery_in_pct"].max(),
            "recovery_median_ms_median": safe_median(crit["recovery_median_ms"]),
            "recovery_max_ms_median": safe_median(crit["recovery_max_ms"]),
            "lat_in_max_ms_median": safe_median(crit["lat_in_max_ms"]),
            "reps": len(crit),
        })
    return pd.DataFrame(records)


def sensitivity_comparison(main_frames, sens_frames, rows=100):
    records = []
    for scenario in ("clean", "netem"):
        def per_run(frames):
            out = []
            for frame in frames:
                if frame["scenario"].iloc[0] != scenario:
                    continue
                subset = frame[(frame["delivered"]) & (frame["kind"] == "reading")
                               & (frame["row"] < rows)]
                for tier, group in subset.groupby("tier"):
                    out.append({"experiment": frame["experiment"].iloc[0],
                                "tier": tier,
                                "run_id": frame["run_id"].iloc[0],
                                "lat_median_ms": group["latency_ms"].median()})
            if not out:
                return pd.DataFrame(columns=["experiment", "tier", "run_id", "lat_median_ms"])
            df = pd.DataFrame(out)
            return df.groupby(["experiment", "tier"])["lat_median_ms"].agg(
                ["median", "min", "max", "count"]).reset_index()

        main_agg = per_run(main_frames)
        sens_agg = per_run(sens_frames)
        if main_agg.empty or sens_agg.empty:
            continue
        merged = main_agg.merge(sens_agg, on=["experiment", "tier"],
                                suffixes=("_main", "_sens"))
        for row in merged.itertuples():
            records.append({
                "scenario": scenario, "experiment": row.experiment, "tier": row.tier,
                "main_first100_median_ms": row.median_main,
                "main_min_ms": row.min_main, "main_max_ms": row.max_main,
                "main_runs": int(row.count_main),
                "sens_1s_median_ms": row.median_sens,
                "sens_min_ms": row.min_sens, "sens_max_ms": row.max_sens,
                "sens_runs": int(row.count_sens),
                "ratio_1s_over_0.1s": (row.median_sens / row.median_main
                                        if row.median_main else np.nan),
            })
    return pd.DataFrame(records)


def wire_summary(run_df):
    frame = run_df.dropna(subset=["wire_bytes_per_msg"])
    if frame.empty:
        return pd.DataFrame()
    return frame.groupby(["experiment", "scenario"]).agg(
        runs=("run_id", "count"),
        bytes_per_msg_median=("wire_bytes_per_msg", "median"),
        bytes_per_msg_min=("wire_bytes_per_msg", "min"),
        bytes_per_msg_max=("wire_bytes_per_msg", "max"),
        packets_per_msg_median=("wire_packets_per_msg", "median"),
        packets_per_msg_min=("wire_packets_per_msg", "min"),
        packets_per_msg_max=("wire_packets_per_msg", "max"),
    ).reset_index()


# ── Plots ──────────────────────────────────────────────────────

def make_plots(agg, frames, run_df, tier_df, sens, figures_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    experiments = sorted(run_df["experiment"].unique())

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(figures_dir / name, dpi=160)
        plt.close(fig)

    for scenario in ("clean", "netem", "outage"):
        subset = [f for f in frames if f["scenario"].iloc[0] == scenario]
        if not subset:
            continue
        fig, axes = plt.subplots(1, 3, figsize=(13, 4.2), sharey=True)
        for ax, experiment in zip(axes, experiments):
            any_curve = False
            for tier in TIERS:
                parts = [f[(f["experiment"] == experiment) & (f["tier"] == tier)
                           & (f["delivered"])]["latency_ms"] for f in subset]
                values = pd.concat(parts).dropna().to_numpy()
                if not len(values):
                    continue
                values = np.sort(values)
                ax.step(values, np.arange(1, len(values) + 1) / len(values),
                        where="post", color=TIER_COLORS[tier], alpha=0.8,
                        label=tier)
                any_curve = True
            ax.set_xscale("log")
            ax.set_title(f"Experiment {experiment}")
            ax.set_xlabel("one-way latency (ms, log)")
            ax.grid(alpha=0.3)
            if not any_curve:
                ax.text(0.5, 0.5, "no data", transform=ax.transAxes, ha="center")
        axes[0].set_ylabel("ECDF")
        axes[0].legend(fontsize=8)
        fig.suptitle(f"{scenario}: per-message latency ECDF (all reps, delivered)")
        save(fig, f"fig_latency_ecdf_{scenario}.png")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), sharey=True)
    width = 0.25
    for ax, scenario in zip(axes, ("clean", "netem")):
        data = agg[agg["scenario"] == scenario]
        x = np.arange(len(TIERS))
        for index, experiment in enumerate(experiments):
            med, low, high = [], [], []
            for tier in TIERS:
                row = data[(data["experiment"] == experiment) & (data["tier"] == tier)]
                if row.empty:
                    med.append(np.nan); low.append(np.nan); high.append(np.nan)
                else:
                    med.append(row["delivery_pct_median"].iloc[0])
                    low.append(row["delivery_pct_min"].iloc[0])
                    high.append(row["delivery_pct_max"].iloc[0])
            med, low, high = np.array(med), np.array(low), np.array(high)
            ax.bar(x + (index - 1) * width, med, width,
                   yerr=np.vstack([med - low, high - med]), capsize=3,
                   label=f"Experiment {experiment}")
        ax.set_xticks(x); ax.set_xticklabels(TIERS, rotation=15)
        ax.set_ylim(0, 105); ax.set_ylabel("delivered %")
        ax.set_title(scenario); ax.grid(axis="y", alpha=0.3)
    axes[0].legend(fontsize=8)
    fig.suptitle("Delivery rate per tier (median, min-max whiskers)")
    save(fig, "fig_delivery_clean_netem.png")

    fig, axes = plt.subplots(2, 4, figsize=(15, 7), sharex=True)
    for row_index, scenario in enumerate(("clean", "netem")):
        for col_index, tier in enumerate(TIERS):
            ax = axes[row_index][col_index]
            series = []
            for experiment in experiments:
                values = tier_df[(tier_df["experiment"] == experiment)
                                 & (tier_df["scenario"] == scenario)
                                 & (tier_df["tier"] == tier)]["lat_median_ms"].dropna()
                series.append(values.to_numpy())
            try:
                ax.boxplot(series, tick_labels=experiments)
            except TypeError:  # matplotlib < 3.9
                ax.boxplot(series, labels=experiments)
            ax.set_yscale("log")
            ax.set_title(f"{scenario} / {tier}")
            ax.grid(axis="y", alpha=0.3)
            if col_index == 0:
                ax.set_ylabel("run median latency (ms, log)")
    fig.suptitle("Latency per run: box = run medians (one point per repetition)")
    save(fig, "fig_latency_box_clean_netem.png")

    outage = agg[(agg["scenario"] == "outage") & agg["position"].notna()]
    positions = sorted(outage["position"].unique())
    if positions:
        fig, axes = plt.subplots(1, 3, figsize=(14, 4.2), sharey=True)
        width = 0.8 / max(1, len(experiments))
        for ax, tier in zip(axes, TIERS[:3]):
            x = np.arange(len(positions))
            for index, experiment in enumerate(experiments):
                med, low, high = [], [], []
                for position in positions:
                    row = outage[(outage["experiment"] == experiment)
                                 & (outage["tier"] == tier)
                                 & (outage["position"] == position)]
                    med.append(row["delivery_in_pct_median"].iloc[0] if len(row) else np.nan)
                    low.append(row["delivery_in_pct_min"].iloc[0] if len(row) else np.nan)
                    high.append(row["delivery_in_pct_max"].iloc[0] if len(row) else np.nan)
                med, low, high = np.array(med), np.array(low), np.array(high)
                ax.bar(x + (index - (len(experiments) - 1) / 2) * width, med, width,
                       yerr=np.vstack([med - low, high - med]), capsize=3,
                       label=f"Experiment {experiment}")
            ax.set_xticks(x)
            ax.set_xticklabels([f"{int(p * 100)}%" for p in positions])
            ax.set_ylim(0, 105)
            ax.set_xlabel("outage position within run")
            ax.set_title(f"{tier} tier")
            ax.grid(axis="y", alpha=0.3)
        axes[0].set_ylabel("in-window delivery %")
        axes[0].legend(fontsize=8)
        fig.suptitle("Outage: delivery of messages published while disconnected")
        save(fig, "fig_outage_recovery.png")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    for ax, tier in zip(axes, ("Critical", "Important")):
        series, labels = [], []
        for experiment in experiments:
            for scenario in ("clean", "netem"):
                values = tier_df[(tier_df["experiment"] == experiment)
                                 & (tier_df["scenario"] == scenario)
                                 & (tier_df["tier"] == tier)]["ack_median_ms"].dropna()
                series.append(values.to_numpy())
                labels.append(f"{experiment}\n{scenario}")
        try:
            ax.boxplot(series, tick_labels=labels)
        except TypeError:  # matplotlib < 3.9
            ax.boxplot(series, labels=labels)
        ax.axhline(50, color="red", linestyle="--", linewidth=1,
                   label="50 ms gate")
        ax.set_ylabel("publisher-side ack time (ms)")
        ax.set_title(tier)
        ax.grid(axis="y", alpha=0.3)
        ax.legend(fontsize=8)
    fig.suptitle("Ack time per run (median of each run); gate applies only to clean")
    save(fig, "fig_ack_times.png")

    wire = wire_summary(run_df)
    clean_wire = wire[wire["scenario"] == "clean"] if not wire.empty else wire
    if not clean_wire.empty:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
        for ax, (field, label) in zip(axes, (("bytes_per_msg", "TX bytes per message"),
                                            ("packets_per_msg", "TX packets per message"))):
            med = clean_wire[f"{field}_median"].to_numpy()
            low = clean_wire[f"{field}_min"].to_numpy()
            high = clean_wire[f"{field}_max"].to_numpy()
            x = np.arange(len(clean_wire))
            ax.bar(x, med, yerr=np.vstack([med - low, high - med]), capsize=4)
            ax.set_xticks(x)
            ax.set_xticklabels([f"{e}\n{scenario}" for e, scenario in
                                zip(clean_wire["experiment"], clean_wire["scenario"])])
            ax.set_ylabel(label)
            ax.grid(axis="y", alpha=0.3)
        fig.suptitle("Loopback TX overhead, clean runs only "
                     "(netem/outage inflate counters — see wire_summary.csv)")
        save(fig, "fig_wire_clean.png")

    sample = run_df[(run_df["scenario"] == "outage") & (run_df["position"] == 0.5)]
    if not sample.empty:
        fig, axes = plt.subplots(1, 3, figsize=(14, 4.2), sharey=True)
        for ax, experiment in zip(axes, experiments):
            rows = sample[sample["experiment"] == experiment].sort_values("rep")
            if rows.empty:
                continue
            run_id = rows["run_id"].iloc[0]
            frame = next(f for f in frames if f["run_id"].iloc[0] == run_id)
            for tier in TIERS:
                part = frame[(frame["tier"] == tier) & (frame["delivered"])]
                ax.scatter(part["seq"], part["latency_ms"], s=6,
                           color=TIER_COLORS[tier], label=tier)
            window = frame[frame["in_window"]]
            if len(window):
                ax.axvspan(window["seq"].min(), window["seq"].max(),
                           color="grey", alpha=0.25)
            missing = frame[~frame["delivered"]]
            if len(missing):
                ax.scatter(missing["seq"], np.full(len(missing), 0.4),
                           marker="x", color="black", s=18, label="not delivered")
            ax.set_yscale("log")
            ax.set_title(f"{experiment} (50% outage, run {run_id})")
            ax.set_xlabel("message seq")
            ax.grid(alpha=0.3)
        axes[0].set_ylabel("one-way latency (ms, log)")
        axes[0].legend(fontsize=7, loc="upper left")
        fig.suptitle("Outage timeline: queued QoS 1/2 messages arrive after reconnect")
        save(fig, "fig_outage_timeline.png")

    if sens is not None and not sens.empty:
        fig, axes = plt.subplots(1, 3, figsize=(14, 4.2), sharey=True)
        for ax, experiment in zip(axes, experiments):
            data = sens[(sens["experiment"] == experiment)
                        & (sens["scenario"] == "clean")]
            x = np.arange(len(TIERS))
            width = 0.35
            for offset, (field, label) in enumerate((("main", "0.1 s interval"),
                                                    ("sens", "1.0 s interval"))):
                med, low, high = [], [], []
                for tier in TIERS:
                    row = data[(data["tier"] == tier)]
                    if field == "main":
                        med.append(row["main_first100_median_ms"].median() if len(row) else np.nan)
                        low.append(row["main_min_ms"].min() if len(row) else np.nan)
                        high.append(row["main_max_ms"].max() if len(row) else np.nan)
                    else:
                        med.append(row["sens_1s_median_ms"].median() if len(row) else np.nan)
                        low.append(row["sens_min_ms"].min() if len(row) else np.nan)
                        high.append(row["sens_max_ms"].max() if len(row) else np.nan)
                med, low, high = np.array(med), np.array(low), np.array(high)
                ax.bar(x + (offset - 0.5) * width, med, width,
                       yerr=np.vstack([med - low, high - med]), capsize=3,
                       label=label)
            ax.set_xticks(x); ax.set_xticklabels(TIERS, rotation=15)
            ax.set_title(f"Experiment {experiment}")
            ax.grid(axis="y", alpha=0.3)
        axes[0].set_ylabel("median latency (ms); first 100 readings")
        axes[0].legend(fontsize=8)
        fig.suptitle("Pacing sensitivity, clean runs: 10 msg/s vs 1 msg/s on the same first 100 rows")
        save(fig, "fig_sensitivity.png")


# ── Report + entry point ──────────────────────────────────────

def render_sanity(hard, soft, notes, metas, run_df, tier_df, cfg_hash, config):
    lines = ["=" * 72,
             "MQTT benchmark — sanity report",
             "=" * 72,
             f"runs (complete): {len(metas)}",
             f"config_hash: {cfg_hash}",
             f"broker under test: {metas[0].get('broker', {}).get('version')}",
             f"dataset rows/run: {config.get('dataset_rows')}",
             f"pacing interval: {config.get('pacing_interval_s')} s",
             f"experiments: {sorted(run_df['experiment'].unique())}",
             f"scenarios: {sorted(run_df['scenario'].unique())}",
             "",
             f"HARD GATES: {'PASS' if not hard else 'FAIL'} ({len(hard)} problem(s))"]
    lines += [f"  FAIL  {item}" for item in hard]
    lines += ["",
              f"SOFT EXPECTATIONS: {'all within bands' if not soft else f'{len(soft)} warning(s)'}"]
    lines += [f"  WARN  {item}" for item in soft]
    lines += ["", "NOTES"]
    lines += [f"  - {item}" for item in notes]
    lines += ["", "Per-condition run/evaluation detail"]
    lines.append(f"  {'exp':<4}{'scenario':<12}{'reps':>5}{'sent':>7}{'recv':>7}"
                 f"{'duplicates':>12}{'mean_int_ms':>13}")
    for (experiment, scenario), group in run_df.groupby(["experiment", "scenario"]):
        lines.append(f"  {experiment:<4}{scenario:<12}{len(group):>5}"
                     f"{int(group['sent_measured'].sum()):>7}"
                     f"{int(group['recv_unique'].sum()):>7}"
                     f"{int(group['duplicates'].sum()):>12}"
                     f"{group['achieved_mean_interval_ms'].median():>13.1f}")
    outage = run_df[run_df["scenario"] == "outage"]
    if not outage.empty:
        lines += ["", "Outage session recovery"]
        for (experiment, position), group in outage.groupby(["experiment", "position"]):
            lines.append(f"  {experiment} p{int(position*100):02d}: "
                         f"session_present={sorted(group['session_present'].astype(str).unique())} "
                         f"window QoS0 losses={sorted(group['outage_window_lost'].unique())}")
            tier_group = tier_df[(tier_df["scenario"] == "outage")
                                 & (tier_df["experiment"] == experiment)
                                 & (tier_df["position"] == position)
                                 & (tier_df["n_recv_in"] > 0)]
            crit_group = tier_group[tier_group["tier"] == "Critical"]
            recovery_group = crit_group if len(crit_group) else tier_group
            label = "Critical" if len(crit_group) else "delivered tiers (no Critical in window)"
            rec_max = recovery_group.groupby("run_id")["recovery_max_ms"].max().dropna()
            lat_max = tier_group.groupby("run_id")["lat_in_max_ms"].max().dropna()
            if len(rec_max):
                lines.append(f"    recovery max ({label}, t1-t_on): {rec_max.median():.1f} ms "
                             f"[{rec_max.min():.1f}-{rec_max.max():.1f}]; "
                             f"max in-window latency (all tiers): {lat_max.median():.1f} ms")
    clean_ack = tier_df[(tier_df["scenario"] == "clean")
                        & tier_df["tier"].isin(["Critical", "Important"])]
    if not clean_ack.empty:
        lines += ["", "Publisher-side ack gate (clean runs, <=50 ms)"]
        for (experiment, tier), group in clean_ack.groupby(["experiment", "tier"]):
            lines.append(f"  {experiment} {tier}: "
                         f"{group['ack_within_50pct'].median():.1f}% "
                         f"[{group['ack_within_50pct'].min():.1f}-{group['ack_within_50pct'].max():.1f}]")
    netem_ack = tier_df[(tier_df["scenario"] == "netem")
                        & tier_df["tier"].isin(["Critical", "Important"])]
    if not netem_ack.empty:
        lines += ["", "Netem ack (informational, not a gate)"]
        for (experiment, tier), group in netem_ack.groupby(["experiment", "tier"]):
            lines.append(f"  {experiment} {tier}: "
                         f"{group['ack_within_50pct'].median():.1f}% within 50 ms "
                         f"[{group['ack_within_50pct'].min():.1f}-{group['ack_within_50pct'].max():.1f}]")
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Analyse the single-clock MQTT benchmark.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--main-dir", default=None)
    parser.add_argument("--sensitivity-dir", default=None)
    parser.add_argument("--no-sensitivity", action="store_true",
                        help="analyse the main study only")
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args(argv)

    if args.main_dir is None:
        args.main_dir = str(BENCH_DIR / "results_v2")
    if args.sensitivity_dir is None:
        args.sensitivity_dir = str(BENCH_DIR / "results_v2_sensitivity")

    main_dir = Path(args.main_dir)
    metas, main_hash = load_study(main_dir, "main")
    config = metas[0]["config"]

    required = ["method_version", "tier_qos", "socketpair", "paho_mqtt",
                "tcp_nodelay", "idle_max_pps"]
    for key in required:
        if key not in config:
            die(f"{main_dir}: config is missing methodology key {key!r}; "
                f"refusing to analyse it as v2")
    if config.get("idle_max_pps") is None:
        die(f"{main_dir}: v2 main/sensitivity analysis requires a recorded "
            f"--idle-max-pps threshold")

    tier_runs, run_summaries, frames = [], [], []
    for meta in metas:
        sent, recv = read_run(meta, main_dir)
        rows, summary, frame = analyse_run(meta, sent, recv)
        tier_runs.extend(rows)
        run_summaries.append(summary)
        frames.append(frame)

    tier_df = pd.DataFrame(tier_runs)
    run_df = pd.DataFrame(run_summaries)
    _, agg = aggregate(tier_runs)

    hard, soft, notes = sanity_checks(run_df, agg, frames, config)

    matrix_path = main_dir / "matrix.json"
    if matrix_path.exists():
        try:
            matrix = json.loads(matrix_path.read_text())
            planned = {entry["run_id"] for entry in matrix.get("plan", [])}
            actual = {meta["run_id"] for meta in metas}
            missing = sorted(planned - actual)
            if missing:
                hard.append(f"{len(missing)} planned run(s) missing: {', '.join(missing)}")
            if matrix.get("config_hash") and matrix["config_hash"] != main_hash:
                hard.append("matrix.json config_hash differs from run metas")
            if matrix.get("status") not in (None, "complete"):
                notes.append(f"matrix.json status={matrix.get('status')} "
                             f"(failures: {matrix.get('failed_runs')})")
        except Exception as exc:
            soft.append(f"could not inspect matrix.json: {exc!r}")
    else:
        soft.append("matrix.json missing — completeness checked from meta files only")

    duplicates = int(run_df["duplicates"].sum())
    notes.append(f"duplicate deliveries removed by (run_id, seq): {duplicates} "
                 f"(expected for QoS 1; not counted as messages)")
    notes.append("latency is one-way (t1 - t0, same monotonic clock); "
                 "never RTT/2")
    notes.append("aggregates are median [min-max] across runs, not pooled CIs")

    sens_df = None
    sens_metas = []
    sens_dir = Path(args.sensitivity_dir)
    if args.no_sensitivity:
        notes.append("sensitivity study skipped by --no-sensitivity")
    elif sens_dir.is_dir() and any(sens_dir.glob("meta_*.json")):
        try:
            sens_metas, sens_hash = load_study(sens_dir, "sensitivity")
            sens_config = sens_metas[0]["config"]
            for key in required:
                if key not in sens_config:
                    die(f"{sens_dir}: config is missing methodology key {key!r}")
                if sens_config.get(key) != config.get(key):
                    die(f"sensitivity {key}={sens_config.get(key)!r} differs from "
                        f"main {config.get(key)!r}; refusing to mix methodologies")
            sens_frames = []
            for meta in sens_metas:
                sent, recv = read_run(meta, sens_dir)
                _, _, frame = analyse_run(meta, sent, recv)
                sens_frames.append(frame)
            sens_df = sensitivity_comparison(frames, sens_frames)
            notes.append(f"sensitivity study: {len(sens_metas)} runs, "
                         f"config_hash={sens_hash[:16]}, compared on first 100 rows")
        except SystemExit:
            raise
        except Exception as exc:
            soft.append(f"sensitivity study not analysed: {exc!r}")
    else:
        notes.append("sensitivity study not found — pacing comparison skipped")

    sanity = render_sanity(hard, soft, notes, metas, run_df, tier_df,
                           main_hash, config)
    (main_dir / "sanity.txt").write_text(sanity)
    print(sanity)

    if hard:
        print("HARD GATE FAILURE — no summary.csv or figures written.", file=sys.stderr)
        return 1

    tier_df.to_csv(main_dir / "summary_per_run.csv", index=False)
    run_df.to_csv(main_dir / "runs.csv", index=False)
    agg.to_csv(main_dir / "summary.csv", index=False)
    outage_critical(frames, tier_df).to_csv(main_dir / "outage_critical.csv", index=False)
    wire = wire_summary(run_df)
    if not wire.empty:
        wire.to_csv(main_dir / "wire_summary.csv", index=False)

    if sens_df is not None and not sens_df.empty:
        sens_df.to_csv(main_dir / "sensitivity_comparison.csv", index=False)

    plot_error = None
    if not args.no_plots:
        try:
            make_plots(agg, frames, run_df, tier_df, sens_df, main_dir / "figures")
        except Exception as exc:
            plot_error = repr(exc)
            soft.append(f"plotting failed: {plot_error}")
            (main_dir / "sanity.txt").write_text(
                render_sanity(hard, soft, notes, metas, run_df, tier_df,
                              main_hash, config))

    analysis_meta = {
        "study": "main",
        "analysis_mode": "v2",
        "main_dir": str(main_dir),
        "config_hash": main_hash,
        "method_version": config.get("method_version"),
        "socketpair": config.get("socketpair"),
        "paho_mqtt": config.get("paho_mqtt"),
        "tcp_nodelay": config.get("tcp_nodelay"),
        "idle_max_pps": config.get("idle_max_pps"),
        "preflight": metas[0].get("preflight"),
        "runs": len(metas),
        "flagged_runs": int(run_df["idle_flagged"].sum()),
        "flagged_run_ids": sorted(
            run_df.loc[run_df["idle_flagged"], "run_id"].tolist()),
        "experiments": sorted(run_df["experiment"].unique().tolist()),
        "scenarios": sorted(run_df["scenario"].unique().tolist()),
        "sensitivity_runs": len(sens_metas),
        "hard_failures": hard,
        "soft_warnings": soft,
        "notes": notes,
        "plot_error": plot_error,
        "broker": metas[0].get("broker"),
        "env": metas[0].get("env"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (main_dir / "analysis_meta.json").write_text(
        json.dumps(analysis_meta, indent=2, sort_keys=True))

    print(f"\nWrote summary.csv, summary_per_run.csv, runs.csv, "
          f"outage_critical.csv, sanity.txt and figures/ to {main_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
