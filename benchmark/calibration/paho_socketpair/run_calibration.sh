#!/usr/bin/env bash
set -Eeuo pipefail

REPO="/home/aqeel/MyStuff/fyp/SleepMonitor"
PYTHON="$REPO/.venv-dev/bin/python"
CAL="/tmp/opencode/sockpair-cal/calibration"
NETEM_PHASE=0

cleanup() {
  local rc=$?
  if [[ "$NETEM_PHASE" == "1" ]]; then
    echo
    echo "cleanup: removing temporary netem from lo ..."
    sudo tc qdisc del dev lo root 2>/dev/null || true
    sudo tc qdisc show dev lo || true
  fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
trap 'exit 131' QUIT

run_harness() {
  local mode="$1" phase="$2" experiments="$3" scenario="$4" rows="$5" interval="$6"
  local dir="$CAL/$phase"
  mkdir -p "$dir"
  echo
  echo "=== $phase: mode=$mode experiments=$experiments scenario=$scenario rows=$rows interval=${interval}s ==="
  PHASE_DIR="$dir" MODE="$mode" EXPERIMENTS="$experiments" SCENARIO="$scenario" ROWS="$rows" INTERVAL="$interval" \
    PYTHONDONTWRITEBYTECODE=1 "$PYTHON" -B - <<'PY' 2>&1 | tee "$dir/run.log"
from pathlib import Path
import os
import socket
import sys

REPO = Path("/home/aqeel/MyStuff/fyp/SleepMonitor")
sys.path.insert(0, str(REPO / "benchmark"))

import paho.mqtt.client as paho
import run_benchmark as rb

mode = os.environ["MODE"]
scenario = os.environ["SCENARIO"]

if mode == "patched":
    def unix_pair():
        r, w = socket.socketpair()
        r.setblocking(False)
        w.setblocking(False)
        return r, w
    paho._socketpair_compat = unix_pair

if scenario == "netem":
    rb.NETEM_CMD = ["tc", "qdisc", "add", "dev", "lo", "root", "netem",
                    "delay", "25ms", "10ms", "loss", "0%"]
    rb.NETEM_STRING = "tc qdisc add dev lo root netem delay 25ms 10ms loss 0%"

rb.BENCH_DIR = Path(os.environ["PHASE_DIR"])
raise SystemExit(rb.main([
    "--experiments", os.environ["EXPERIMENTS"],
    "--scenarios", scenario,
    "--rows", os.environ["ROWS"],
    "--interval", os.environ["INTERVAL"],
    "--reps", "1",
]))
PY
}

echo "=== initial lo qdisc ==="
initial_qdisc="$(tc qdisc show dev lo)"
printf '%s\n' "$initial_qdisc"
if grep -q 'netem' <<<"$initial_qdisc"; then
  echo "ERROR: netem is already present on lo; remove it before running." >&2
  exit 1
fi

# Clean comparison, no sudo: A, B, C full 526 rows at 0.1 s, stock then AF_UNIX.
run_harness stock    stock-clean    "A,B,C" clean 526 0.1
run_harness patched  patched-clean  "A,B,C" clean 526 0.1

echo
echo "=== netem phase: sudo authentication required ==="
sudo -v
sudo -n tc qdisc show dev lo >/dev/null
NETEM_PHASE=1

# Delay-only netem, A/QoS 0, 20 measured rows at 1 msg/s, stock then AF_UNIX.
run_harness stock    stock-netem    "A" netem 20 1
run_harness patched  patched-netem  "A" netem 20 1

echo
echo "=== removing netem and verifying lo qdisc ==="
sudo tc qdisc del dev lo root 2>/dev/null || true
final_qdisc="$(sudo tc qdisc show dev lo)"
printf '%s\n' "$final_qdisc"
if grep -q 'netem' <<<"$final_qdisc"; then
  echo "ERROR: netem still present on lo" >&2
  exit 1
fi
NETEM_PHASE=0

echo
echo "=== done: $CAL ==="
