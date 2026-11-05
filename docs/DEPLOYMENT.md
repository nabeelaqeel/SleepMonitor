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

No remote? Use Option B in step 2.2. Phase 0 files (`docker-compose.aws.yml`, `mosquitto/mosquitto.conf`, `app/eas.example.json`) already exist in the repo — nothing else to prepare. (Fresh checkout? `cd app && cp eas.example.json eas.json` — your local `eas.json` is gitignored.)

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
| 22 | `0.0.0.0/0` | ssh |
| 1883 | your IP (operator MQTT checks) | MQTT TCP — the phone only ever uses 9001; tighten this rule's source after §3.2 (NOTES §8) |
| 9001 | `0.0.0.0/0` | MQTT WebSocket — the app's only broker path |
| 8000 | `0.0.0.0/0` | Auth API — login |

Do **not** add 5432. Launch, then copy **Public IPv4** from the instance page → `<EC2_IP>` for every step below.

---

## 2. SERVER SETUP

```bash
# Step 2.1 — first ssh + Docker + Compose
WHERE: 💻 laptop
ssh -i sm-key.pem ubuntu@<EC2_IP>

# Step 2.2 — now inside: 🖥 EC2
sudo apt update
sudo apt install -y docker.io docker-compose-v2
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

```bash
# Step 2.5 — write .env.development (gitignored, two filler slots)
WHERE: 🖥 EC2
sudo apt install -y openssl python3           # already present on Ubuntu 24.04, harmless
cd /opt/SleepMonitor
cat > .env.development <<'EOF'
COMPOSE_PROJECT_NAME=sleep-monitor

POSTGRES_DB=sleep_monitor
POSTGRES_USER=sleep_user
POSTGRES_PASSWORD=<FILL_PG_PASSWORD>
DATABASE_URL=postgresql://sleep_user:<FILL_PG_PASSWORD>@localhost:5432/sleep_monitor

JWT_SECRET=<FILL_JWT_SECRET>
# demo accounts are seeded (patient@sleep.com / 1234) — they are what the
# evaluation logs in with; flip to false and provision your own users
# (api.security.hash_password) for anything beyond the demo.
SEED_DEMO_USERS=true

MQTT_HOST=localhost
MQTT_PORT=1883
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

# replace the placeholders with real values, same file — all three secrets are
# generated at deploy time and never carried by the repo:
sed -i -e "s/<FILL_PG_PASSWORD>/$(openssl rand -hex 12)/g" \
       -e "s/<FILL_JWT_SECRET>/$(python3 -c 'import secrets; print(secrets.token_hex(32))')/g" \
       -e "s/<FILL_MQTT_PASSWORD>/$(openssl rand -hex 12)/g" .env.development

