# Demo Setup — Baked Accounts, Live Data Flow & Demo-Day Runbook

How the evaluation demo works end to end: the two baked accounts, the CSV →
MQTT → Postgres → app data path, which account sees what on screen, and the
one-server runbook for demo day. Audience: the project owner presenting, and
evaluators reading the repo.

**Last updated:** 2026-11-19
**Branch:** `feature/login`

> **Cross-references:** database/ingest internals live in
> [`DATABASE.md`](DATABASE.md), login + seeded accounts in
> [`AUTH_API.md`](AUTH_API.md), the MQTT payload schema in
> [`DATA_MODEL.md`](DATA_MODEL.md), topics/latency probe in
> [`MQTT_SETUP.md`](MQTT_SETUP.md), and the server operations runbook in
> [`notes/deployment/WORKFLOW.md`](../notes/deployment/WORKFLOW.md). This page
> only documents what those do not: the demo wiring itself.

---

## 1. The one-sentence model

> **`patient@sleep.com` gets the live data from the CSV file**: a seeded
> generator produces the night, the publisher streams it over MQTT, the ingest
> worker persists it, and the app's patient account sees exactly that stream —
> because the server env aims the stream at the demo patient's fixed UUID.

Everything below verifies that sentence piece by piece.

---

## 2. Baked demo accounts

Two accounts are seeded at API startup. They live in `users` only — no client
code contains credentials (`docs/AUTH_API.md`, "Seeded accounts" table).

| Email | Password | Role | `user_id` | Extra |
|---|---|---|---|---|
| `doctor@sleep.com` | `1234` | doctor | `00000000-0000-0000-0000-000000000001` | — |
| `patient@sleep.com` | `1234` | patient | `00000000-0000-0000-0000-000000000002` | Physical profile (below) |

- Definition: `api/db.py:29-53` (`SEED_USERS`). The patient entry carries the
  demo-day profile — `age 34`, `weight_kg 78.0`, `height_cm 175.0`,
  `medical_history "Mild obstructive sleep apnea (AHI 14), diagnosed 2024"`
  (`api/db.py:46-51`) — so the doctor's detail screen shows real Age / Weight /
  Height / History instead of `—` (`app/screens/doctor/PatientDetailScreen.js:295-307`).
- Seeding runs in `ensure_setup` (`api/db.py:72-77`), gated by
  `DEMO_SEEDING_ENABLED` — `SEED_DEMO_USERS` env, default `true`
  (`api/config.py:44-46`); the gate is the `for user in SEED_USERS if
  DEMO_SEEDING_ENABLED else []` line (`api/db.py:110`).
- **The fixed UUIDs are deliberate.** `…0002` is the value the server
  environment uses to aim the stream at the demo patient (§4, §6) and what the
  ingest worker falls back to for unbound devices (`ingest/worker.py:75`).
- Regression-tested: `tests/test_api_register.py:116`
  (`test_seeded_accounts_still_login`), roster-profile surfacing in
  `tests/test_api_patients.py:273` (`test_seeded_patient_profile_reaches_roster`).

Verification (needs the stack up):

```bash
.venv-dev/bin/python -m pytest tests/test_api_register.py tests/test_api_patients.py -q
curl -s http://<SERVER_IP>:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"patient@sleep.com","password":"1234"}' | head -c 200
```

---

## 3. Live data flow (CSV → MQTT → Postgres → API → app)

