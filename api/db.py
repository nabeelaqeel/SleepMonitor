"""PostgreSQL access layer for the auth API.

One short-lived connection per operation; the app only logs in twice a
day, so pooling would be overkill. Startup is idempotent — the same
permissive pattern the ingest worker uses:

  * ensure_setup() adds the password_hash, pairing_code and physical-profile
    columns when missing, rebuilds the users role CHECK around the admin
    role, seeds bcrypt hashes for the three demo users (only when the
    stored hash is empty, so restarts never clobber a password changed
    later), fills the demo patient's profile the same way and mints
    pairing codes for the demo doctors.

The DATABASE_URL comes from .env.development (same as the ingest worker).
"""

from __future__ import annotations

import re
import secrets
from contextlib import contextmanager
from datetime import UTC

import psycopg2

from api.config import DATABASE_URL, DEMO_SEEDING_ENABLED

# demo credentials are hashed at API startup; SEED_DEMO_USERS=false disables
# this entirely so deployments can provision their own accounts instead.
SEED_USERS = [
    {
        "user_id": "00000000-0000-0000-0000-000000000001",
        "email": "doctor@sleep.com",
        "name": "Dr. Ahmad",
        "role": "doctor",
        "password": "1234",
    },
    {
        "user_id": "00000000-0000-0000-0000-000000000002",
        "email": "patient@sleep.com",
        "name": "Ali Hassan",
        "role": "patient",
        "password": "1234",
        # Demo-day physical profile so the doctor's detail screen shows real
        # Age/Weight/Height/History instead of placeholders. Doctors carry
        # no profile (they are not patients).
        "profile": {
            "age": 34,
            "weight_kg": 78.0,
            "height_cm": 175.0,
            "medical_history": "Mild obstructive sleep apnea (AHI 14), diagnosed 2024",
        },
    },
    {
        "user_id": "00000000-0000-0000-0000-000000000003",
        "email": "admin@sleep.com",
        "name": "System Admin",
        "role": "admin",
        "password": "1234",
    },
]

_USER_COLS = ("user_id", "email", "name", "role", "password_hash")


@contextmanager
def connection():
    """Yield a connection with commit-on-success / rollback-on-error."""
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_setup(hash_password) -> None:
    """Add password_hash/pairing_code when missing and seed demo users (hash only when empty).

    `hash_password` is injected (security.hash_password) so db.py has no
    dependency on the hashing layer. Demo seeding respects SEED_DEMO_USERS
    (api.config) — schema migration runs regardless.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255) DEFAULT ''
            """
        )
        cur.execute(
            """
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS pairing_code VARCHAR(12) UNIQUE
            """
        )
        # Physical-profile columns for the roster/detail screen — same
        # ADD COLUMN IF NOT EXISTS migration path as above, so staging and
        # production databases created before them upgrade on the next API
        # start without a down -v reset.
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS age INTEGER")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS weight_kg NUMERIC(5,1)")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS height_cm NUMERIC(5,1)")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS medical_history TEXT")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                device_id    VARCHAR(100) PRIMARY KEY,
                patient_id   UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                display_name VARCHAR(100),
                created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        # Widen the role CHECK to include 'admin'. The legacy inline CHECK was
        # auto-named users_role_check (Postgres appends _check1, _check2… only
        # when de-duplicating), so drop every name variant before re-adding
        # under one stable explicit name future migrations can target.
        # Running on every start is cheap on the tiny users table, and a
        # widening re-add can only admit more values — never a revalidation
        # failure on rows that passed the narrower set.
        cur.execute(
            """
            DO $$
            DECLARE legacy text;
            BEGIN
                FOR legacy IN
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'users'::regclass
                      AND contype = 'c'
                      AND conname ~ '^users_role_check(_[0-9]+)?$'
                LOOP
                    EXECUTE format('ALTER TABLE users DROP CONSTRAINT %I', legacy);
                END LOOP;
            END
            $$;
            """
        )
        cur.execute(
            """
            ALTER TABLE users
            ADD CONSTRAINT users_role_check
            CHECK (role IN ('doctor', 'patient', 'admin'))
            """
        )
        for user in SEED_USERS if DEMO_SEEDING_ENABLED else []:
            cur.execute(
                "SELECT password_hash FROM users WHERE email = %s",
                (user["email"],),
            )
            row = cur.fetchone()
            if row is None:
                # Fresh install: init sql already seeds these rows, but be
                # safe in case the DB predates the seed volume.
                cur.execute(
                    """
                    INSERT INTO users (user_id, email, name, role, password_hash)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (email) DO NOTHING
                    """,
                    (user["user_id"], user["email"], user["name"],
                     user["role"], hash_password(user["password"])),
                )
                # A concurrent insert may have won; re-read to see if the
                # hash still needs filling.
                cur.execute(
                    "SELECT password_hash FROM users WHERE email = %s",
                    (user["email"],),
                )
                row = cur.fetchone()
            # Fill the hash only when empty — never overwrite a real one.
            if row is not None and not (row[0] or ""):
                cur.execute(
                    "UPDATE users SET password_hash = %s WHERE email = %s",
                    (hash_password(user["password"]), user["email"]),
                )
            if user["role"] == "doctor" and row is not None:
                cur.execute(
                    """
                    UPDATE users
                    SET pairing_code = %s
                    WHERE email = %s AND pairing_code IS NULL
                    """,
                    (generate_pairing_code(), user["email"]),
                )
            # Fill the demo profile only where NULL — the same never-clobber
            # rule as the hash seeding, so an edited profile survives restarts.
            profile = user.get("profile")
            if profile and row is not None:
                cur.execute(
                    """
                    UPDATE users
                    SET age = COALESCE(age, %s),
                        weight_kg = COALESCE(weight_kg, %s),
                        height_cm = COALESCE(height_cm, %s),
                        medical_history = COALESCE(medical_history, %s)
                    WHERE email = %s
                    """,
                    (profile["age"], profile["weight_kg"], profile["height_cm"],
                     profile["medical_history"], user["email"]),
                )


