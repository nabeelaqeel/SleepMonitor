# Device Testing Checklist

Manual QA for the installed APK (current build: `app/builds/SleepMonitor-0.1.0-release-*`).
Everything the automated suite cannot reach lives here — UI behaviour, the
Android SAF pickers, Bluetooth gaps, broker Last-Will fallout, and 12-hour
token expiry (a 60-test DB-free pytest suite covers the server logic; see
`tests/`, `ai/tests/`, `benchmark/tests/`).

Goal: turn the rows still marked **Untested** / "on-device check pending" in
`docs/PROJECT_OVERVIEW.md` into **Working**.

---

## Prerequisites

1. **Stack up** — run the terminals from `docs/RUN_TERMINAL.md`:
   postgres → ingest worker → auth API → echo → publisher.
2. **Broker + API reachable** — phone and host on the same LAN. The app's
   addresses are `EXPO_PUBLIC_*` values baked into the APK at BUILD time
   from the gitignored `app/.env.development`: `EXPO_PUBLIC_BROKER_IP`
   (+ MQTT user/password) read in `app/services/mqttService.js`,
   `EXPO_PUBLIC_API_URL` in `app/auth/apiAuth.js` (unset keys fall back
   to hardcoded defaults in those files). Nothing on the phone or host
   retargets an installed build afterwards — before testing, verify the
   addresses baked into the current APK, or rebuild it with matching
   values (`deploy/build-apk.sh --env-file app/.env.development`).
3. **Demo data flowing** — publisher streaming `data/sleep_data_realistic.csv`
   (tier rules live in `publisher/tier_rules.py`, so the app's tier card
   should agree exactly with what the publisher computes).
4. **Demo credentials** (bcrypt-seeded in `api/db.py` `SEED_USERS`):
   `doctor@sleep.com` / `1234` and `patient@sleep.com` / `1234`.
5. **Optional AI demo** — `deploy/bootstrap.sh --ai-demo` (needs
   `AI_DEMO_PATIENT_ID`; see `ai/README.md`).

Mark each row ✅ / ❌ / n-a in the last column; log misses at the bottom.

---

## A. Install & launch

| # | Step | Expected | Result |
|---|------|----------|--------|
| A1 | Install the APK build | Installs, opens to the login screen | |
| A2 | Launch with **no API running** | Login fails with a reachable-network style error, app does not crash | |
| A3 | Grant Bluetooth/notification prompts on first launch | No phantom permission loops | |

## B. Auth

| # | Step | Expected | Result |
|---|------|----------|--------|
| B1 | Log in as `doctor@sleep.com` | Lands on the doctor roster | |
| B2 | Log in as `patient@sleep.com` | Lands on the patient home (live vitals) | |
| B3 | Wrong password | Rejected with the generic error; identical message for an email that does not exist (no user-enumeration leak) | |
| B4 | Force-quit and relaunch the app | Session persisted via AsyncStorage — no re-login within the 12 h JWT window | |
| B5 | Open the app >12 h after login (or clear the token) | Prompted to log in again | |

## C. Session & live vitals (patient)

| # | Step | Expected | Result |
|---|------|----------|--------|
| C1 | While the publisher streams, open Patient — Home | Live vitals cards update, SpO2 sparkline advances, tier card matches the publisher's tier | |
| C2 | Numbers plausibility | SpO2 within ~85–100%, HR 30–120, HRV tens of ms — no `NaN`, no frozen 35 ms HRV (the restored-HRV bug) | |
| C3 | Stop the publisher (session/end arrives) | Session view stops cleanly; nothing publishes after end | |
| C4 | Keep app open with publisher down | Backoff reconnect churn is quiet; no battery-melting reconnect loop visualised | |

## D. Network metrics (patient — Network tab)

| # | Step | Expected | Result |
|---|------|----------|--------|
| D1 | Open Network while streaming | Delivery % tracks `seq` vs publisher stats; latency shows the `RTT/2` estimate via `echo.py` | |
| D2 | Kill the echo responder briefly | Latency column degrades gracefully (no crash/NaN rendering) | |

## E. Alerts & recommendations

| # | Step | Expected | Result |
|---|------|----------|--------|
| E1 | Open Patient — Alerts while a Critical/Important reading crosses | Event appears with a human reason (e.g. "SpO2 critically low"), matching tier_rules wording | |
| E2 | Run the AI demo patient (`bootstrap.sh --ai-demo`) | A nightly recommendation renders on the demo patient without inventing one for the live patient | |

## F. Report & PDF export (patient — Report)

| # | Step | Expected | Result |
|---|------|----------|--------|
| F1 | Open Report for a session with data | Timeline chart renders; export sheet shows every row **frozen** while any export runs (re-entry guard) | |
| F2 | Share the PDF | `expo-sharing` hands off to Android sharesheet; the PDF opens in a viewer | |
| F3 | Save to device — first time | The one-time Downloads-folder grant opens; **on Android 11+ the picker may refuse the Downloads ROOT — select/create a subfolder inside it instead**; the grant works identically | |
| F4 | Save to device — second time | Saves silently into the granted folder (no picker), file appears in Files/Downloads | |
| F5 | Cancel mid-save (back out of the picker) | No success toast, no stray temp file left behind in the app's cache dir | |
| F6 | Pull the network cable mid-export (or kill the API) | Export failure surfaces an explicit alert to the user rather than a silent hang | |

## G. Doctor dashboards

| # | Step | Expected | Result |
|---|------|----------|--------|
| G1 | Patient list | Seeded roster renders with the live patient overlay | |
| G2 | Open the live patient detail | Live vitals + alerts for the streaming patient | |
| G3 | Doctor Alerts tab / session PDF export | Same export behaviour as the patient side (F1–F5) | |

## H. Resilience & lifecycle

| # | Step | Expected | Result |
|---|------|----------|--------|
| H1 | Kill the **publisher hard** (`kill -9`; a SIGTERM ends the session cleanly and no will is sent) mid-session, broker stays up | The broker publishes the publisher's Last Will — a `session/end` with reason "publisher disconnected unexpectedly" — and ingest/app reflect the aborted session instead of silently stalling. (Killing the *broker* for LWT delivery is a false test: the will is published BY the broker and nothing delivers during its outage — that scenario lives in H2) | |
| H2 | Restart the broker, then the publisher | QoS 1/2 messages queued while down are redelivered and ingested; `session_stats` recovery counts make sense | |
| H3 | Background the app for minutes, return | The persistent MQTT session (per-install client id, `cleanSession: false`) resumes without losing the stream | |
| H4 | Rotate screen / dark mode on every screen | No layout explosions | |

## I. Release-build sanity

| # | Step | Expected | Result |
|---|------|----------|--------|
| I1 | On the release APK: log in via LAN `http://<host>:8000` | Works — the release manifest deliberately allows cleartext to the LAN API | |
| I2 | Confirm no dev overlays/menus leak into the release UI | Only the production navigation graph | |
| I3 | `adb` uninstall + clean reinstall | Redux/AsyncStorage state fresh; first-run flow repeats cleanly | |

---

## Bug log

For each failure, one line: `build · step id · symptom · screenshot path`.
Batch them into a GitHub issue per milestone release; keep this file's
Results column as the running state, then update the matching rows in
`docs/PROJECT_OVERVIEW.md` when a defect ships fixed.
