# Terminal-by-Terminal Run (Host venv)

The Docker-free way to run the whole system: every process starts by hand in
its own terminal, from a host Python venv (`.venv-dev/`). Kept for debugging
without Docker — the containerized stack in the README's
[Run the Full Stack](../README.md#run-the-full-stack) replaces all of this
with one command and is the preferred flow on a fresh laptop.

Each login needs **PostgreSQL + the Auth API**, live data needs the
**Publisher + Expo app**; the others add latency measurement and database
persistence.

| # | Process | Optional? | Run from |
|---|---|---|---|
| 1 | PostgreSQL (Docker) | Optional for the DB demo — **required for login** (credentials are bcrypt-verified against it) | repo root |
| 2 | Ingest worker | Optional — DB demo only | repo root |
| 3 | Auth API | **Required** — login only | repo root |
| 4 | Echo responder | Optional — latency readout only | repo root |
| 5 | Publisher | **Required** | repo root |
| 6 | Expo app | **Required** | `app/` |

All Python commands run **from the repository root** — the scripts resolve
`.env.development` and dataset paths relative to it.

---

## Prerequisites

**1. Env file (first time only).** `.env.development` is gitignored — copy
`.env.example`, then set `MQTT_USER=sm`, a real `MQTT_PASSWORD`,
`POSTGRES_PASSWORD`, and a `JWT_SECRET` (generate one with the snippet below):

```bash
cp .env.example .env.development

JWT_CURRENT=$(grep '^JWT_SECRET=' .env.development | cut -d= -f2- | head -n1)
if [ -z "$JWT_CURRENT" ] || \
   [ "$JWT_CURRENT" = "change_me_random_hex_at_least_32_characters_long" ] || \
   [ "$JWT_CURRENT" = "change_me_random_hex" ]; then
  V=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
  if grep -q '^JWT_SECRET=' .env.development; then
    # awk, not sed -i — GNU sed and BSD/macOS sed disagree on `-i` syntax
    awk -v v="$V" '/^JWT_SECRET=/ { if (!done) { print "JWT_SECRET=" v; done = 1 }; next } { print }' \
      .env.development > .env.development.tmp
    mv .env.development.tmp .env.development
  else
    echo "JWT_SECRET=${V}" >> .env.development
  fi
fi
```

**2. Python venv (first time only).** Install the server-side dependencies
once:

```bash
python3 -m venv .venv-dev
.venv-dev/bin/pip install -r ingest/requirements.txt -r publisher/requirements.txt -r api/requirements.txt
```

**3. Mosquitto running as a system service.** The host-venv flow talks to a
system-installed broker (no terminal needed once enabled). If it is not set
up yet, follow [Broker Setup (Mosquitto)](#broker-setup-mosquitto) below,
then `sudo systemctl enable --now mosquitto`.

**4. Point the services at localhost.** The containerized flow uses the
container hostnames `postgres` / `broker`; the host venv needs the plain
`localhost` variants. Flip the active `DATABASE_URL` and `MQTT_HOST` lines in
`.env.development` (and `.env.example`, so fresh clones default correctly) to
their commented `localhost` values.

> If you previously ran the Docker stack: `docker compose down` first (it
> holds ports 1883/9001/8000).

---

## Terminal 1 — PostgreSQL (optional)

```bash
docker compose --env-file .env.development up -d
docker ps --filter name=sleep-postgres   # wait until STATUS shows "healthy"
```

## Terminal 2 — Ingest worker (optional, leave running)

```bash
.venv-dev/bin/python ingest/worker.py
```

## Terminal 3 — Auth API (required for login, leave running)

```bash
.venv-dev/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Startup seeds bcrypt hashes for the two demo users (only when empty) and then
serves `POST /auth/login` on port 8000 — the app's `EXPO_PUBLIC_API_URL` must
point at this host's LAN IP.

## Terminal 4 — Echo responder (optional, leave running)

```bash
.venv-dev/bin/python publisher/echo.py
```

It answers the app's latency probes. Without it the Network screen shows `—`
for latency; everything else keeps working.

## Terminal 5 — Publisher (leave running)

```bash
.venv-dev/bin/python publisher/publisher.py
```

You should see `Loaded 526 rows from data/sleep_data_realistic.csv`, then one
line per published reading. For a fast replay (handy for DB demos):

```bash
PUBLISH_INTERVAL=0.05 .venv-dev/bin/python publisher/publisher.py
```

## Terminal 6 — Expo app

```bash
cd app && npx expo start
```

Scan the QR code with Expo Go on your phone (same Wi-Fi), then log in as
`patient@sleep.com` / `1234`. Home shows live vitals; Network shows measured
delivery and estimated latency.

## Sanity check (optional)

```bash
# Raw MQTT tap — prints every message the broker routes
mosquitto_sub -h localhost -p 1883 -t "sleep/#" -v
```

Start order does not matter — the app can join a publisher session mid-stream
(the delivery baseline is recorded when the app joins).

---

## Reading the database

If the ingest worker ran, inspect what landed in PostgreSQL:

```bash
docker exec sleep-postgres psql -U sleep_user -d sleep_monitor \
  -c "SELECT * FROM session_stats;"
```

`session_stats.missing_readings` measures QoS 0 loss: with the worker stopped
during a run, only the QoS 1/2 messages are redelivered on restart.

To re-apply schema changes, wipe the volume with
`docker compose --env-file .env.development down -v` — the schema reapplies
from `postgres/init/` on the next boot.

> The echo responder (`publisher/echo.py`) powers the estimated latency
> readout (it relays `qos/ping` → `qos/pong`). For the broker to retain app
> sessions long enough to survive a disconnect, add
> `persistent_client_expiration 2h` to `/etc/mosquitto/mosquitto.conf` and
> restart Mosquitto — abandoned sessions get reaped while queued QoS 1/2
> messages still survive.

See [`docs/DATABASE.md`](DATABASE.md) for the schema, payload fields, and
design details.

---

## Broker Setup (Mosquitto)

One-time setup of the system-installed broker that the host-venv flow uses.
(Skipped on the containerized flow — the README's
[Run the Full Stack](../README.md#run-the-full-stack) starts
`eclipse-mosquitto:2.1.2-alpine` configured by `mosquitto/mosquitto.conf`, already
locked, credentials via `mosquitto/passwd`.)

### 1. Install Mosquitto

```bash
# Ubuntu / Debian
sudo apt install mosquitto mosquitto-clients

# macOS
brew install mosquitto
```

### 2. Enable the WebSocket listener

Create or edit `/etc/mosquitto/conf.d/sleepmonitor.conf` (Linux) or the
equivalent on macOS:

```
listener 1883
allow_anonymous true

listener 9001
protocol websockets
allow_anonymous true
```

Restart the broker:

```bash
# Linux
sudo systemctl restart mosquitto

# macOS
brew services restart mosquitto
```

> On a machine already used by this stack, just re-enable the service:
> `sudo systemctl enable --now mosquitto`.

### 3. Update the broker IP in the app

Find your laptop's LAN IP address:

```bash
# Linux / macOS
ip addr show   # or: ifconfig | grep "inet "

# Windows
ipconfig       # look for IPv4 Address
```

Set the broker IP in `app/.env.development` (gitignored — copy
`app/.env.example` to create it):

```bash
# app/.env.development
EXPO_PUBLIC_BROKER_IP=192.168.x.x
```

Expo inlines `EXPO_PUBLIC_*` variables at bundle time, so **restart
`npx expo start`** after changing it. The app falls back to a built-in
default if the variable is missing.

### 4. Verify the broker is routing messages

```bash
# Terminal 1 — subscribe to all sleep topics
mosquitto_sub -h <YOUR_IP> -p 1883 -t "sleep/#" -v

# Terminal 2 — publish a test message
mosquitto_pub -h <YOUR_IP> -p 1883 -t "sleep/normal" \
  -m '{"tier":"Normal","spo2":97,"heartRate":62,"hrv":40,"motion":0,"timestamp":"01:00 AM","reason":"","stats":{"critical":0,"important":0,"normal":1,"background":0,"total":1},"qos":0,"topic":"sleep/normal"}'
```
