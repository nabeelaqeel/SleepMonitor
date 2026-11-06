"""Run a post-night AI recommendation.

CLI:
    .venv-dev/bin/python -m ai.recommend --session-id <uuid>
    .venv-dev/bin/python -m ai.recommend --session-id <uuid> --publish

Reads the completed session from Postgres, computes the nightly features, runs
the trained model and optionally publishes the non-diagnostic guidance band.
"""

from __future__ import annotations

import argparse
import math
import os
from datetime import datetime, timezone
import json

import pandas as pd

from .mqtt import publish
from .nightly_adapter import get_recommendation
from .session_loader import latest_session_for_patient, session_readings

DEFAULT_TOPIC = "sleep/recommendation"


def _json_safe(value):
    """Coerce a nested result into strict-JSON-safe native values.

    Nightly features may carry numpy scalars and NaN (missing channels). NaN is
    not valid JSON, so it (and any non-finite float) becomes null — otherwise
    json.dumps would emit bare NaN, which brokers and phone-side JSON parsers
    can silently reject.
    """
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    # numpy scalars (np.int64 / np.float32 / np.bool_ are not native subclasses)
    if type(value).__module__.startswith("numpy"):
        return _json_safe(value.item())
    # datetimes / pandas Timestamps anything else → string
    return str(value)


def _readings_window(readings: list[dict]) -> dict | None:
    """First → last reading timestamps, for the exported report's recording
    window line. Timestamps are UTC ISO strings; None when there's no window."""
    stamps = [
        pd.to_datetime(
            reading.get("timestamp", reading.get("ts")),
            errors="coerce",
            utc=True,
        )
        for reading in readings
    ]
    stamps = [ts for ts in stamps if pd.notna(ts)]
    if len(stamps) < 2:
        return None
    return {
        "start": stamps[0].isoformat(),
        "end": stamps[-1].isoformat(),
    }


def recommendation_payload(result: dict) -> dict:
    """Shape the message the app will consume on sleep/recommendation.

    Beyond the band itself the payload carries everything the app's nightly
    "Sleep Pattern Report" export needs (nightly features + per-channel
    coverage meta, recording window, model metadata), so the report never has
    to re-derive anything phone-side.
    """
    return {
        "sessionId": result.get("session_id"),
        "patientId": result.get("patient_id"),
        "band": result.get("band"),
        "p_positive": _json_safe(result.get("p_positive")),
        "thresholdFlagged": result.get("flagged_positive"),
        "threshold": _json_safe(result.get("threshold")),
        "nightly": _json_safe(result.get("nightly")) or {},
        "window": _json_safe(result.get("window")),
        "modelVersion": result.get("model_version"),
        "trainedOn": result.get("trained_on"),
        "disclaimer": result.get("disclaimer"),
        "computedAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-night AI recommendation")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--session-id", help="UUID of a specific session")
    group.add_argument("--patient-id", help="UUID of the patient; uses that patient's latest session")
    parser.add_argument("--publish", action="store_true",
                        help="publish the result to sleep/recommendation")
    parser.add_argument("--topic", default=DEFAULT_TOPIC,
                        help="MQTT topic to publish to")
    parser.add_argument("--qos", type=int, default=1, choices=[0, 1, 2],
                        help="MQTT QoS (1 by default)")
    parser.add_argument("--retain", action="store_true",
                        help="retain the message so late subscribers see it")
    args = parser.parse_args()

    session_id = args.session_id or latest_session_for_patient(args.patient_id)

    readings = session_readings(session_id)
    if not readings:
        print("No readings found for session %s" % session_id, file=__import__("sys").stderr)
        return 1

    result = get_recommendation(
        readings,
        session_id=session_id,
        patient_id=readings[0].get("patient_id"),
    )
    result["window"] = _readings_window(readings)
    payload = recommendation_payload(result)
    if args.publish:
        publish(args.topic, payload, qos=args.qos, retain=args.retain)
        print(json.dumps({
            "topic": args.topic,
            "qos": args.qos,
            "retain": args.retain,
            "payload": payload,
        }, indent=2, default=str))
    else:
        print(json.dumps(payload, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
