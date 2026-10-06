# AWS Cloud Migration Guide

## Summary of Decisions

| Component | Choice | Why |
|---|---|---|
| MQTT Broker | **Mosquitto on EC2 t3.micro** | AWS IoT Core drops QoS 2 and requires SigV4 WebSocket signing — incompatible with Paho JS without major rework |
| Database | **Amazon RDS PostgreSQL (db.t3.micro)** | One database handles both relational data (users, sessions) and time-series readings at FYP scale; free tier for 12 months |
| REST API | **AWS Lambda + API Gateway HTTP API** | Serverless, free tier covers all FYP traffic, no server to manage |
| Authentication | **Amazon Cognito** | Built-in doctor/patient groups, JWT tokens, native API Gateway integration, 50K MAU free permanently |
| TLS termination | **Nginx on the same EC2** | Mosquitto WebSocket must be WSS in cloud; Nginx proxies port 443 → Mosquitto port 9001 |

---

## Why Not AWS IoT Core?

AWS IoT Core looks like the obvious choice for an MQTT IoT project but has two hard blockers for this system:

1. **No QoS 2.** IoT Core caps at QoS 1. The `sleep/critical` topic deliberately uses QoS 2 (exactly-once) for apnea events. Switching to IoT Core requires redesigning the QoS contract.
2. **SigV4 WebSocket signing.** IoT Core WebSocket connections require AWS Signature V4 URL signing. The Paho JS client used by the React Native app has no built-in SigV4 support. Getting it working requires a custom authorizer or pre-signed URL wrapper — days of debugging for no benefit at this scale.

Self-managed Mosquitto on a t3.micro sidesteps both problems with zero code changes in `mqttService.js` except updating the host, port, and `useSSL: true`.

---

## Target AWS Architecture

```
                        REACT NATIVE APP (Expo)
                        +-----------------------+
                        |  Paho JS (WSS :443)   |
                        |  Axios (HTTPS :443)   |
                        |  AWS Amplify Auth     |
                        +-----+--------+--------+
                              |        |
            WSS (port 443)    |        |   HTTPS (port 443)
            +-----------------+        +------------------+
            |                                            |
+-----------v-----------+                  +------------v-----------+
|  EC2 t3.micro         |                  |  API Gateway HTTP API  |
|  Mosquitto + Nginx    |                  +------------+-----------+
|  Elastic IP           |                               |
|  Ports: 443 (WSS)     |                  +------------v-----------+
|         8883 (MQTTS)  |                  |  Lambda (Node.js)      |
|         22 (SSH/mgmt) |                  |  /patients             |
+-----------+-----------+                  |  /sessions             |
            |                             |  /readings             |
            | Python publisher            |  /alerts               |
            | (runs on same EC2)          +------------+-----------+
            | publishes to               |                         |
            | localhost:1883             +------------v-----------+
            |                            |  Amazon RDS            |
            +---(MQTT subscriber)------->|  PostgreSQL            |
               Lambda or Python bridge   |  db.t3.micro           |
               writes readings to RDS    |  (private subnet)      |
                                         +-----------+------------+
                                                     |
                                         +-----------v-----------+
                                         |  Amazon Cognito       |
                                         |  Doctor / Patient     |
                                         |  groups + JWT tokens  |
                                         +-----------------------+

VPC LAYOUT
+---------------------------------------------------------------------+
|  VPC (10.0.0.0/16)                                                  |
|  +------------------------+     +--------------------------------+  |
|  |  Public Subnet         |     |  Private Subnet                |  |
|  |  EC2 (Mosquitto+Nginx) |     |  RDS PostgreSQL                |  |
|  |  Elastic IP            |     |  Security Group:               |  |
|  |  Security Group:       |     |    port 5432 from EC2 SG only  |  |
|  |    443 in: 0.0.0.0/0  |     |    port 5432 from Lambda SG    |  |
|  |    22 in: your IP only |     +--------------------------------+  |
|  +------------------------+                                         |
+---------------------------------------------------------------------+
```

