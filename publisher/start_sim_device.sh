#!/usr/bin/env bash
# Launch one simulated watch. DEVICE_ID and PATIENT_ID are required: they
# land in every published payload and PATIENT_ID forms the MQTT client_id
# (sleep-publisher-<PATIENT_ID>), so distinct values per instance are what
# keeps parallel watches collision-free and registry-bindable.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$REPO_ROOT/.venv-dev/bin/python"

if [[ -z "${DEVICE_ID:-}" || -z "${PATIENT_ID:-}" ]]; then
  cat >&2 <<EOF
usage: DEVICE_ID=<id> PATIENT_ID=<id> [CSV_PATH=path] [MQTT_HOST=host] [MQTT_PORT=port] $0

DEVICE_ID and PATIENT_ID are required — each parallel watch instance needs
its own pair or two publishers share one MQTT client_id and evict each
other. Optional variables are exported only when set.
EOF
  exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "error: interpreter not found: $PYTHON (create the repo venv first)" >&2
  exit 1
fi

export DEVICE_ID PATIENT_ID
# Only forward the optionals when provided; publisher.py keeps its own defaults.
if [[ -n "${CSV_PATH:-}" ]];  then export CSV_PATH;  fi
if [[ -n "${MQTT_HOST:-}" ]]; then export MQTT_HOST; fi
if [[ -n "${MQTT_PORT:-}" ]]; then export MQTT_PORT; fi

cd "$REPO_ROOT"
exec "$PYTHON" publisher/publisher.py
