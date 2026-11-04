"""Read one completed sleep session from PostgreSQL for nightly analysis.

The ingest worker keeps this module separate; no writes happen here.
"""

from __future__ import annotations

import os
from typing import Any

import pandas as pd
from dotenv import load_dotenv

SQL = """
SELECT
    session_id,
    patient_id,
    seq,
    ts,
    spo2,
    heart_rate,
    hrv,
    motion
FROM readings
WHERE session_id = %s
ORDER BY ts ASC;
"""


def session_readings(session_id: str, dsn: str | None = None) -> list[dict]:
    """Return one completed session as a list of nightly feature inputs.

    The ingest worker does not know about this module, so it never writes
    here. It keeps the QoS pipeline untouched.
    """
    load_dotenv(".env.development")
    dsn = dsn or os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")

    import psycopg2

    with psycopg2.connect(dsn) as conn:
        table = pd.read_sql_query(SQL, conn, params=(session_id,))
    return table.to_dict(orient="records")


def latest_session_for_patient(patient_id: str, dsn: str | None = None) -> str:
    """Return the most recent session id for a single patient."""
    load_dotenv(".env.development")
    dsn = dsn or os.getenv("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")

    import psycopg2

    sql = """
    SELECT session_id
    FROM sessions
    WHERE patient_id = %s
    ORDER BY started_at DESC
    LIMIT 1
    """

    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, (patient_id,))
        result = cur.fetchone()

    if result is None:
        raise RuntimeError(f"No session found for patient_id={patient_id}")
    return str(result[0])
