-- =============================================================
-- Sleep Monitor — Initial Database Schema
-- Runs automatically when the postgres container first starts.
-- For production (RDS), run this manually after provisioning.
-- =============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Users ─────────────────────────────────────────────────────
-- Both doctors and patients are stored here. Role determines
-- which navigator is shown in the React Native app.
CREATE TABLE users (
    user_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email       VARCHAR(255) UNIQUE NOT NULL,
    name        VARCHAR(255) NOT NULL,
    role        VARCHAR(20) NOT NULL CHECK (role IN ('doctor', 'patient')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Doctor ↔ Patient assignments ──────────────────────────────
CREATE TABLE doctor_patients (
    doctor_id   UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    patient_id  UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (doctor_id, patient_id)
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
    ('00000000-0000-0000-0000-000000000002', 'patient@sleep.com', 'Ali Hassan', 'patient');

INSERT INTO doctor_patients (doctor_id, patient_id) VALUES
    ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002');
