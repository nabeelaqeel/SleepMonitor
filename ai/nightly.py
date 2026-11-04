"""Post-night CLI for AI recommendation.

Reads one completed sleep session from PostgreSQL, computes the nightly features,
runs the trained Random Forest, and writes a JSON summary. It never modifies the
ingest worker or QoS framework.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from .nightly_adapter import get_recommendation

SQL_SELECT = """
    SELECT
        session_id,
        patient_id,
        seq,
        ts,
        published_at,
        spo2,
        heart_rate AS "heartRate",
        hrv,
        motion,
        tier,
        qos
    FROM readings
    WHERE session_id = %s::uuid
    ORDER BY ts ASC
"""


def query_session(session_id: str, dsn: str) -> list[dict]:
    import psycopg2

    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(SQL_SELECT, (session_id,))
        rows = cur.fetchall()
    out: list[dict] = []
    for session_id_, patient_id_, *_rest in rows:
        reading = {k: value for k, value in zip(
            ["session_id", "patient_id", "seq", "ts", "published_at", "spo2", "heartRate", "hrv", "motion", "tier", "qos"],
            [session_id_, patient_id_, *_rest],
        )}
        out.append(reading)
    return out


def to_dicts_from_csv(csv_path: Path) -> list[dict]:
    import pandas as pd
    df = pd.read_csv(csv_path)
    # The demo CSV uses these columns; `hrv` may not exist.
    careful = df.copy()
    careful["timestamp"] = pd.to_datetime(careful["minute"] * 1000, unit="s", utc=True)
    for c in ("spo2", "heartRate", "hrv", "motion"):
        if c not in careful.columns:
            careful[c] = None
    careful["session_id"] = "csv-session"
    return careful.to_dict(orient="records")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the post-night AI recommendation")
    parser.add_argument("--csv", type=Path, help="override the DB source with a CSV file")
    parser.add_argument("--out-dir", type=Path, default=Path("outputs"))
    args = parser.parse_args()

    if args.csv:
        readings = to_dicts_from_csv(args.csv)
        session_id = "csv-session"
    else:
        load_dotenv(".env.development")
        dsn = os.getenv("DATABASE_URL", "postgresql://sleep_user:sqlite@localhost/sleep_monitor")
        session_id = os.getenv("SESSION_ID", "")
        if not session_id:
            raise ValueError("SESSION_ID is not set. Run with --csv or set SESSION_ID in .env.development.")
        readings = query_session(session_id, dsn)

    if not readings:
        print("No readings available", file=__import__("sys").stderr)
        return 2

    result = get_recommendation(readings, session_id=session_id, patient_id=readings[0]["patient_id"])
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"{session_id or 'local'}-ai-recommendation.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))
    print(f"Recommendation saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