---

## Database: RDS PostgreSQL

### Why not Timestream or DynamoDB?

| Option | Problem |
|---|---|
| Amazon Timestream | Purpose-built for time-series only — you still need a second database for relational data (users, doctor-patient assignments). Two databases for a FYP adds unnecessary complexity. No free tier. |
| DynamoDB | No SQL aggregations (AVG, MIN, MAX) — must compute in application code. Time-range queries require careful composite key design. Doctor-patient relationships and session joins are awkward without JOINs. |
| RDS PostgreSQL | Handles relational + time-series at FYP scale (≈ 720 readings per 2-hour session). Full SQL. Free tier db.t3.micro for 12 months. Migration path to TimescaleDB is schema-compatible if needed later. |

### Schema

```sql
-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users (doctors and patients share this table)
CREATE TABLE users (
    user_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email       VARCHAR(255) UNIQUE NOT NULL,
    name        VARCHAR(255) NOT NULL,
    role        VARCHAR(20) NOT NULL CHECK (role IN ('doctor', 'patient')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Doctor ↔ Patient assignments
CREATE TABLE doctor_patients (
    doctor_id   UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    patient_id  UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (doctor_id, patient_id)
);

-- Sleep sessions
CREATE TABLE sessions (
    session_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    patient_id  UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    started_at  TIMESTAMPTZ NOT NULL,
    ended_at    TIMESTAMPTZ,
    device_id   VARCHAR(100),
    notes       TEXT
);

-- Time-series sensor readings (high-volume)
CREATE TABLE readings (
    reading_id  BIGSERIAL PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    patient_id  UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    ts          TIMESTAMPTZ NOT NULL,
    spo2        FLOAT,
    heart_rate  FLOAT,
    hrv         FLOAT,
    motion      FLOAT,
    tier        VARCHAR(20),    -- Critical / Important / Normal / Background
    qos         SMALLINT
);

CREATE INDEX idx_readings_patient_ts ON readings (patient_id, ts DESC);
CREATE INDEX idx_readings_session_ts ON readings (session_id, ts DESC);

-- Alert / event log
CREATE TABLE alerts (
    alert_id    BIGSERIAL PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    patient_id  UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    ts          TIMESTAMPTZ NOT NULL,
    severity    VARCHAR(20) NOT NULL,   -- Critical / Important
    spo2        FLOAT,
    heart_rate  FLOAT,
    hrv         FLOAT,
    reason      TEXT,
    mqtt_topic  VARCHAR(100),
    raw_payload JSONB
);

CREATE INDEX idx_alerts_patient_ts  ON alerts (patient_id, ts DESC);
CREATE INDEX idx_alerts_session_sev ON alerts (session_id, severity);

-- Computed session summary
CREATE TABLE session_stats (
    session_id      UUID PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
    avg_spo2        FLOAT,
    min_spo2        FLOAT,
    avg_heart_rate  FLOAT,
    total_readings  INT DEFAULT 0,
    critical_count  INT DEFAULT 0,
    important_count INT DEFAULT 0,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## Mosquitto on EC2 — TLS Setup

In the cloud, all connections must be encrypted. The cleanest approach is to terminate TLS at Nginx on port 443 and proxy to Mosquitto's local WebSocket listener on port 9001.

### Nginx config (`/etc/nginx/sites-available/mqtt`)

```nginx
server {
    listen 443 ssl;
    server_name your-ec2-domain.com;

    ssl_certificate     /etc/letsencrypt/live/your-ec2-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-ec2-domain.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;

    location /mqtt {
        proxy_pass          http://localhost:9001;
        proxy_http_version  1.1;
        proxy_set_header    Upgrade    $http_upgrade;
        proxy_set_header    Connection "Upgrade";
        proxy_set_header    Host       $host;
        proxy_read_timeout  86400s;
        proxy_send_timeout  86400s;
    }
}
```

### React Native app changes (`mqttService.js`)

Only three lines change:

```js
// Before (local dev)
const BROKER_IP   = '192.168.1.139';
const BROKER_PORT = 9001;
// useSSL: false

