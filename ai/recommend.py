"""Run a post-night AI recommendation.

CLI:
    .venv-dev/bin/python -m ai.recommend --session-id <uuid>

Reads the completed session from Postgres, computes the nightly features,
runs the trained model and prints the non-diagnostic guidance band.
"""

from __future__ import annotations

import argparse
import json

from .classifier import load as load_classifier
from .nightly_adapter import get_recommendation, session_to_nightly_features
from .session_loader import session_readings


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-night AI recommendation")
    parser.add_argument("--session-id", required=True, help="UUID of the completed session")
    args = parser.parse_args()

    readings = session_readings(args.session_id)
    if not readings:
        print("No readings found for session %s" % args.session_id, file=__import__("sys").stderr)
        return 1

    result = get_recommendation(readings, session_id=args.session_id)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
