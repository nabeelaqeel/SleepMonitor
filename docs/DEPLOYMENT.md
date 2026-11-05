# Deployment Runbook (AWS Learner Lab)

Instructions only — execute top to bottom. Every step shows **where** you type it, the command, and the expected result. All rationale, constraints, costs, and tradeoffs live in [`DEPLOYMENT_NOTES.md`](DEPLOYMENT_NOTES.md).

```
You type here:     💻 laptop    — your machine, repo root unless stated
                   🖥  EC2       — in the ssh session on the server
                   🖱 console    — AWS Academy web console (clicks, no terminal)
```

---

## 0. PRE-CHECK

```bash
# 💻 laptop — EAS logged in?
npx eas-cli whoami                          # expect: meowplayer

# 💻 laptop — is the repo on a remote?
git remote -v                               # URL shown? → commit + push (next line)
# if a remote exists:
git add -A && git commit -m "Phase 0: AWS deploy prep" && git push
```

No remote? Use Option B in step 2.2. Phase 0 files (`docker-compose.aws.yml`, `mosquitto/mosquitto.conf`, `app/eas.example.json`) already exist in the repo — nothing else to prepare. (Fresh checkout? `cd app && cp eas.example.json eas.json` before §4.2 — your local `eas.json` stays gitignored.)

---

## 1. CREATE THE EC2 INSTANCE

Step 1.1 — 🖱 console: **Start Lab** → AWS Console (region is fixed for you) → EC2 → Launch instance

| Setting | Value |
|---|---|
| AMI | Ubuntu 24.04 LTS |
| Instance type | t3.micro |
| Key pair | create `sm-key.pem`, then on laptop: `chmod 400 sm-key.pem` |
| Instance name | `sleepmonitor` |

`sm-sg` security group — inbound rules:

| Port | Source | Purpose |
|---|---|---|
| 22 | your IP, or `0.0.0.0/0` while demoing | ssh |
| 1883 | your IP (operator MQTT checks) | MQTT TCP — the phone only ever uses 9001; tighten this rule's source after §3.2 (NOTES §8) |
| 9001 | `0.0.0.0/0` | MQTT WebSocket — the app's only broker path |
| 8000 | `0.0.0.0/0` | Auth API — login |