grep -c "FILL_" .env.development          # expect: 0
```

```bash
# Step 2.6 — swap (1 GiB RAM headroom)
WHERE: 🖥 EC2
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h    # expect: Swap row shows 2.0Gi
```

```bash
# Step 2.7 — broker passwd (BEFORE first broker start — it refuses without it)
WHERE: 🖥 EC2, still in /opt/SleepMonitor
cd /opt/SleepMonitor
# the broker password is the one §2.5 generated into .env.development —
# read it from there so the command and the file can never disagree:
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
# Step 2.8 — start Postgres + broker
WHERE: 🖥 EC2
cd /opt/SleepMonitor
docker compose -f docker-compose.aws.yml --env-file .env.development up -d
sleep 20
docker ps --format 'table {{.Names}}\t{{.Status}}'
# expect:
#   sleep-broker        Up ...          (any Up)
#   sleep-postgres      Up ... (healthy)
```

```bash
# Step 2.9 — venv + the four Python services
WHERE: 🖥 EC2
cd /opt/SleepMonitor
python3 -m venv .venv
.venv/bin/pip install -r api/requirements.txt -r ingest/requirements.txt -r publisher/requirements.txt
# expect: "Successfully installed ..." (a few minutes first time)
```

```bash
# Step 2.10 — systemd units (all four, once, paste as-is)
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
```

```bash
# Step 2.11 — enable + start everything
WHERE: 🖥 EC2
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
# Step 3.1 — auth API round-trip
WHERE: 💻 laptop
curl -sS -X POST http://<EC2_IP>:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"patient@sleep.com","password":"1234"}'
# expect: JSON containing "token"
```

```bash
# Step 3.2 — live MQTT tap (broker is LOCKED: -u/-P required)
WHERE: 💻 laptop (needs mosquitto-clients installed — README prerequisite)
# <BROKER_PASSWORD> = the §2.5 value: grep '^MQTT_PASSWORD=' .env.development (on the server)
mosquitto_sub -h <EC2_IP> -p 1883 -t 'sleep/#' -u sm -P '<BROKER_PASSWORD>' -v
# expect: one JSON reading per PUBLISH_INTERVAL (default 1s), e.g.:
#   sleep/normal {"patientId":"patient-001","tier":"Normal",...}
```

Both green → backend live. Continue to the app section.

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

Expected: login as `patient@sleep.com` / `1234` → Home shows live vitals, badge on Alert screen fires, Network screen shows broker CONNECTED. (Your old laptop IPs are `192.168.0.29` if you want to revert later.)

```bash
# Step 4.2 — bake IP + broker password into the release config
WHERE: 💻 laptop, app/
# eas.json is GITIGNORED (template: eas.example.json) — values stay
# machine-local and never reach the repo. <BROKER_PASSWORD> is the §2.5 value
# again (grep it on the server).
cd app
# scope: builds run on the PREVIEW profile (§4.3) — its two placeholders are
# filled here. Production deliberately keeps SET_ME_HTTPS_ENDPOINT (fail-closed:
# no build, no login until a real https endpoint + TLS exist — NOTES §8), so the
# check below expects exactly ONE remaining SET_ME line.
sed -i -e 's/SET_ME_EC2_PUBLIC_IP/<EC2_IP>/g' \
       -e 's/SET_ME_MQTT_PASSWORD/<BROKER_PASSWORD>/g' eas.json
# mirror the same values into app/.env.local — SDK 54 `eas update` (§6.3)
# reads envs from local .env files, NOT from the eas.json profile env block
cat > .env.local <<'EOF'
EXPO_PUBLIC_BROKER_IP=<EC2_IP>
EXPO_PUBLIC_API_URL=http://<EC2_IP>:8000
EXPO_PUBLIC_MQTT_USER=sm
EXPO_PUBLIC_MQTT_PASSWORD=<BROKER_PASSWORD>
EXPO_PUBLIC_ALLOW_PLAIN_HTTP=true
EOF
grep SET_ME eas.json                        # expect ONLY: "SET_ME_HTTPS_ENDPOINT" (production, see above)
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

Step 4.4 — install: open the build URL → download `SleepMonitor.apk` → move to phone → allow install from unknown sources → install → log in with the test credentials. **From now on, this APK performs with zero maintenance as long as `<EC2_IP>` settles (Elastic IP).**

---

## 5. EVERY LAB SESSION

```bash
# 🖱 console: Start Lab → EC2 → Start instance → COPY THE NEW PUBLIC IPv4
# If it differs from what the APK has — you're on a lab without an Elastic IP:
# see DEPLOYMENT_NOTES §5 for the two options (EIP is the fix).
```

```bash
# 🖥 EC2 — check everything came back:
docker ps --format 'table {{.Names}}\t{{.Status}}'     # broker + postgres (healthy)
systemctl is-active sm-api sm-ingest sm-pub sm-echo    # 4× active
```

```bash
# 💻 laptop — confirm the demo is live before an evaluation:
curl -sS -X POST http://<IP>:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"patient@sleep.com","password":"1234"}'
# -P <BROKER_PASSWORD>: the §2.5 value again (grep it on the server)
mosquitto_sub -h <IP> -p 1883 -t 'sleep/#' -u sm -P '<BROKER_PASSWORD>' -v
```