| Step | File | Fact (cited) |
|---|---|---|
| 1. Generate | `data/generate_data.py:5-8` | `random.seed(42)` / `np.random.seed(42)`, `TOTAL_MINUTES = 480` — one seeded 8-hour synthetic night |
| 2. Dataset | `data/generate_data.py:61` | Writes `data/sleep_data_realistic.csv` — **526 data rows** (527 lines incl. header), sha256 `b247f4b8…` |
| 3. Publish | `publisher/publisher.py:46-52` | Replays `CSV_PATH` at `PUBLISH_INTERVAL` s, `LOOP_CSV=true` loops; payload identity from env: `patientId = PATIENT_ID` (:104-105, :218-219), `deviceId = DEVICE_ID` (default `sleepband-001`) |
| 4. Tier/QoS | `publisher/tier_rules.py:42` | `TIER_QOS = {"Critical": 2, "Important": 1, "Normal": 0, "Background": 0}`; thresholds :28-37, `classify()` :45 |
| 5. Topics | `publisher/publisher.py:215` | `sleep/<tier>` (+ `session/start|end`); stats to `sleep/background` (:240-241). Latency probe: app → `qos/ping`, `publisher/echo.py:47-48` → `qos/pong` |
| 6. Ingest | `ingest/worker.py:99-101` | Subscribes `sleep/#` (QoS 2) + `session/#` (QoS 1); idempotent on `(session_id, seq)` (:17); drops seq-less stats (:144-146); measures QoS-0 loss at session end as `missing = expected − received` (`ingest/db.py:134-…`, `docs/DATABASE.md:304`) |
| 7. Postgres | `postgres/init/01_schema.sql:73,96` | `readings` and `alerts` (Critical/Important only, `UNIQUE (session_id, seq)`); alert bulk-insert `ingest/db.py:110-118` |
| 8. API | `api/main.py` | FastAPI surfaces: `GET /patients` roster (:312), `GET /alerts` (:324-337), auth endpoints |
| 9. App | `app/App.js:157-168` | `<SleepProvider>` mounts per role: doctor (no `patientId`), patient (`patientId={user.patientId \|\| user.id}` :166) |

Dataset verification (exact):

```bash
wc -l data/sleep_data_realistic.csv        # 527 = 1 header + 526 rows
sha256sum data/sleep_data_realistic.csv    # b247f4b8953e46e4899d70ae94b22389b86e292ecd85e9c55143d78dfa555390
```

> Regenerating the CSV changes the hash (the seed only fixes *content* given
> the same code); re-run `data/generate_data.py` only if you accept that.

---

## 4. Who sees what — the attribution rule

Implemented in `app/context/SleepContext.js` this session:

- **Patient mode:** the provider receives the logged-in account id
  (`app/App.js:166` → `SleepContext.js:40`), holds it in `patientIdRef`
  (:104-105), and gates personal live data on
  `data.patientId === account` (:206-207, comment :203-205). Consequence:
  **only `patient@sleep.com` sees live readings** — and only once the
  publisher's env `PATIENT_ID` equals `…0002` (§6). Any other patient account
  (e.g. a fresh Google sign-in) keeps the neutral placeholder: HomeScreen
  treats the `lastUpdated === 'Waiting...'` sentinel as "no data"
  (`app/screens/HomeScreen.js:37-39`, rendered :66).
- **Doctor mode:** `patientId` is `null` (`app/App.js:157-160`), so the whole
  stream is ingested ungated (:206-207). The roster joins live traffic through
  **bound devices**, not patientId: `GET /patients` rows carry `devices[]`
  (`app/screens/doctor/rosterLive.js:11-32`; endpoint `api/main.py:312`), and
  `pickLiveDevice` marks a patient LIVE when any bound device has a snapshot
  fresher than the live window (`rosterLive.js:35-47`, window
  `PATIENT_LIVE_WINDOW_MS` at `SleepContext.js:19`). The roster therefore shows
  whichever account has `sleepband-001` bound as "the streamer".
- **Binding:** the demo patient binds the device in-app
  (`app/screens/DeviceScreen.js:96` → `POST /devices/bind`, `api/main.py:285-300`).
  The registry row is what Postgres attribution uses: the ingest worker
  resolves each session's patient via `deviceId` (`ingest/worker.py:221-241`,
  `ingest/db.py:62-70`), falling back to `PATIENT_UUID` (env, default `…0002`,
  `ingest/worker.py:75`) when the device is unbound — so an unbound demo still
  attributes to Ali Hassan, with a once-per-device warning.
- **Rebind semantics (stated plainly):** `POST /devices/bind` **refuses** to
  rebind a device that belongs to a different patient — HTTP 409
  (`api/main.py:299-300`, `api/db.py:296-307`, "no hijacking"). Same-patient
  rebind only refreshes `display_name` (`api/db.py:298`). So the demo's
  single-device attribution is stable by design: moving `sleepband-001` to
  another account is a database intervention, not an app action. The demo is
  single-stream; per-account data ownership in Postgres follows the registry,
  while what an app account sees *live* follows the payload `patientId`.

