#!/usr/bin/env python3
"""Gate the B/C netem calibration before the full v2 rerun.

Calibration design:
  - 150 dataset rows, 1 msg/s, delay-only netem (no loss)
  - A, B, C, one repetition each
  - stock paho socketpair vs AF_UNIX socketpair

Gate:
  1. all six runs complete
  2. all six metas have netem.applied == true and the delay-only command
  3. stock A t0 -> on_publish median >= 10 ms (artifact reproduced)
  4. patched A (t1 - on_publish) median between 35 and 70 ms
  5. A patched t0 -> on_publish median < 2 ms
  6. patched t1-t0 median <= stock median + 5 ms for QoS 0, 1, 2

QoS samples: QoS 0 from A, QoS 1 from B/Important, QoS 2 from C.
The stock-minus-patched offset is reported, not gated.
If the stock A ack artifact is below 10 ms, the gate is INCONCLUSIVE,
not PASS.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

BENCH_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_DIR))

from analyze_benchmark import (  # noqa: E402
    TIERS, analyse_run, die, load_study, read_run,
)
from run_benchmark import NETEM_DELAY_ONLY_STRING  # noqa: E402

QOS_SOURCES = {
    0: ("A", None),
    1: ("B", "Important"),
    2: ("C", None),
}


def load_phase(directory, label):
    metas, cfg_hash = load_study(directory, label)
    if len(metas) != 3:
        die(f"{label}: expected 3 runs (A, B, C), found {len(metas)}")
    experiments = sorted(meta.get("experiment") for meta in metas)
    if experiments != ["A", "B", "C"]:
        die(f"{label}: expected experiments A/B/C, found {experiments}")
    if any(meta.get("scenario") != "netem" for meta in metas):
        die(f"{label}: calibration must use only the netem scenario")
    config = metas[0]["config"]
    if "loss" in (config.get("netem") or ""):
        die(f"{label}: calibration must be delay-only, config says "
            f"{config.get('netem')!r}")
    flagged = sorted(
        meta["run_id"] for meta in metas
        if (meta.get("idle") or {}).get("flagged"))
    if flagged:
        die(f"{label}: {len(flagged)} flagged run(s) above the idle threshold; "
            f"delete and rerun: {', '.join(flagged)}")

    frames = []
    for meta in metas:
        sent, recv = read_run(meta, directory)
        _, _, frame = analyse_run(meta, sent, recv)
        frames.append(frame)
    return metas, cfg_hash, config, pd.concat(frames, ignore_index=True)


def qos_frame(frames, qos):
    experiment, tier = QOS_SOURCES[qos]
    subset = frames[frames["experiment"] == experiment]
    if tier is not None:
        subset = subset[subset["tier"] == tier]
    return subset


def stats(frames, qos):
    subset = qos_frame(frames, qos)
    latency = subset["latency_ms"].dropna()
    ack = subset["ack_ms"].dropna()
    if latency.empty:
        die(f"no delivered samples for QoS {qos}")
    return {
        "messages": int(len(latency)),
        "latency_median_ms": float(latency.median()),
        "latency_p95_ms": float(latency.quantile(0.95)),
        "ack_samples": int(len(ack)),
        "ack_median_ms": float(ack.median()) if len(ack) else float("nan"),
    }


def tier_table(stock_frames, patched_frames):
    rows = []
    for (experiment, tier) in sorted(
            stock_frames[["experiment", "tier"]].drop_duplicates().itertuples(index=False)):
        stock = stock_frames[(stock_frames["experiment"] == experiment)
                             & (stock_frames["tier"] == tier)]
        patched = patched_frames[(patched_frames["experiment"] == experiment)
                                 & (patched_frames["tier"] == tier)]
        sl = stock["latency_ms"].dropna()
        pl = patched["latency_ms"].dropna()
        sa = stock["ack_ms"].dropna()
        pa = patched["ack_ms"].dropna()
        rows.append({
            "experiment": experiment,
            "tier": tier,
            "stock_messages": len(sl),
            "patched_messages": len(pl),
            "stock_t1_t0_median_ms": sl.median() if len(sl) else float("nan"),
            "patched_t1_t0_median_ms": pl.median() if len(pl) else float("nan"),
            "t1_t0_delta_patched_minus_stock_ms":
                (pl.median() - sl.median()) if len(sl) and len(pl) else float("nan"),
            "stock_t0_on_publish_median_ms": sa.median() if len(sa) else float("nan"),
            "patched_t0_on_publish_median_ms": pa.median() if len(pa) else float("nan"),
        })
    return pd.DataFrame(rows)


def fmt_stat(value, messages, unit="ms"):
    if pd.isna(value) or messages is None:
        return "—"
    return f"{value:.2f} {unit} (n={int(messages)})"


def build_qos_rows(stock_frames, patched_frames):
    rows = []
    for qos, (experiment, tier) in QOS_SOURCES.items():
        stock = stats(stock_frames, qos)
        patched = stats(patched_frames, qos)
        rows.append({
            "qos": qos,
            "source": experiment if tier is None else f"{experiment}/{tier}",
            "messages": patched["messages"],
            "stock_messages": stock["messages"],
            "stock_t1_t0_median_ms": stock["latency_median_ms"],
            "patched_t1_t0_median_ms": patched["latency_median_ms"],
            "stock_minus_patched_ms":
                stock["latency_median_ms"] - patched["latency_median_ms"],
            "patched_t0_on_publish_median_ms": patched["ack_median_ms"],
            "stock_t0_on_publish_median_ms": stock["ack_median_ms"],
        })
    return rows


def netem_guard_counts(metas):
    ok = 0
    for meta in metas:
        netem = meta.get("netem") or {}
        if (netem.get("applied") is True
                and netem.get("command") == NETEM_DELAY_ONLY_STRING):
            ok += 1
    return ok, len(metas)


def build_gate_rows(stock_metas, patched_metas, stock_frames,
                    patched_frames, qos_rows):
    a_stock = stats(stock_frames, 0)
    a_patch = stats(patched_frames, 0)
    stock_ok, stock_n = netem_guard_counts(stock_metas)
    patched_ok, patched_n = netem_guard_counts(patched_metas)

    rows = [{
        "criterion": "all 6 runs netem.applied == true and delay-only command",
        "stock_label": f"{stock_ok}/{stock_n} runs (n={stock_n})",
        "patched_label": f"{patched_ok}/{patched_n} runs (n={patched_n})",
        "stock_median_ms": None,
        "stock_messages": None,
        "patched_median_ms": None,
        "patched_messages": None,
        "limit_ms": None,
        "limit_label": "6/6",
        "result": ("PASS" if stock_ok == 3 and patched_ok == 3
                   else "FAIL"),
    }]

    stock_ack = a_stock["ack_median_ms"]
    ack_n = a_stock["ack_samples"]
    ack_ok = (not pd.isna(stock_ack)) and stock_ack >= 10.0
    rows.append({
        "criterion": ("stock A t0 -> on_publish median >= 10 ms "
                      "(artifact reproduced)"),
        "stock_label": fmt_stat(stock_ack, ack_n),
        "patched_label": "—",
        "stock_median_ms": stock_ack,
        "stock_messages": ack_n,
        "patched_median_ms": None,
        "patched_messages": None,
        "limit_ms": 10.0,
        "limit_label": ">= 10.00 ms",
        "result": ("PASS" if ack_ok
                   else "INCONCLUSIVE: artifact did not reproduce"),
    })

    a_patch_frame = qos_frame(patched_frames, 0)
    t1_ack = (a_patch_frame["latency_ms"]
              - a_patch_frame["ack_ms"]).dropna()
    t1_ack_median = (float(t1_ack.median()) if len(t1_ack)
                     else float("nan"))
    t1_ack_ok = (len(t1_ack) > 0
                 and 35.0 <= t1_ack_median <= 70.0)
    rows.append({
        "criterion": ("patched A (t1 - on_publish) median "
                      "between 35 and 70 ms"),
        "stock_label": "—",
        "patched_label": fmt_stat(t1_ack_median, len(t1_ack)),
        "stock_median_ms": None,
        "stock_messages": None,
        "patched_median_ms": t1_ack_median,
        "patched_messages": len(t1_ack),
        "limit_ms": None,
        "limit_label": "35.00-70.00 ms",
        "result": "PASS" if t1_ack_ok else "FAIL",
    })

    patched_ack = a_patch["ack_median_ms"]
    patch_ack_ok = (not pd.isna(patched_ack)) and patched_ack < 2.0
    rows.append({
        "criterion": "A patched t0 -> on_publish median < 2 ms",
        "stock_label": fmt_stat(a_stock["ack_median_ms"],
                                a_stock["ack_samples"]),
        "patched_label": fmt_stat(patched_ack, a_patch["ack_samples"]),
        "stock_median_ms": a_stock["ack_median_ms"],
        "stock_messages": a_stock["ack_samples"],
        "patched_median_ms": patched_ack,
        "patched_messages": a_patch["ack_samples"],
        "limit_ms": 2.0,
        "limit_label": "2.00 ms",
        "result": "PASS" if patch_ack_ok else "FAIL",
    })

    for row in qos_rows:
        limit = row["stock_t1_t0_median_ms"] + 5.0
        passed = (not pd.isna(row["patched_t1_t0_median_ms"])
                  and row["patched_t1_t0_median_ms"] <= limit)
        rows.append({
            "criterion": (f"QoS {row['qos']}: patched t1−t0 median "
                          f"<= stock + 5 ms"),
            "stock_label": fmt_stat(row["stock_t1_t0_median_ms"],
                                    row["stock_messages"]),
            "patched_label": fmt_stat(row["patched_t1_t0_median_ms"],
                                      row["messages"]),
            "stock_median_ms": row["stock_t1_t0_median_ms"],
            "stock_messages": row["stock_messages"],
            "patched_median_ms": row["patched_t1_t0_median_ms"],
            "patched_messages": row["messages"],
            "limit_ms": limit,
            "limit_label": f"stock + 5 = {limit:.2f} ms",
            "result": "PASS" if passed else "FAIL",
        })
    return rows


def overall_status(gate_rows):
    results = [row["result"] for row in gate_rows]
    if any(result == "FAIL" for result in results):
        return "FAIL"
    if any(result.startswith("INCONCLUSIVE") for result in results):
        return "INCONCLUSIVE"
    return "PASS"


def markdown(stock_hash, patched_hash, qos_rows, gate_rows, tiers,
             stock_runs, patched_runs):
    complete = stock_runs == 3 and patched_runs == 3
    lines = [
        "# B/C netem calibration gate",
        "",
        f"- stock config hash: `{stock_hash[:16]}`",
        f"- AF_UNIX config hash: `{patched_hash[:16]}`",
        "- 150 rows, 1 msg/s, delay-only netem, one run per experiment",
        f"- all six calibration runs complete: {'PASS' if complete else 'FAIL'} "
        f"(stock {stock_runs}, AF_UNIX {patched_runs})",
        "",
        "## Gate",
        "",
        "| Criterion | stock | patched | Limit | Result |",
        "|---|---:|---:|---:|:---|",
    ]
    for row in gate_rows:
        lines.append(
            f"| {row['criterion']} "
            f"| {row['stock_label']} "
            f"| {row['patched_label']} "
            f"| {row['limit_label']} | {row['result']} |")
    lines += [
        "",
        f"**Overall gate: {overall_status(gate_rows)}**",
        "",
        "## Per-QoS result (not a gate)",
        "",
        "| QoS | Source | stock msg | patched msg | stock t1−t0 (ms) "
        "| patched t1−t0 (ms) | stock−patched offset (ms) "
        "| patched on_publish (ms) |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in qos_rows:
        lines.append(
            f"| {row['qos']} | {row['source']} "
            f"| {row['stock_messages']} | {row['messages']} "
            f"| {row['stock_t1_t0_median_ms']:.2f} "
            f"| {row['patched_t1_t0_median_ms']:.2f} "
            f"| {row['stock_minus_patched_ms']:.2f} "
            f"| {row['patched_t0_on_publish_median_ms']:.2f} |")
    lines += ["", "## Per-tier detail", "",
              "| Exp | Tier | stock msg | patched msg | stock t1−t0 | "
              "patched t1−t0 | Δ | stock ack | patched ack |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in tiers.itertuples():
        lines.append(
            f"| {row.experiment} | {row.tier} | {int(row.stock_messages)} "
            f"| {int(row.patched_messages)} "
            f"| {row.stock_t1_t0_median_ms:.2f} | {row.patched_t1_t0_median_ms:.2f} "
            f"| {row.t1_t0_delta_patched_minus_stock_ms:+.2f} "
            f"| {row.stock_t0_on_publish_median_ms:.2f} "
            f"| {row.patched_t0_on_publish_median_ms:.2f} |")
    lines += [
        "",
        "QoS 0 comes from experiment A; QoS 1 from B/Important; QoS 2 from C. "
        "B's other tiers are shown for completeness but do not feed the gate.",
        "",
    ]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-dir",
                        default=str(BENCH_DIR / "calibration_v2/bc_netem/stock"))
    parser.add_argument("--af-unix-dir",
                        default=str(BENCH_DIR / "calibration_v2/bc_netem/af_unix"))
    parser.add_argument("--out-dir",
                        default=str(BENCH_DIR / "calibration_v2/bc_netem/gate"))
    args = parser.parse_args(argv)

    stock_metas, stock_hash, stock_config, stock_frames = load_phase(
        Path(args.stock_dir), "stock")
    patched_metas, patched_hash, patched_config, patched_frames = load_phase(
        Path(args.af_unix_dir), "AF_UNIX")
    if patched_config.get("socketpair") != "af_unix":
        die(f"AF_UNIX phase has socketpair={patched_config.get('socketpair')!r}")
    if stock_config.get("socketpair") != "stock":
        die(f"stock phase has socketpair={stock_config.get('socketpair')!r}")
    for key in ("method_version", "runner_sha256", "dataset_sha256",
                "classifier_sha256", "dataset_rows", "pacing_interval_s",
                "paho_mqtt", "tcp_nodelay", "idle_max_pps", "tier_qos",
                "netem"):
        if stock_config.get(key) != patched_config.get(key):
            die(f"stock and AF_UNIX calibration differ on {key}: "
                f"{stock_config.get(key)!r} != {patched_config.get(key)!r}")

    qos_rows = build_qos_rows(stock_frames, patched_frames)
    qos_df = pd.DataFrame(qos_rows)
    gate_rows = build_gate_rows(
        stock_metas, patched_metas, stock_frames, patched_frames, qos_rows)
    gate_df = pd.DataFrame(gate_rows)
    tiers = tier_table(stock_frames, patched_frames)
    overall = overall_status(gate_rows)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    qos_df.to_csv(out_dir / "per_qos.csv", index=False)
    gate_df.to_csv(out_dir / "gate.csv", index=False)
    tiers.to_csv(out_dir / "per_tier.csv", index=False)
    report = markdown(stock_hash, patched_hash, qos_rows, gate_rows, tiers,
                      len(stock_metas), len(patched_metas))
    (out_dir / "gate.md").write_text(report)

    print(report)
    print(f"Gate {overall}; wrote {out_dir}")
    if overall == "FAIL":
        return 1
    if overall == "INCONCLUSIVE":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