def get_user_by_email(email: str) -> dict | None:
    """Case-insensitive lookup; None when absent or ambiguous.

    `users.email` constraints are case-sensitive, so identities differing
    only by case can coexist in principle. Logging into an ambiguous match
    would pick an arbitrary account, so more than one hit also returns None
    — the login endpoint keeps its single generic 401 either way.
    """
    email = email.strip().lower()
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {', '.join(_USER_COLS)}
            FROM users
            WHERE lower(email) = lower(%s)
            """,
            (email,),
        )
        rows = cur.fetchall()
    if len(rows) != 1:
        return None  # 0 hits = unknown email; >1 hits = ambiguous identity
    return dict(zip(_USER_COLS, rows[0]))


def get_user_by_id(user_id: str) -> dict | None:
    """Row for an exact user_id; None when unknown.

    Endpoints that must tell "row deleted after token issuance" (401)
    apart from "row exists but the asked-for thing is absent" need this
    — the JWT carries no email, so get_user_by_email can't serve them.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {', '.join(_USER_COLS)}
            FROM users
            WHERE user_id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()
    return dict(zip(_USER_COLS, row)) if row else None


# Digits 2-9 and letters minus I/L/O keep codes readable when a patient
# types them from a phone screen or reads one aloud (no 0/O, 1/I/l pairs).
_PAIRING_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def generate_pairing_code() -> str:
    """Cryptographically random 12-char code, no visually ambiguous characters."""
    return "".join(secrets.choice(_PAIRING_ALPHABET) for _ in range(12))


def create_user(email: str, name: str, role: str, password_hash: str) -> dict | None:
    """Insert a user and return the row shaped like get_user_by_email.

    Emails are stored lowercase so the case-insensitive login lookup can
    never see two identities that differ only by case. Returns None when
    the email is already taken (the UNIQUE constraint is the race-safe
    arbiter — a check-then-insert pair would still let duplicates through).
    """
    with connection() as conn, conn.cursor() as cur:
        try:
            cur.execute(
                """
                INSERT INTO users (email, name, role, password_hash)
                VALUES (%s, %s, %s, %s)
                RETURNING user_id, email, name, role, password_hash
                """,
                (email.strip().lower(), name, role, password_hash),
            )
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            return None
        row = cur.fetchone()
    return dict(zip(_USER_COLS, row))


def update_user_name(user_id: str, name: str) -> dict | None:
    """Rename the caller; None when user_id is unknown.

    Only `name` is mutable here — id, email and role never move through
    this path, so the bearer token (sub+role only) needs no reissue.
    Returns the row shaped like get_user_by_email.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE users
            SET name = %s
            WHERE user_id = %s
            RETURNING {', '.join(_USER_COLS)}
            """,
            (name, user_id),
        )
        row = cur.fetchone()
    return dict(zip(_USER_COLS, row)) if row else None