Happy: green everywhere vs APK matching the IP → hand over the phone.

---

## 6. SHIP CHANGES AFTER THE FIRST DEPLOY

First, classify the change:

| You changed… | Go to |
|---|---|
| Backend Python (`api/`, `ingest/`, `publisher/`) | 6.1 |
| Broker config (`mosquitto/mosquitto.conf`) | 6.2a — non-destructive restart only |
| Database schema (`postgres/init/01_schema.sql`) | 6.2b — wipe + re-up (**data loss**; backup first) |
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
# --env-file required: the compose file interpolates POSTGRES_PASSWORD with a
# mandatory `:?` — any compose subcommand without it errors out.
docker compose -f docker-compose.aws.yml --env-file .env.development restart broker
docker logs sleep-broker --tail 20    # expect: "Opening ... port 9001" again

# 6.2b — schema change (DESTRUCTIVE: wipe + re-up; guarded backup first)
WHERE: 🖥 EC2
cd /opt/SleepMonitor
SQL="backup-$(date +%F-%H%M).sql"
docker exec sleep-postgres pg_dump -U sleep_user sleep_monitor > "$SQL" || { echo "pg_dump FAILED — aborting"; exit 1; }
[ -s "$SQL" ] || { echo "backup EMPTY — aborting"; exit 1; }
echo "$SQL ready — review it, then rerun the down to confirm the destructive step"
docker compose -f docker-compose.aws.yml --env-file .env.development down -v     # ⚠ delete stored data
docker compose -f docker-compose.aws.yml --env-file .env.development up -d
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
# 6.4 — app config/native change, or EXPO_PUBLIC_* values — full rebuild:
WHERE: 💻 laptop, app/
cd app
npx eas-cli build -p android --profile preview --non-interactive
# → download → sideload again (as in §4.4)
```

---

## 7. TROUBLESHOOTING

| Symptom | Run | Likely fix |
|---|---|---|
| API "RuntimeError: JWT_SECRET …" on start | `journalctl -u sm-api -n 20` | regenerate: it rejects `.env.example` placeholder values (`change_me…`) by design |
| broker refuses to start / no "Opening port 9001" in logs | `docker logs sleep-broker --tail 20` | passwd file missing — repeat §2.7 |
| mosquitto_sub says "not authorised" | re-run §3.2 | `-u sm -P '<BROKER_PASSWORD>'` (the §2.5-generated value) is mandatory — the broker is locked |
| `sleep-postgres` restart-loop / unhealthy | `docker logs sleep-postgres --tail 20` | password mismatch: §2.5 vs the old volume → match values, or wipe (§6.2b) |
| App "Broker: disconnected" after lab restart | §5 commands | IP changed without an EIP — §6.4 rebuild with new IP, or set up the EIP (NOTES §5) |
| Publisher logs "connection refused" | `docker ps` | broker container not up — §2.8 again |
| `eas build` fails immediately | `npx eas-cli whoami` | not logged in, or `eas.json` missing in `app/` (copy `eas.example.json` → `eas.json`, §0) |
| login throws "Refusing to send credentials over plain HTTP" | read the host in the error | `assertSecureEndpoint` blocks public plain-HTTP unless `EXPO_PUBLIC_ALLOW_PLAIN_HTTP=true` is baked — `app/.env.development` for the rehearsal, `app/eas.json` for APKs (then OTA/rebuild §6.3/6.4); rationale in NOTES §8 |
| Budget exhausted / lab locked | 🖱 console cost page | the Elastic IP is an additional drain (besides persistent EBS) — see NOTES §2 |

---

*Everything below step headings is mandatory order. Reading order — this file is opinionated; the why for each step is one short chapter away: [`DEPLOYMENT_NOTES.md`](DEPLOYMENT_NOTES.md).*