---

## 5. Alerts lifecycle

| Stage | Where | Behaviour (cited) |
|---|---|---|
| Emitted | `publisher/tier_rules.py:55-83` | Critical/Important classification (SpO₂ < 90 / HR < 40 or > 100; SpO₂ 90–94, HR 40–50 or 90–100, HRV < 20) |
| Live in app | `app/context/SleepContext.js:239-255` | Critical/Important readings append to the patient/doctor `eventLog` (cap 50), stamped with `tsMs = data.publishedAt` for later dedupe |
| Persisted | `ingest/worker.py:168-171`, `ingest/db.py:110-118` | Same messages mirrored into `alerts` idempotently |
| History API | `api/main.py:324-337` | `GET /alerts`, doctor-role only (403 otherwise), `list_doctor_alerts` (`api/db.py:465-495`): `ts DESC LIMIT 50`, scoped by the `doctor_patients` join so unlinked patients never leak |
| Merged view | `app/screens/doctor/DoctorAlertsScreen.js:9,55` | `mergeAlerts(eventLog, history, roster)` (`app/screens/doctor/alertHistory.js`) — history rows deduped against live keys on `tier \| floor(ts/1000) \| spo2 \| hr` (`alertHistory.js:19-23`); live rows win (:53-56) |

Evaluator-visible result: an alert that fired during the stream appears once —
live as it happens, then as history after a screen refresh — not twice.

---

## 6. Server environment (`.env.development`)

Bootstrap renders it in TEST mode; an existing file is never overwritten
(`./deploy/bootstrap.sh --force` regenerates deliberately). The full variable
table lives in `docs/DATABASE.md` (§Environment); demo-critical entries:

| Variable | Value for demo day | Why (cited) |
|---|---|---|
| `PATIENT_ID` | `00000000-0000-0000-0000-000000000002` | Aims the publisher payload at the demo patient — the app's patient gate compares against this (`SleepContext.js:206-207`). ⚠ Template default is `patient-001` (`deploy/bootstrap.sh:166`); **change it to the UUID or the patient screen stays empty** |
| `PATIENT_UUID` | `00000000-0000-0000-0000-000000000002` | Ingest FK target / unbound-device fallback (`ingest/worker.py:75`; template `deploy/bootstrap.sh:167`; `docs/DATABASE.md:126`) |
| `DEVICE_ID` | `sleepband-001` | The single demo device id, publisher + worker (`deploy/bootstrap.sh:168`) |
| `AI_DEMO_PATIENT_ID` | `00000000-0000-0000-0000-000000000002` | AI demo band publisher targets the same account (`deploy/bootstrap.sh:173`, compose `docker-compose.aws.yml:145-151`); `--ai-demo` appends it if missing (`deploy/bootstrap.sh:84-106`) |
| `SEED_DEMO_USERS` | `true` (demo) / `false` (real deployments) | Seeding gate (`api/config.py:44-46`; template `deploy/bootstrap.sh:151`) |
| `GOOGLE_CLIENT_ID` | the Web OAuth client ID | Server-side verifier audience (`api/google_auth.py:112`); must **equal** the app's baked `EXPO_PUBLIC_GOOGLE_CLIENT_ID` (`app/.env.example:38-43`; baked via `deploy/build-apk.sh:271-282`, which refuses the placeholder). Unset = `/auth/google` answers 503, login stays email/password (`api/config.py:48-50`) |
| `MQTT_USER` / `MQTT_PASSWORD` | `sm` / generated | Shared by publisher + worker + echo (`publisher/publisher.py:44,94-95`) and baked into the app as `EXPO_PUBLIC_MQTT_*` (bootstrap print block, `deploy/bootstrap.sh:335-336`) |

Verify on the server after `up -d`:

```bash
docker exec sleep-publisher printenv PATIENT_ID     # 00000000-0000-0000-0000-000000000002
docker exec sleep-ingest    printenv PATIENT_UUID  # 00000000-0000-0000-0000-000000000002
docker exec sleep-publisher printenv DEVICE_ID      # sleepband-001
```