def get_or_create_pairing_code(user_id: str) -> str | None:
    """Return the doctor's pairing code, minting one on first use.

    The conditional UPDATE + RETURNING makes concurrent callers converge on
    a single code: whoever loses the race re-reads the winner's value
    instead of overwriting it. None for an unknown user_id.
    """
    with connection() as conn, conn.cursor() as cur:
        for _ in range(3):
            cur.execute(
                "SELECT pairing_code FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            if row[0]:
                return row[0]
            cur.execute(
                """
                UPDATE users
                SET pairing_code = %s
                WHERE user_id = %s AND pairing_code IS NULL
                RETURNING pairing_code
                """,
                (generate_pairing_code(), user_id),
            )
            minted = cur.fetchone()
            if minted is not None:
                return minted[0]
            # Concurrent caller won the UPDATE — loop re-reads their code.
        raise RuntimeError("pairing code generation kept colliding")


def find_user_by_pairing_code(code: str) -> dict | None:
    """Resolve a pairing code to its user row; None when the code is unknown."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {', '.join(_USER_COLS)}
            FROM users
            WHERE pairing_code = %s
            """,
            (code.strip().upper(),),
        )
        row = cur.fetchone()
    return dict(zip(_USER_COLS, row)) if row else None


def link_doctor(patient_id: str, doctor_id: str) -> None:
    """Attach a patient to a doctor; repeating an existing pair is a no-op."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO doctor_patients (doctor_id, patient_id)
            VALUES (%s, %s)
            ON CONFLICT (doctor_id, patient_id) DO NOTHING
            """,
            (doctor_id, patient_id),
        )


def get_doctor_of_patient(patient_id: str) -> dict | None:
    """The doctor currently linked to this patient; None when unlinked.

    Inverse of link_doctor. A patient may be linked to several doctors —
    the newest assignment wins so "my doctor" stays deterministic. The
    users row is joined live, never snapshotted at link time, so a later
    rename is visible on the very next call.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {', '.join(_USER_COLS)}
            FROM doctor_patients dp
            JOIN users ON users.user_id = dp.doctor_id
            WHERE dp.patient_id = %s
            ORDER BY dp.assigned_at DESC
            LIMIT 1
            """,
            (patient_id,),
        )
        row = cur.fetchone()
    return dict(zip(_USER_COLS, row)) if row else None


_DEVICE_COLS = ("device_id", "patient_id", "display_name", "created_at")


