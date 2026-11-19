-- =============================================================
-- Sleep Monitor — Initial Database Schema
-- Runs automatically when the postgres container first starts.
-- For production (RDS), run this manually after provisioning.
-- =============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Users ─────────────────────────────────────────────────────
-- Doctors, patients and system admins are stored here. Role determines
-- which navigator the React Native app shows; admins operate the system
-- itself and are provisioned (by this seed or another admin), never
-- self-registered. The CHECK is explicitly named users_role_check so
-- migrations can target it deterministically — an unnamed inline CHECK
-- would be auto-named the same way, but only while it stays the table's
-- sole CHECK constraint.
CREATE TABLE users (
    user_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email         VARCHAR(255) UNIQUE NOT NULL,
    name          VARCHAR(255) NOT NULL,
    role          VARCHAR(20) NOT NULL CONSTRAINT users_role_check
                  CHECK (role IN ('doctor', 'patient', 'admin')),
    -- bcrypt hash; empty for the seeded rows — the auth API seeds the real
    -- hash of the demo password on startup (SQL cannot compute bcrypt),
    -- so the API must run at least once before anyone can log in.
    password_hash VARCHAR(255) DEFAULT '',
    -- Doctor-only pairing code, minted by the auth API on registration
    -- (patients keep NULL). Patients post it to /auth/link-doctor.
    pairing_code  VARCHAR(12) UNIQUE,
    -- Physical profile for the doctor's patient-detail screen. Nullable:
    -- doctors have none and patients may not have reported theirs. The
    -- auth API mirrors these as ADD COLUMN IF NOT EXISTS in ensure_setup
    -- so databases created before them upgrade on the next API start.
    -- medical_history keeps one entry per line; the API shapes lines into
    -- the history records the app renders.
    age             INTEGER,
    weight_kg       NUMERIC(5,1),
    height_cm       NUMERIC(5,1),
    medical_history TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Doctor ↔ Patient assignments ──────────────────────────────
CREATE TABLE doctor_patients (
    doctor_id   UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    patient_id  UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (doctor_id, patient_id)
);

-- ── Device registry ───────────────────────────────────────────
-- Maps each watch's deviceId to the patient it belongs to, so N
-- simulated watches attribute their sessions/readings/alerts to the
-- right user. Unbound devices fall back to PATIENT_UUID (the
-- single-watch demo); the ingest worker resolves on session/start.
CREATE TABLE devices (
    device_id    VARCHAR(100) PRIMARY KEY,
    patient_id   UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    display_name VARCHAR(100),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Sleep sessions ─────────────────────────────────────────────
CREATE TABLE sessions (
    session_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    patient_id  UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    started_at  TIMESTAMPTZ NOT NULL,
    ended_at    TIMESTAMPTZ,
    device_id   VARCHAR(100),
    notes       TEXT
);

-- ── Time-series sensor readings ────────────────────────────────
-- High-volume table. One row per MQTT message received.
-- `seq` is the publisher-assigned monotonic counter for the session;
-- UNIQUE(session_id, seq) makes redelivered MQTT messages idempotent.
-- `published_at` is the publisher's send time (epoch ms) and enables
-- true end-to-end latency measurement.
CREATE TABLE readings (
    reading_id   BIGSERIAL PRIMARY KEY,
    session_id   UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    patient_id   UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    seq          INT NOT NULL,
    ts           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    spo2         FLOAT,
    heart_rate   FLOAT,
    hrv          FLOAT,
    motion       FLOAT,
    tier         VARCHAR(20) CHECK (tier IN ('Critical', 'Important', 'Normal', 'Background')),
    qos          SMALLINT CHECK (qos IN (0, 1, 2)),
    UNIQUE (session_id, seq)
);

-- Composite index for time-range queries per patient
CREATE INDEX idx_readings_patient_ts ON readings (patient_id, ts DESC);
CREATE INDEX idx_readings_session_ts ON readings (session_id, ts DESC);

-- ── Alert / event log ─────────────────────────────────────────
-- Only Critical and Important events are stored here
-- (mirrors the eventLog filter in SleepContext.js).
CREATE TABLE alerts (
    alert_id    BIGSERIAL PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    patient_id  UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    seq         INT NOT NULL,
    ts          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    severity    VARCHAR(20) NOT NULL CHECK (severity IN ('Critical', 'Important')),
    spo2        FLOAT,
    heart_rate  FLOAT,
    hrv         FLOAT,
    reason      TEXT,
    mqtt_topic  VARCHAR(100),
    raw_payload JSONB,
    UNIQUE (session_id, seq)
);

CREATE INDEX idx_alerts_patient_ts  ON alerts (patient_id, ts DESC);
CREATE INDEX idx_alerts_session_sev ON alerts (session_id, severity);

-- ── Session statistics ─────────────────────────────────────────
-- Computed summary per session. Updated by the backend API
-- or a background job when a session ends.
CREATE TABLE session_stats (
    session_id        UUID PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
    avg_spo2          FLOAT,
    min_spo2          FLOAT,
    avg_heart_rate    FLOAT,
    total_readings    INT NOT NULL DEFAULT 0,
    critical_count    INT NOT NULL DEFAULT 0,
    important_count   INT NOT NULL DEFAULT 0,
    -- QoS delivery accounting: expected = last seq + 1, received = rows
    -- persisted, missing = QoS 0 packets dropped in transit.
    expected_readings INT NOT NULL DEFAULT 0,
    received_readings INT NOT NULL DEFAULT 0,
    missing_readings  INT NOT NULL DEFAULT 0,
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Seed data for local development ───────────────────────────
-- Matches the mock credentials in auth/mockAuth.js.
-- Remove before production.
INSERT INTO users (user_id, email, name, role) VALUES
    ('00000000-0000-0000-0000-000000000001', 'doctor@sleep.com',  'Dr. Ahmad',  'doctor'),
    ('00000000-0000-0000-0000-000000000002', 'patient@sleep.com', 'Ali Hassan', 'patient'),
    ('00000000-0000-0000-0000-000000000003', 'admin@sleep.com',   'System Admin', 'admin');

INSERT INTO doctor_patients (doctor_id, patient_id) VALUES
    ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002');