App-side values (broker IP, API URL, MQTT creds, Google client ID) are printed
by the bootstrap at the end — paste them into the build profile exactly as
`notes/deployment/WORKFLOW.md` §S7 describes.

---

## 7. Demo-day runbook

### 7.1 One-server start

```bash
./deploy/bootstrap.sh          # first boot, TEST mode (staging)
./deploy/deploy-update.sh      # update an existing stack (add --branch <NAME> on staging, --ai-demo for the AI service)
```

Step-by-step (ssh, ports, APK install): `notes/deployment/WORKFLOW.md`.
TEST mode keeps the database compose-local; DEMO/RDS mode is a production-only
flip of the active `DATABASE_URL` line (`docker-compose.aws.yml:6-15,28-33`).

### 7.2 Scripted walkthrough

| # | Action | Expected on screen | Backed by |
|---|---|---|---|
| 1 | Login `doctor@sleep.com` / `1234` | Patients tab | `api/main.py:312`, `PatientListScreen.js` |
| 2 | Watch the Patients tab | Ali Hassan's card shows the LIVE pill while streaming (values = live snapshot) | `LIVE_CONFIG` `app/screens/doctor/PatientListScreen.js:24-26`, `rosterLive.js:35-47` |
| 3 | Open Ali Hassan → detail | Vitals + Age/Weight/Height/BMI + history + live overlay; session report export | `PatientDetailScreen.js:80-102,295-307,149-161` |
| 4 | Alerts tab | Persisted history merged with live Critical/Important events, no duplicates | `DoctorAlertsScreen.js:55`, `alertHistory.js:19-23` |
| 5 | Logout → login `patient@sleep.com` / `1234` | Own live readings, timeline, stats | `app/App.js:166`, `SleepContext.js:206-207` |
| 6 | New account via Google | Zeros / `Waiting...` placeholder — by design (no stream is aimed at that account id) | `HomeScreen.js:37-39` |
| 7 | (Optional) `--ai-demo` stack | AI band card cycles healthy → monitor → apnea for the demo patient | `docker-compose.aws.yml:145-151`, `SleepContext.js:186,378-379` |

### 7.3 Watch the wire while presenting

```bash
mosquitto_sub -h <SERVER_IP> -p 1883 -t 'sleep/#' -u sm -P '<MQTT_PASSWORD>' -v
```

(Username is hardcoded `sm` — one passwd entry, rebuilt wholesale on
`--force`; `notes/deployment/WORKFLOW.md:153`.)

---

## 8. Limitations (state these on demo day if asked)

- **Single-stream demo.** One publisher container, one `DEVICE_ID`
  (`sleepband-001`). Parallel publishers with the same identity collide on
  client id and mis-attribute (`publisher/publisher.py:8-9`, startup warning
  :287-296). The registry binds one device to one patient, and cross-patient
  rebinds are refused (409, `api/db.py:296-307`) — moving the demo device is a
  database operation, not a feature.
- **Alert dedupe is second-resolution.** The live/persisted merge keys on
  publish-second, not on `seq` (`alertHistory.js:19-23`) because `GET /alerts`
  does not return `seq` (`api/db.py:476-487`). Exact dedupe would need `seq`
  exposed in the history payload — future work.
- **`patientSnapshots` has zero consumers.** Defined and exported in the
  context (`app/context/SleepContext.js:85,373`) but no screen reads it — the
  roster uses `deviceSnapshots` instead.
- **NetworkScreen broker label is a hardcoded display string** —
  `localhost:1883` (`app/screens/NetworkScreen.js:75-76`); it does not reflect
  the baked broker endpoint.
- **QoS-0 tail loss is invisible** when the publisher's `totalReadings` is
  absent (the `max(seq)+1` fallback cannot see a dropped trailing run); the
  publisher always sends it (`docs/DATABASE.md:379-380`).
- **The sensor is simulated.** Data comes from `data/generate_data.py` —
  no physical hardware is involved anywhere in this pipeline.

## 9. Full test sweep (pre-demo)

```bash
.venv-dev/bin/python -m pytest tests/ -q
```