**5432 must NOT appear in `sm-sg`.** The database is AWS RDS and gets its own security group in §2.3 (source = this instance's `sg` only).

Launch, then copy **Public IPv4** from the instance page → `<EC2_IP>` for every step below.

---

## 2. SERVER SETUP

```bash
# Step 2.1 — first ssh + Docker + Compose + psql client
WHERE: 💻 laptop
ssh -i sm-key.pem ubuntu@<EC2_IP>

# Step 2.2 — now inside: 🖥 EC2
sudo apt update
sudo apt install -y docker.io docker-compose-v2 postgresql-client
sudo usermod -aG docker ubuntu
exit
```

```bash
# Step 2.3 — re-ssh so the docker group applies
WHERE: 💻 laptop
ssh -i sm-key.pem ubuntu@<EC2_IP>        # 🖥 EC2 from here until §3

docker version && docker compose version   # both print versions — Docker ✔
```

**Step 2.4 — get the repo** — pick ONE (both need the target dir ready first):

```bash
sudo mkdir -p /opt/SleepMonitor && sudo chown ubuntu:ubuntu /opt/SleepMonitor
```

```bash
# Option A — git (you have a remote + pushed, see §0)
git clone https://github.com/<you>/SleepMonitor.git /opt/SleepMonitor
```

```bash
# Option B — scp tarball (no remote)
# 💻 laptop first:
tar --exclude='node_modules' --exclude='.venv*' --exclude='.git' \
    --exclude='benchmark' --exclude='graphify-out' \
    -czf sm.tar.gz .
scp -i sm-key.pem sm.tar.gz ubuntu@<EC2_IP>:/tmp/

# then 🖥 EC2:
tar -xzf /tmp/sm.tar.gz -C /opt/SleepMonitor/
```

Step 2.5 — 🖱 console: create the **RDS database** *(DEMO mode only — skip if this session is test-only; the `.env` DEMO line then stays a placeholder until demo day, runbook §5)*

| Setting | Value |
|---|---|
| Engine | PostgreSQL (16.x) |
| Templates | Free tier if offered, else db class manually |
| DB instance identifier | `sleep-monitor-pg` (same identifier on every future recreation → same endpoint) |
| Instance config | db.t3.micro, 20 GB, autoscaling OFF |
| Master username | `sleep_user` |
| Master password | generate first: 💻 `openssl rand -hex 12` → paste it into the console AND keep it for §2.6–§2.7 |
| Connectivity | default VPC (the lab one), **Public access: No**, create **new VPC security group `sm-rds-sg`**, port 5432 |
| Database authentication | Password authentication |
| Additional config | **Initial database name: `sleep_monitor`** — Backup retention: **0 days** — Encryption at rest: keep **enabled** (already the default) |

Still 🖱 console — after creation finishes (~5–10 min), wire the security group: **EC2 → Security Groups → `sm-rds-sg` → Inbound rules → Add rule**: PostgreSQL `5432`, source = **type Security group** → `sm-sg`. Only your EC2 may ever reach the DB.

```bash
# Step 2.6 — collect the RDS values once, apply the schema
WHERE: 🖥 EC2
cd /opt/SleepMonitor
read -rp  'RDS endpoint (from §2.5 console): ' RDS_ENDPOINT
read -rsp 'RDS master password (§2.5): ' RDS_PW && echo
export PGPASSWORD="$RDS_PW"

PGPASSWORD="$RDS_PW" psql -h "$RDS_ENDPOINT" -U sleep_user -d sleep_monitor \
  -f postgres/init/01_schema.sql        # expect: CREATE TABLE / CREATE INDEX lines
PGPASSWORD="$RDS_PW" psql -h "$RDS_ENDPOINT" -U sleep_user -d sleep_monitor -c "SELECT 1;"
# expect: 1 row, "1"
```

> **Why psql, not compose:** `postgres/init/01_schema.sql` only auto-applies on a *fresh local Docker volume* — there is no such volume for RDS, so every fresh RDS gets the schema applied exactly once with `-f`.

```bash
# Step 2.7 — write .env.development (the runtime env file — the naming is
# hardcoded in the Python services, see DEPLOYMENT_NOTES §4)
WHERE: 🖥 EC2 (same ssh session as §2.6 if RDS was created — it reuses $RDS_ENDPOINT / $RDS_PW)
cd /opt/SleepMonitor
LOCAL_PW="$(openssl rand -hex 12)"     # local TEST-mode DB password (mode §6.2b uses it too)
# DEMO line: bake the §2.5/§2.6 values when RDS was created this session;
# skip-RDS sessions must NOT embed empty strings — keep literal markers instead
if [ -n "${RDS_ENDPOINT:-}" ] && [ -n "${RDS_PW:-}" ]; then
  RDS_LINE="DATABASE_URL=postgresql://sleep_user:$RDS_PW@$RDS_ENDPOINT:5432/sleep_monitor?sslmode=require"
else
  RDS_LINE="# DATABASE_URL=postgresql://sleep_user:<FILL_RDS_PW>@<FILL_RDS_ENDPOINT>:5432/sleep_monitor?sslmode=require"
fi
cat > .env.development <<EOF
COMPOSE_PROJECT_NAME=sleep-monitor

# ── DATABASE: pick exactly ONE active line (the other stays commented) ──
# TEST mode (default): EC2-local Docker Postgres (--profile local-db, §5)
DATABASE_URL=postgresql://sleep_user:$LOCAL_PW@localhost:5432/sleep_monitor
# DEMO mode: AWS RDS (requires the §2.5 instance; created + deleted with the session)
$RDS_LINE

# TEST-mode local database credentials (compose interpolation, --profile local-db)
POSTGRES_DB=sleep_monitor
POSTGRES_USER=sleep_user
POSTGRES_PASSWORD=$LOCAL_PW

JWT_SECRET=<FILL_JWT_SECRET>
SEED_DEMO_USERS=true
# demo accounts are seeded (patient@sleep.com / 1234) — they are what the
# evaluation logs in with; flip to false and provision your own users
# (api.security.hash_password) for anything beyond the demo.

MQTT_HOST=localhost
MQTT_PORT=1883
# Broker credentials — parity with the AWS deployment:
MQTT_USER=sm
MQTT_PASSWORD=<FILL_MQTT_PASSWORD>

INGEST_CLIENT_ID=sleep-ingest-001
SESSION_EXPIRY=3600
FLUSH_INTERVAL=1.0
FLUSH_MAX=50

PATIENT_ID=patient-001
PATIENT_UUID=00000000-0000-0000-0000-000000000002
DEVICE_ID=sleepband-001

CSV_PATH=data/sleep_data_realistic.csv
PUBLISH_INTERVAL=1.0
LOOP_CSV=true
EOF

# replace the remaining two placeholder secrets — generated here, never committed;
# in DEMO sessions where RDS was created (§2.6), the RDS line above already
# carries the §2.5/§2.6 values
sed -i -e "s/<FILL_JWT_SECRET>/$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
       -e "s/<FILL_MQTT_PASSWORD>/$(openssl rand -hex 12)/" .env.development

grep -c '^[^#]*<FILL' .env.development   # expect: 0 — ACTIVE-line placeholders only;
                                         # the TEST path's commented DEMO line may
                                         # legitimately carry <FILL_RDS_*> markers (§5 flip)
grep '^DATABASE_URL' .env.development | sed 's/:.*@/@/';   # expect: localhost line ACTIVE (test default)
```

> **DATABASE_URL cheat sheet:** the TEST default needs no RDS — flip to DEMO by commenting the localhost line, uncommenting the RDS line (§2.5 gave the endpoint/password), then restarting the two units (the §5 flip block). `?sslmode=require` is what makes every RDS connection TLS-encrypted — do not drop it from the demo line. `POSTGRES_*` keys exist solely for the `local-db` profile interpolation.

```bash
# Step 2.8 — swap (1 GiB RAM headroom)
WHERE: 🖥 EC2
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h    # expect: Swap row shows 2.0Gi
```

```bash
# Step 2.9 — broker passwd (BEFORE first broker start — it refuses without it)
WHERE: 🖥 EC2, still in /opt/SleepMonitor
MQPW="$(grep '^MQTT_PASSWORD=' .env.development | cut -d= -f2-)"
docker run --rm -v "$PWD/mosquitto:/mosquitto/config" eclipse-mosquitto:2 \
  mosquitto_passwd -c -b /mosquitto/config/passwd sm "$MQPW"
# the broker drops to its internal non-root user (uid 1883), and mosquitto
# 2.1+ WARNs (future: refuses) files with other ownership — validated recipe:
sudo chown 1883:1883 mosquitto/passwd
sudo chmod 600 mosquitto/passwd

ls -l mosquitto/passwd                    # expect: exists, owner = 1883, mode 600
```

```bash
# Step 2.10 — start the broker (TEST mode also brings the local DB when profiled)
WHERE: 🖥 EC2
cd /opt/SleepMonitor
# --env-file is REQUIRED on every compose call — even profile-gated services
# are interpolated, and compose only auto-loads `.env`, not .env.development:
# DEMO mode (RDS line active): broker only
docker compose -f docker-compose.aws.yml --env-file .env.development up -d
# TEST mode (localhost line active): ALSO bring the local DB — do this BEFORE
# starting systemd services (publisher/ingest write at boot):
docker compose -f docker-compose.aws.yml --env-file .env.development --profile local-db up -d
# wait up to 60s for EXACT 'healthy' ('unhealthy' must NOT satisfy this),
# and abort loudly if it never arrives:
for i in $(seq 1 12); do
  [ "$(docker inspect --format '{{.State.Health.Status}}' sleep-postgres)" = "healthy" ] && break
  sleep 5
done
[ "$(docker inspect --format '{{.State.Health.Status}}' sleep-postgres)" = "healthy" ] || { echo "sleep-postgres failed to reach healthy within 60s — check: docker logs sleep-postgres"; exit 1; }
docker ps --format 'table {{.Names}}\t{{.Status}}'
# expect: sleep-broker Up (+ sleep-postgres Up & healthy in TEST mode)
docker logs sleep-broker   # expect: "Opening ipv4 listen socket on port 9001."
```

```bash
# Step 2.11 — host venv + the four Python services
WHERE: 🖥 EC2
cd /opt/SleepMonitor
python3 -m venv .venv
.venv/bin/pip install -r api/requirements.txt -r ingest/requirements.txt -r publisher/requirements.txt
# expect: "Successfully installed ..." (a few minutes first time)
```

```bash
# Step 2.12 — systemd units (all four, once, paste as-is)
WHERE: 🖥 EC2
sudo tee /etc/systemd/system/sm-api.service > /dev/null <<'EOF'
[Unit]
Description=SleepMonitor auth API
After=network-online.target docker.service
Requires=docker.service

[Service]
WorkingDirectory=/opt/SleepMonitor
ExecStart=/opt/SleepMonitor/.venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/sm-ingest.service > /dev/null <<'EOF'
[Unit]
Description=SleepMonitor MQTT ingest worker
After=network-online.target docker.service
Requires=docker.service

[Service]
WorkingDirectory=/opt/SleepMonitor
ExecStart=/opt/SleepMonitor/.venv/bin/python ingest/worker.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/sm-pub.service > /dev/null <<'EOF'
[Unit]
Description=SleepMonitor fake-device publisher
After=network-online.target docker.service
Requires=docker.service

[Service]
WorkingDirectory=/opt/SleepMonitor
ExecStart=/opt/SleepMonitor/.venv/bin/python publisher/publisher.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/sm-echo.service > /dev/null <<'EOF'
[Unit]
Description=SleepMonitor MQTT echo responder
After=network-online.target docker.service
Requires=docker.service

[Service]
WorkingDirectory=/opt/SleepMonitor
ExecStart=/opt/SleepMonitor/.venv/bin/python publisher/echo.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now sm-api sm-ingest sm-pub sm-echo
systemctl is-active sm-api sm-ingest sm-pub sm-echo
# expect:
#   active
#   active
#   active
#   active

# anything not "active"? look at the logs:
journalctl -u sm-api -n 30 --no-pager      # (or -u sm-ingest / sm-pub / sm-echo)
```

---

## 3. VERIFY FROM THE LAPTOP

```bash
# Step 3.1 — auth API round-trip (real bcrypt checks against RDS now)
WHERE: 💻 laptop
curl -sS -X POST http://<EC2_IP>:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"patient@sleep.com","password":"1234"}'
# expect: JSON containing "token"
```

```bash
# Step 3.2 — live MQTT tap (broker is LOCKED: -u/-P required)
WHERE: 💻 laptop (needs mosquitto-clients installed — README prerequisite)
# <BROKER_PASSWORD> = the §2.9 value — grep '^MQTT_PASSWORD=' .env.development (on the server)
mosquitto_sub -h <EC2_IP> -p 1883 -t 'sleep/#' -u sm -P '<BROKER_PASSWORD>' -v
# expect: one JSON reading per PUBLISH_INTERVAL (default 1s), e.g.:
#   sleep/normal {"patientId":"patient-001","tier":"Normal",...}
```

# Step 3.3 — the DB is receiving (query the ACTIVE mode's DB)
WHERE: 🖥 EC2
# TEST mode active (localhost) → check inside the container:
docker exec sleep-postgres psql -U sleep_user -d sleep_monitor -c "SELECT count(*) FROM readings;"
# DEMO mode active (RDS) → check over TLS:
PGPASSWORD='<master password from §2.5>' psql -h "<RDS_ENDPOINT>" -U sleep_user -d sleep_monitor \
  -c "SELECT count(*) FROM readings;"
# expect: a count that grows every second while the publisher streams
# count stuck at 0? → wrong active DATABASE_URL — see §7

All three green → backend live. Continue to the app section.

---

## 4. THE APP

```bash
# Step 4.1 — dress rehearsal in Expo Go (finds broken config BEFORE the build)
WHERE: 💻 laptop, repo root, then app/
cd app
sed -i -e 's/^EXPO_PUBLIC_BROKER_IP=.*/EXPO_PUBLIC_BROKER_IP=<EC2_IP>/' \
       -e 's|^EXPO_PUBLIC_API_URL=.*|EXPO_PUBLIC_API_URL=http://<EC2_IP>:8000|' .env.development
# login against a PUBLIC IP needs the demo transport flag — it is already in
# app/.env.development (EXPO_PUBLIC_ALLOW_PLAIN_HTTP=true); runbook context: NOTES §8
npx expo start
# scan the QR with Expo Go on your phone
```

Expected: login as `patient@sleep.com` / `1234` → Home shows live vitals, badge on Alert screen fires, Network screen shows broker CONNECTED.

```bash
# Step 4.2 — bake IP + broker password into the release config
WHERE: 💻 laptop, app/
# eas.json is GITIGNORED (template: eas.example.json) — values stay
# machine-local and never reach the repo. <BROKER_PASSWORD> is the §2.9 value
# again (grep it on the server).
cd app
# scope: builds run on the PREVIEW profile (§4.3) — its placeholders get filled
# here only; the production profile keeps ITS OWN unfilled placeholders
# (deliberately unfilled — fail-closed, see DEPLOYMENT_NOTES §3).
# Profile-aware fill (python touches build.preview only — global seds would
# also replace the production placeholders, which must stay):
python3 - <<'EOF'
import json

p = json.load(open("eas.json"))
pv = p["build"]["preview"]["env"]
pv["EXPO_PUBLIC_BROKER_IP"] = "<EC2_IP>"
pv["EXPO_PUBLIC_API_URL"] = "http://<EC2_IP>:8000"
pv["EXPO_PUBLIC_MQTT_PASSWORD"] = "<BROKER_PASSWORD>"
json.dump(p, open("eas.json", "w"), indent=2)

# .env.local mirrors the same values — SDK 54 `eas update` (§6.3) publishes
# read envs from local .env files, NOT from the eas.json profile env block
open(".env.local", "w").write(
    "EXPO_PUBLIC_BROKER_IP=<EC2_IP>\n"
    "EXPO_PUBLIC_API_URL=http://<EC2_IP>:8000\n"
    "EXPO_PUBLIC_MQTT_USER=sm\n"
    "EXPO_PUBLIC_MQTT_PASSWORD=<BROKER_PASSWORD>\n"
    "EXPO_PUBLIC_ALLOW_PLAIN_HTTP=true\n")
EOF
grep SET_ME eas.json                        # expect EXACTLY 2 lines — the consciously
                                            # unfilled production placeholders
                                            # (SET_ME_EC2_PUBLIC_IP, SET_ME_HTTPS_ENDPOINT, NOTES §3)
grep -c "^EXPO_PUBLIC" .env.local           # expect: 5
```

```bash
# Step 4.3 — build the APK
WHERE: 💻 laptop, app/
npx eas-cli build -p android --profile preview --non-interactive
# expect: "Waiting for build..." + a URL — takes ~15–25 min
# (safety net: the build aborts if a SET_ME placeholder remains in eas.json —
#  app/app.config.js fails the config evaluation; fix §4.2 and re-run)
```

Step 4.4 — install: open the build URL → download `SleepMonitor.apk` → move to phone → allow install from unknown sources → install → log in with the test credentials.

---

## 5. OPERATIONS RUNBOOK (every session)

```
🖱 console (both in parallel, ~5–10 min):
   A. RDS: Create database — same settings as §2.5, same identifier
      (sleep-monitor-pg) and SAME master password → same endpoint string;
      "Encryption at rest" stays enabled. When up: re-attach the sm-rds-sg
      rule (5432 from sm-sg) if the console created a fresh SG.
   B. EC2: Start your instance → copy Public IPv4 (no EIP? it CHANGED)
      Both services flip healthy around the same minute.
```

```bash
# 🖥 EC2 — check everything came back:
docker ps --format 'table {{.Names}}\t{{.Status}}'     # sleep-broker up
systemctl is-active sm-api sm-ingest sm-pub sm-echo    # 4× active
# TEST mode active? the local DB container is up when you passed
# --profile local-db on the compose up (see line 2.7 below);
# DEMO mode: re-apply the schema on a re-created RDS:
PGPASSWORD='<master password>' psql -h "<RDS_ENDPOINT>" -U sleep_user -d sleep_monitor \
  -f postgres/init/01_schema.sql
```

```bash
# 🖥 EC2 — SWITCH TO DEMO MODE (before an evaluation; flip back afterwards):
#  1. RDS instance up (§2.5/§2.6 — skip if it's already running from this session)
#  2. STOP the publisher BEFORE flipping — it owns the session lifecycle
#     (an abrupt swap leaves an open session: no session/end in the old DB):
sudo systemctl stop sm-pub
sleep 2                                  # let the ingest flush the session/end
#  3. flip the two DATABASE_URL lines in .env.development (nano):
#     → '#' the TEST localhost line
#     → uncomment the RDS line (keeps ?sslmode=require)
#  4. restart the two DB-reading units (publisher/echo idle during the swap):
sudo systemctl restart sm-api sm-ingest
systemctl is-active sm-api sm-ingest     # 2× active
#  5. only NOW resume streaming into the new DB — session/start lands there:
sudo systemctl start sm-pub
sudo systemctl is-active sm-pub          # active
# back to TEST after the demo: stop sm-pub → reverse the comment swap →
# restart sm-api sm-ingest → start sm-pub again.
# phone impact: none — the app never talks to the database.
```

```bash
# 💻 laptop — confirm the demo is live before an evaluation:
curl -sS -X POST http://<IP>:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"patient@sleep.com","password":"1234"}'
# -P <BROKER_PASSWORD>: the §2.9 value again (grep it on the server)
mosquitto_sub -h <IP> -p 1883 -t 'sleep/#' -u sm -P '<BROKER_PASSWORD>' -v
```

```bash
# 🖥 EC2 — DB count check (the RDS SG admits only the EC2; TEST mode → §3.3):
WHERE: 🖥 EC2
cd /opt/SleepMonitor
# values derived from the ACTIVE .env.development — no manual re-entry:
EP=$(grep '^DATABASE_URL=' .env.development | sed 's/.*@//; s/:5432.*//')
PW=$(grep '^DATABASE_URL=' .env.development | sed 's|.*://sleep_user:||; s|@.*||')
PGPASSWORD="$PW" psql -h "$EP" -U sleep_user -d sleep_monitor \
  -c "SELECT count(*) FROM readings;"
# expect: a count that grows every second (fresh RDS without re-apply? §5 re-apply step)
```

**Session end (⚠ order matters — delete RDS FIRST, then End Lab):**

🖱 RDS → `sleep-monitor-pg` → Actions → **Delete** → **UNCHECK "Create final snapshot"** → confirm. A retained snapshot keeps billing; skipping it means the next session recreates from `01_schema.sql` instead (~$0.10–0.20 saved/steady-state).

| Activity | Cost |
|---|---|
| t3.micro running ~8h/day, 20 days | ≈ $3–4 term |
| EBS 30 GB gp3 persistent | ≈ $2–3/mo |
| **RDS per-session (created + deleted each session)** | **≈ $0.10–0.20 per session — the delete is what keeps this true** |
| Elastic IP attached (even when stopped) | ≈ $3.6/mo — an additional drain on top of EBS, which also keeps billing while stopped |

Leaving for a long break? Release the Elastic IP (accepting an OTA re-pin via §6.3) and let RDS/EC2 stay deleted.

---

## 6. SHIP CHANGES AFTER THE FIRST DEPLOY

First, classify the change:

| You changed… | Go to |
|---|---|
| Backend Python (`api/`, `ingest/`, `publisher/`) | 6.1 |
| Broker config (`mosquitto/mosquitto.conf`) | 6.2a — non-destructive restart only |
| Database schema (`postgres/init/01_schema.sql`) | 6.2b — re-apply on the ACTIVE database (TEST volume or RDS) |
| App JS code (screens, logic) | 6.3 — cheap OTA |
| `app.json`, plugins, icons, native deps | 6.4 — only path |
| `EXPO_PUBLIC_*` values in `app/eas.json` (via `eas build`) | 6.4 rebuild — `eas update` does NOT read the `eas.json` env block (NOTES §7) |
| `EXPO_PUBLIC_*` values in `app/.env.local` (via OTA updates) | 6.3 OTA |

```bash
# 6.1 — backend fix
WHERE: 💻 laptop   (commit, push)
git add . && git commit -m "..." && git push
# Then 🖥 EC2:
cd /opt/SleepMonitor && git pull          # Option B deployments: scp a new tarball
.venv/bin/pip install -r api/requirements.txt -r ingest/requirements.txt -r publisher/requirements.txt   # only if requirements changed
sudo systemctl restart sm-api             # + the unit(s) you touched
systemctl is-active sm-api                # expect: active
```

```bash
# 6.2a — broker config change (non-destructive restart)
WHERE: 🖥 EC2
cd /opt/SleepMonitor
# --env-file required on EVERY compose call (profile-gated services still get
# interpolated, and compose only auto-loads `.env` — never our `.env.development`):
docker compose -f docker-compose.aws.yml --env-file .env.development restart broker
docker logs sleep-broker --tail 20    # expect: "Opening ... port 9001" again

# 6.2b — schema change (SESSION-SAFE reset: the publisher owns session/end)
WHERE: 🖥 EC2
cd /opt/SleepMonitor
# 0. stop the stream BEFORE touching the schema:
sudo systemctl stop sm-pub && sleep 2             # session/end flushed into the OLD db
sudo systemctl stop sm-ingest
SQL="backup-$(date +%F-%H%M).sql"

# ── TEST branch (active DATABASE_URL = localhost):
docker exec sleep-postgres pg_dump -U sleep_user -d sleep_monitor > "$SQL" || { echo "pg_dump FAILED — aborting"; exit 1; }
[ -s "$SQL" ] || { echo "backup EMPTY — aborting"; exit 1; }
docker compose -f docker-compose.aws.yml --env-file .env.development --profile local-db down -v
docker compose -f docker-compose.aws.yml --env-file .env.development --profile local-db up -d
# wait up to 60s for EXACT 'healthy' ('unhealthy' must NOT satisfy this),
# and abort loudly if it never arrives:
for i in $(seq 1 12); do
  [ "$(docker inspect --format '{{.State.Health.Status}}' sleep-postgres)" = "healthy" ] && break
  sleep 5
done
[ "$(docker inspect --format '{{.State.Health.Status}}' sleep-postgres)" = "healthy" ] || { echo "sleep-postgres failed to reach healthy within 60s — check: docker logs sleep-postgres"; exit 1; }

# ── DEMO branch (active DATABASE_URL = RDS):
# atomic reset: DROP + re-apply in ONE transaction (ON_ERROR_STOP → rollback)
# one silent prompt for the master password — keeps it out of shell history:
read -rsp 'RDS master password: ' RDS_PW < /dev/tty && echo
PGPASSWORD="$RDS_PW" \
  pg_dump -h "<RDS_ENDPOINT>" -U sleep_user -d sleep_monitor > "$SQL" || { echo "pg_dump FAILED — aborting"; exit 1; }
[ -s "$SQL" ] || { echo "backup EMPTY — aborting"; exit 1; }
PGPASSWORD="$RDS_PW" psql -v ON_ERROR_STOP=1 -1 \
  -h "<RDS_ENDPOINT>" -U sleep_user -d sleep_monitor \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" \
  -f postgres/init/01_schema.sql

# bring services back IN ORDER (api+ingest on the fresh schema, then streaming):
sudo systemctl restart sm-api sm-ingest && systemctl is-active sm-api sm-ingest
sudo systemctl start sm-pub && systemctl is-active sm-pub
```

```bash
# 6.3 — app JS code: OTA (2 min, no rebuild, no reinstall)
WHERE: 💻 laptop, app/
cd app
npx eas-cli update --branch preview --message "what and why in plain words"
# expect: "Update published" + an update ID

# EXPO_PUBLIC_* value changes ride 6.3 ONLY through app/.env.local:
# on SDK 54 `eas update` reads local .env files — NOT the eas.json profile
# env block (that feeds eas build only). Keep both sources in sync, publish,
# and rebuild via 6.4 whenever phones can't reach EAS (NOTES §7 trade-offs).
```

```bash
# 6.4 — app config/native change — full rebuild:
WHERE: 💻 laptop, app/
cd app
npx eas-cli build -p android --profile preview --non-interactive
# → download → sideload again (as in §4.4)
```

---

## 7. TROUBLESHOOTING

| Symptom | Run | Likely fix |
|---|---|---|
| API "RuntimeError: JWT_SECRET …" at start | `journalctl -u sm-api -n 20` | regenerate: it rejects `.env.example` placeholder values (`change_me…`) by design |
| broker refuses to start / no "Opening port 9001" | `docker logs sleep-broker --tail 20` | passwd file missing — repeat §2.9 |
| mosquitto_sub says "not authorised" | re-run §3.2 | `-u sm -P '<BROKER_PASSWORD>'` (the §2.9-generated value) is mandatory — the broker is locked |
| psql: "could not connect … timeout" to RDS | §2.5 SG step | `sm-rds-sg` inbound rule must source `sm-sg` (not 0.0.0.0/0) — instance and DB must share the VPC |
| psql / API: "password authentication failed" | grep the env file | master password mismatch between §2.5 console value and §2.7 `DATABASE_URL` |
| DB tables missing after a fresh RDS | §5 re-apply step | `01_schema.sql` is per-fresh-instance: run the `-f` apply |
| App "Broker: disconnected" after lab restart | §5 commands | IP changed without an EIP — §6.4 rebuild with the new IP, or re-pin via §6.3/§6.4 (NOTES §5) |
| Login throws "Refusing to send credentials over plain HTTP" | read the thrown host | `assertSecureEndpoint` blocks public plain-HTTP unless `EXPO_PUBLIC_ALLOW_PLAIN_HTTP=true` is baked — `app/.env.development` for the rehearsal, `eas.json` → rebuild/OTA for APKs (NOTES §8) |
| `eas build` fails immediately | `npx eas-cli whoami` | not logged in, or `eas.example.json` not copied to `eas.json` (§0) |
| streams live but `SELECT count(*)` stays 0 | check the active line with `grep '^DATABASE_URL' .env.development` | you queried the INACTIVE DB — flip §2.7's DATABASE_URL to the other mode and `systemctl restart sm-api sm-ingest` |
| Budget exhausted / lab locked | 🖱 console cost page | standing drains ranked: Elastic IP (~$3.6/mo idle) > EBS (~$2.4/mo) > everything else; RDS per-session is deleted before ending (NOTES §2) |

---

*Everything below step headings is mandatory order. Reading order — this file is opinionated; the why for each step is one short chapter away: [`DEPLOYMENT_NOTES.md`](DEPLOYMENT_NOTES.md).*
