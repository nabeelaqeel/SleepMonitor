"""PostgreSQL access layer for the ingest worker.

All writes go through a single connection owned by the worker's main
thread, so no locking is required here. Inserts are idempotent via
`ON CONFLICT DO NOTHING` on (session_id, seq) — safe to replay after
a worker restart or MQTT redelivery.
"""

from __future__ import annotations

import logging
from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values

log = logging.getLogger("ingest.db")


def connect(dsn: str):
    """Open one connection to the ingest DSN, transactions driven by the caller (autocommit off)."""
    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    return conn


def ensure_user(conn, patient_uuid: str, email: str = "patient@sleep.com",
                name: str = "Ali Hassan") -> None:
    """Make sure the seeded patient row exists before any FK insert."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (user_id, email, name, role)
            VALUES (%s, %s, %s, 'patient')
            ON CONFLICT DO NOTHING
            """,
            (patient_uuid, email, name),
        )
    conn.commit()


def upsert_session(conn, session_id: str, patient_uuid: str,
                   device_id: str, started_at: datetime) -> None:
    """Create the session row on first sight; ON CONFLICT keeps a replayed session/start harmless."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sessions (session_id, patient_id, started_at, device_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (session_id) DO NOTHING
            """,
            (session_id, patient_uuid, started_at, device_id),
        )
    conn.commit()


def insert_readings(conn, rows: list[tuple]) -> int:
    """Bulk-insert readings; (session_id, seq) conflicts are dropped so MQTT redelivery cannot duplicate a row. Returns how many rows actually inserted."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO readings
                (session_id, patient_id, seq, published_at,
                 spo2, heart_rate, hrv, motion, tier, qos)
            VALUES %s
            ON CONFLICT (session_id, seq) DO NOTHING
            """,
            rows,
            template="(%s, %s, %s, to_timestamp(%s / 1000.0), %s, %s, %s, %s, %s, %s)",
        )
        inserted = cur.rowcount
    conn.commit()
    return inserted


def insert_alerts(conn, rows: list[tuple]) -> int:
    """Bulk-insert the Critical/Important alert rows mirroring today's read batch; idempotent the same way. Returns actually-inserted count."""
    if not rows:
        return 0
    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO alerts
                (session_id, patient_id, seq, severity,
                 spo2, heart_rate, hrv, reason, mqtt_topic, raw_payload)
            VALUES %s
            ON CONFLICT (session_id, seq) DO NOTHING
            """,
            rows,
            template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
        )
        inserted = cur.rowcount
    conn.commit()
    return inserted


def finalize_session(conn, session_id: str, ended_at: datetime,
                     declared_total: int | None = None) -> dict:
    """Aggregate readings/alerts and close the session.

    `expected` is the reading count declared by the publisher in
    session/end when available (exact); otherwise it falls back to the
    highest seq seen + 1 (which cannot see a dropped trailing run).
    `missing` = expected - persisted rows, i.e. QoS 0 packets dropped in
    transit. QoS 1/2 are protected by the broker, so they only show up
    here if the worker was down past the session expiry.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*), coalesce(max(seq), -1), avg(spo2), min(spo2), avg(heart_rate)
            FROM readings WHERE session_id = %s
            """,
            (session_id,),
        )
        received, max_seq, avg_spo2, min_spo2, avg_hr = cur.fetchone()
        if declared_total is not None:
            expected = int(declared_total)
        else:
            expected = (max_seq + 1) if max_seq is not None and max_seq >= 0 else 0
        missing = max(expected - received, 0)

        cur.execute(
            "SELECT count(*) FROM alerts WHERE session_id = %s AND severity = 'Critical'",
            (session_id,),
        )
        critical = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM alerts WHERE session_id = %s AND severity = 'Important'",
            (session_id,),
        )
        important = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO session_stats
                (session_id, avg_spo2, min_spo2, avg_heart_rate, total_readings,
                 critical_count, important_count,
                 expected_readings, received_readings, missing_readings, computed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (session_id) DO UPDATE SET
                avg_spo2          = EXCLUDED.avg_spo2,
                min_spo2          = EXCLUDED.min_spo2,
                avg_heart_rate    = EXCLUDED.avg_heart_rate,
                total_readings    = EXCLUDED.total_readings,
                critical_count    = EXCLUDED.critical_count,
                important_count   = EXCLUDED.important_count,
                expected_readings = EXCLUDED.expected_readings,
                received_readings = EXCLUDED.received_readings,
                missing_readings  = EXCLUDED.missing_readings,
                computed_at       = NOW()
            """,
            (session_id, avg_spo2, min_spo2, avg_hr, received,
             critical, important, expected, received, missing),
        )
        cur.execute(
            "UPDATE sessions SET ended_at = %s WHERE session_id = %s",
            (ended_at, session_id),
        )
    conn.commit()
    return {
        "received": received,
        "expected": expected,
        "missing": missing,
        "critical": critical,
        "important": important,
    }