def bind_device(patient_id: str, device_id: str,
                display_name: str | None) -> dict | None:
    """Insert or refresh the caller's registry row for a device.

    Returns None when the device is bound to a DIFFERENT patient —
    rebinding someone else's watch would let one account hijack another's
    data attribution. Same-patient rebinding only refreshes display_name.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT patient_id FROM devices WHERE device_id = %s",
            (device_id,),
        )
        row = cur.fetchone()
        if row is not None and str(row[0]) != str(patient_id):
            return None
        cur.execute(
            """
            INSERT INTO devices (device_id, patient_id, display_name)
            VALUES (%s, %s, %s)
            ON CONFLICT (device_id) DO NOTHING
            """,
            (device_id, patient_id, display_name),
        )
        if cur.rowcount == 0:
            # Lost a concurrent insert race — the owner must be the same
            # patient (the pre-check passed) or the device is hijacked.
            cur.execute(
                "SELECT patient_id FROM devices WHERE device_id = %s",
                (device_id,),
            )
            if str(cur.fetchone()[0]) != str(patient_id):
                return None
        cur.execute(
            """
            UPDATE devices
            SET display_name = COALESCE(%s, display_name)
            WHERE device_id = %s AND patient_id = %s
            RETURNING device_id, patient_id::text, display_name, created_at
            """,
            (display_name, device_id, patient_id),
        )
        out = cur.fetchone()
    return dict(zip(_DEVICE_COLS, out))


def list_devices(patient_id: str) -> list[dict]:
    """The calling patient's bound devices, oldest first."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT device_id, patient_id::text, display_name, created_at
            FROM devices
            WHERE patient_id = %s
            ORDER BY created_at, device_id
            """,
            (patient_id,),
        )
        rows = cur.fetchall()
    return [dict(zip(_DEVICE_COLS, row)) for row in rows]


# PatientDetailScreen maps over medicalHistory as {id, date, type, note,
# doctor} records — a bare string would crash its .map, so each TEXT line
# is shaped into one record. A trailing "diagnosed YYYY" becomes the badge
# date instead of sitting inside the note.
_HISTORY_DATE_RE = re.compile(r"[,\s]+(?:diagnosed|treated)\s+(\d{4})$", re.IGNORECASE)


def _history_records(medical_history: str | None) -> list[dict]:
    """Shape users.medical_history lines into the records the app renders."""
    records = []
    for index, line in enumerate(x.strip() for x in (medical_history or "").splitlines()):
        if not line:
            continue
        match = _HISTORY_DATE_RE.search(line)
        note, date = (line[:match.start()].rstrip(" ,"), match.group(1)) if match else (line, "")
        records.append({
            # Stable per line order; the app only uses it as a React key.
            "id": f"mh{index}",
            "date": date,
            "type": "Diagnosis",
            "note": note,
            "doctor": "",
        })
    return records


def list_doctor_patients(doctor_id: str) -> list[dict]:
    """Roster for the calling doctor: linked patients + their data snapshot.

    One LATERAL query per concern keeps this batched (no per-patient
    round-trips); the latest-reading lookup rides the (patient_id, ts
    DESC) index. LEFT JOINs keep freshly paired patients (no devices, no
    data) in the roster — completeness beats activity for the demo. Each
    row also carries the patient's physical profile under the exact keys
    the app reads; BMI is computed client-side, never sent.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                u.user_id::text, u.email, u.name,
                u.age, u.weight_kg, u.height_cm, u.medical_history,
                COALESCE(dev.devices, '[]'::json),
                lr.ts, lr.spo2, lr.heart_rate,
                ls.session_id::text, ls.started_at, ls.ended_at,
                COALESCE(ls.total_readings, 0), COALESCE(ls.missing_readings, 0)
            FROM users u
            JOIN doctor_patients dp
                 ON dp.patient_id = u.user_id AND dp.doctor_id = %s::uuid
            LEFT JOIN LATERAL (
                SELECT json_agg(
                           json_build_object('device_id', d.device_id,
                                             'display_name', d.display_name)
                           ORDER BY d.created_at, d.device_id
                       ) AS devices
                FROM devices d
                WHERE d.patient_id = u.user_id
            ) dev ON TRUE
            LEFT JOIN LATERAL (
                SELECT r.ts, r.spo2, r.heart_rate
                FROM readings r
                WHERE r.patient_id = u.user_id
                ORDER BY r.ts DESC
                LIMIT 1
            ) lr ON TRUE
            LEFT JOIN LATERAL (
                SELECT s.session_id, s.started_at, s.ended_at,
                       st.total_readings, st.missing_readings
                FROM sessions s
                LEFT JOIN session_stats st ON st.session_id = s.session_id
                WHERE s.patient_id = u.user_id
                ORDER BY s.started_at DESC
                LIMIT 1
            ) ls ON TRUE
            WHERE u.role = 'patient'
            ORDER BY u.name, u.email
            """,
            (doctor_id,),
        )
        rows = cur.fetchall()
    patients = []
    for (uid, email, name, age, weight, height, history,
         devices, r_ts, spo2, hr,
         s_id, started_at, ended_at, total, missing) in rows:
        patients.append({
            "id": uid,
            "email": email,
            "name": name,
            # NUMERIC arrives as Decimal — float keeps the JSON numbers plain
            # for the app's `${weight} kg` style rendering.
            "age": age,
            "weight": None if weight is None else float(weight),
            "height": None if height is None else float(height),
            "medicalHistory": _history_records(history),
            "devices": devices,
            "last_reading": None if r_ts is None else {
                "ts": r_ts,
                "spo2": spo2,
                "heart_rate": hr,
            },
            "last_session": None if s_id is None else {
                "session_id": s_id,
                "started_at": started_at,
                "ended_at": ended_at,
                "total_readings": total,
                "missing_readings": missing,
            },
        })
    return patients


def list_doctor_alerts(doctor_id: str) -> list[dict]:
    """Alert history for the calling doctor's linked patients, newest first.

    Scoped by the doctor_patients join exactly like list_doctor_patients,
    so alerts of unlinked patients never leak across doctors. Hard cap of
    50 rows, no pagination — the Alerts tab renders a recent-events feed,
    not an archive.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.alert_id, a.patient_id::text, u.name,
                   a.severity, a.spo2, a.heart_rate, a.ts, a.session_id::text
            FROM alerts a
            JOIN users u
                 ON u.user_id = a.patient_id AND u.role = 'patient'
            JOIN doctor_patients dp
                 ON dp.patient_id = a.patient_id AND dp.doctor_id = %s::uuid
            ORDER BY a.ts DESC
            LIMIT 50
            """,
            (doctor_id,),
        )
        rows = cur.fetchall()
    # Alerts ride idx_alerts_patient_ts; FLOAT columns arrive as Python
    # floats, so only the UUIDs and the ISO timestamp need shaping.
    return [
        {
            "alert_id": alert_id,
            "patient_id": patient_id,
            "patient_name": name,
            "severity": severity,
            "spo2": spo2,
            "heart_rate": heart_rate,
            # Contract fixes UTC: normalize so a non-UTC server clock can't
            # shift the offset the app receives.
            "ts": ts.astimezone(UTC).isoformat(),
            "session_id": session_id,
        }
        for (alert_id, patient_id, name, severity, spo2, heart_rate,
             ts, session_id) in rows
    ]


# ── Admin (system-operator) queries ────────────────────────────
# Every /admin/* endpoint routes through these; like the user-scoped ones
# above they never return password_hash in a shaped response.

def list_users() -> list[dict]:
    """Every account for GET /admin/users, oldest first.

    Exactly the five operator fields — password_hash is never selected, so
    it cannot leak into a response shape by accident.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT user_id::text, email, name, role, created_at
            FROM users
            ORDER BY created_at, email
            """
        )
        rows = cur.fetchall()
    return [
        {
            "id": user_id,
            "email": email,
            "name": name,
            "role": role,
            "created_at": created.astimezone(UTC).isoformat(),
        }
        for (user_id, email, name, role, created) in rows
    ]


def update_user_password(user_id: str, password_hash: str) -> dict | None:
    """Overwrite the stored hash for admin password reset; None when unknown.

    Deliberately separate from update_user_name so a rename can never carry
    a credential write. Returns the row shaped like get_user_by_email; the
    hash stays server-side as everywhere else.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE users
            SET password_hash = %s
            WHERE user_id = %s
            RETURNING {', '.join(_USER_COLS)}
            """,
            (password_hash, user_id),
        )
        row = cur.fetchone()
    return dict(zip(_USER_COLS, row)) if row else None


def db_health() -> dict:
    """DB reachability + newest-reading timestamp for GET /admin/health.

    Wrapped so a down database degrades to reachable=false instead of a
    500 — a health endpoint must describe failures, not raise them. The
    MAX(ts) over readings doubles as the ingest-liveness proxy: null means
    the pipeline has never persisted a reading.
    """
    out: dict = {"reachable": False, "last_data_received": None}
    row = None
    try:
        with connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
            out["reachable"] = True
            cur.execute("SELECT MAX(ts) FROM readings")
            row = cur.fetchone()
    except psycopg2.Error:
        return out
    if row is not None and row[0] is not None:
        out["last_data_received"] = row[0].astimezone(UTC).isoformat()
    return out


def list_recent_qos_sessions(limit: int = 20) -> list[dict]:
    """Recent QoS delivery accounting (session_stats), newest computed first.

    GET /admin/qos-sessions — the pipeline-health view of the ingest
    worker's accounting: expected = last publisher seq + 1, received = rows
    persisted, missing = QoS 0 packets dropped in transit. delivery_pct is
    null while nothing was expected, since an empty session has no
    meaningful delivery ratio. Hard cap keeps it a health view, not an
    archive.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT st.session_id::text,
                   st.expected_readings, st.received_readings, st.missing_readings,
                   CASE WHEN st.expected_readings > 0
                        THEN ROUND(st.received_readings * 100.0
                                   / st.expected_readings, 1)
                        ELSE NULL END,
                   st.computed_at
            FROM session_stats st
            ORDER BY st.computed_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [
        {
            "session_id": session_id,
            "expected_readings": expected,
            "received_readings": received,
            "missing_readings": missing,
            # ROUND(numeric) arrives as Decimal — float keeps plain JSON.
            "delivery_pct": None if pct is None else float(pct),
            "computed_at": computed.astimezone(UTC).isoformat(),
        }
        for (session_id, expected, received, missing, pct, computed) in rows
    ]
