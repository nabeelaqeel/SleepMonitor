#!/usr/bin/env bash
# B/C netem calibration: stock paho socketpair vs AF_UNIX socketpair.
#
# 6 runs total: A, B, C for each socketpair mode, one repetition each.
# 150 dataset rows at 1 msg/s, delay-only netem (no loss).
#
# Calibration may run record-only. To enforce the idle threshold, set
# IDLE_MAX_PPS (packets/second) after measuring the idle baseline with the
# agent/IDE and other localhost services closed:
#
#   IDLE_MAX_PPS=<pps> ./benchmark/calibration_v2/run_bc_netem.sh
#
# Outputs:
#   benchmark/calibration_v2/bc_netem/stock/
#   benchmark/calibration_v2/bc_netem/af_unix/
#   benchmark/calibration_v2/bc_netem/gate/

set -euo pipefail

BENCH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="${OUT_ROOT:-$BENCH_DIR/calibration_v2/bc_netem}"
IDLE_MAX_PPS="${IDLE_MAX_PPS:-}"
PYTHON="${PYTHON:-python3}"

if [[ -n "$IDLE_MAX_PPS" && ! "$IDLE_MAX_PPS" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
    echo "IDLE_MAX_PPS must be a non-negative number (packets/second)" >&2
    exit 2
fi

cleanup() {
    sudo -n tc qdisc del dev lo root >/dev/null 2>&1 || true
}
trap cleanup EXIT

sudo -v
if tc qdisc show dev lo | grep -q netem; then
    echo "leftover netem on lo; refusing to start" >&2
    exit 2
fi

run_mode() {
    local mode="$1"
    local out="$ROOT/$mode"
    local extra=()
    if [[ -n "$IDLE_MAX_PPS" ]]; then
        extra+=(--idle-max-pps "$IDLE_MAX_PPS")
    fi
    echo "=== $mode: A,B,C / netem / 1 msg/s / 150 rows ==="
    "$PYTHON" "$BENCH_DIR/run_benchmark.py" \
        --experiments A,B,C \
        --scenarios netem \
        --reps 1 \
        --rows 150 \
        --interval 1.0 \
        --socketpair "$mode" \
        --netem-delay-only \
        --calibration \
        --out-dir "$out" \
        "${extra[@]}"
}

run_mode stock
run_mode af_unix

"$PYTHON" "$BENCH_DIR/calibration_v2/analyze_bc_netem.py" \
    --stock-dir "$ROOT/stock" \
    --af-unix-dir "$ROOT/af_unix" \
    --out-dir "$ROOT/gate"
