"""Run a post-night AI recommendation.

CLI:
    .venv-dev/bin/python -m ai.recommend --session-id <uuid>
    .venv-dev/bin/python -m ai.recommend --session-id <uuid> --publish

Reads the completed session from Postgres, computes the nightly features, runs
the trained model and optionally publishes the non-diagnostic guidance band.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
import json

from .mqtt import publish
from .nightly_adapter import get_recommendation
from .session_loader import latest_session_for_patient, session_readings

DEFAULT_TOPIC = "sleep/recommendation"


def recommendation_payload(result: dict) -> dict:
    """Shape the message the app will consume on sleep/recommendation."""
    return {
        "sessionId": result.get("session_id"),
        "patientId": result.get("patient_id"),
        "band": result.get("band"),
        "p_positive": result.get("p_positive"),
        "thresholdFlagged": result.get("flagged_positive"),
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