// After (cloud)
const BROKER_IP   = 'your-ec2-domain.com';
const BROKER_PORT = 443;
// useSSL: true, userName: '...', password: '...'
```

Topic names, QoS levels, and payload format are unchanged.

---

## Authentication: Amazon Cognito

Replace `auth/mockAuth.js` with Cognito:

1. Create a Cognito User Pool with two groups: `Doctors` and `Patients`.
2. Install AWS Amplify: `npm install aws-amplify @aws-amplify/auth`
3. Configure Amplify in `App.js`:
   ```js
   import { Amplify } from 'aws-amplify';
   Amplify.configure({
     Auth: {
       region:           'ap-southeast-1',
       userPoolId:       'ap-southeast-1_XXXXXXX',
       userPoolClientId: 'xxxxxxxxxxxxxxxxxxxxxxxx',
     }
   });
   ```
4. Replace `login()` with `signIn()` from `@aws-amplify/auth`.
5. API Gateway HTTP API reads the Cognito group from the JWT `cognito:groups` claim to determine role.

---

## Cost Estimate

### Free tier (first 12 months)

| Service | Free allowance | Cost |
|---|---|---|
| EC2 t3.micro | 750 hrs/month | $0 |
| RDS db.t3.micro | 750 hrs/month + 20 GB | $0 |
| Lambda | 1M requests + 400K GB-s/month | $0 |
| API Gateway HTTP API | 1M requests/month | $0 |
| Cognito | 50K MAU (permanent) | $0 |
| Data transfer out | 100 GB/month | $0 |
| **Total** | | **~$0/month** |

### After free tier

| Service | Monthly cost |
|---|---|
| EC2 t3.micro | ~$7.50 |
| RDS db.t3.micro + 20 GB gp2 | ~$14.55 |
| Lambda + API Gateway | ~$0.05 |
| Data transfer | ~$0.50 |
| **Total** | **~$23/month** |

**Cost tip:** Stop the EC2 instance when not demoing. A stopped EC2 costs only the EBS storage (~$0.08/month). Use an EventBridge scheduled rule + Lambda to auto-stop at night.

---

## Migration Checklist

### Week 1 — Infrastructure
- [ ] Launch EC2 t3.micro in a VPC public subnet
- [ ] Attach Elastic IP
- [ ] Install Mosquitto + Nginx on EC2
- [ ] Configure Nginx WSS proxy on port 443
- [ ] Obtain TLS certificate via Let's Encrypt (`certbot --nginx -d your-domain.com`)
- [ ] Add Mosquitto password auth (no anonymous connections)
- [ ] Security Group: allow 443 from `0.0.0.0/0`, allow 22 from your IP only
- [ ] Test WebSocket connection with `useSSL: true` from Paho JS

### Week 2 — Database
- [ ] Launch RDS PostgreSQL db.t3.micro in a private subnet
- [ ] Run schema DDL
- [ ] Security Group: allow 5432 from EC2 Security Group only
- [ ] Write Python bridge service on EC2 (subscribes to `sleep/#`, inserts to RDS)
- [ ] Run bridge as a `systemd` service

### Week 3 — Auth and API
- [ ] Create Cognito User Pool + Doctor/Patient groups
- [ ] Create test users, assign groups
- [ ] Build Lambda functions (patients, sessions, readings, alerts endpoints)
- [ ] Create HTTP API Gateway + Cognito JWT authorizer
- [ ] Test full auth flow end-to-end

### Week 4 — React Native app
- [ ] Update `mqttService.js` (host, port 443, useSSL, credentials)
- [ ] Replace `mockAuth.js` with Amplify Auth
- [ ] Replace mock data fetches with real API Gateway calls
- [ ] Test on physical device on mobile data (not just same Wi-Fi)
