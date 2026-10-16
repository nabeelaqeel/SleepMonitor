# Architecture

> **Path convention:** app source paths in this document are relative to `app/`
> (the Expo project root). Repository-level paths are written in full.

## App Bootstrapping

`index.js` calls `registerRootComponent(App)` which mounts `App.js` as the root.

On mount, `App` runs an async `useEffect` that calls `getStoredUser()` (reads `AsyncStorage`). During this check a splash screen is shown. Once resolved, the tree renders into one of three mutually exclusive branches:

```
App
 ├── [loading]  → Splash (MaterialCommunityIcons "sleep" + ActivityIndicator)
 ├── [!user]    → SafeAreaProvider > SleepProvider > LoginScreen
 ├── [doctor]   → SafeAreaProvider > SleepProvider > DoctorNavigator
 └── [patient]  → SafeAreaProvider > SleepProvider > PatientNavigator
```

`SleepProvider` wraps all post-login trees. It establishes the MQTT connection on mount and tears it down on unmount. Note that it also wraps `LoginScreen`, meaning the MQTT connection opens before the user logs in — a minor inefficiency.

---

## State Management

All live sensor data is held in `SleepContext` (`app/context/SleepContext.js`). No external state library is used.

### State shape

```js
currentData: {
  tier:        string,   // 'Critical' | 'Important' | 'Normal' | 'Background'
  spo2:        number,   // SpO2 percentage
  heartRate:   number,   // BPM
  hrv:         number,   // RMSSD in ms
  motion:      number,   // limb movement index
  timestamp:   string,   // e.g. '02:14 AM'
  lastUpdated: string,   // 'Just now' | 'Waiting...'
  reason:      string,   // classifier explanation
}

sessionStats: {
  critical: number, important: number,
  normal: number, background: number, total: number
}

spo2History:  number[]   // rolling last-10 SpO2 values (initialised to [97×10])

eventLog: Array<{
  id: string, tier: string, time: string,
  spo2: number, hr: number,
  duration: string,  // always '—' in Phase 1
  topic: string, reason: string
}>                        // newest-first, capped at 50 entries

networkStats: {
  connected: boolean,
  critical:   { count: number, delivery: number|null },
  important:  { count: number, delivery: number|null },
  normal:     { count: number, delivery: number|null },
  background: { count: number, delivery: number|null },
}

latencyStats: {
  0: { ms: number|null, samples: number },   // estimated latency (RTT/2), per QoS
  1: { ms: number|null, samples: number },
  2: { ms: number|null, samples: number },
}

patientSnapshots: {              // keyed by payload patientId (doctor roster)
  [patientId]: { tier, spo2, heartRate, topic, timestamp, lastSeen }
}
```

### Update flow (per MQTT message)

```
onMessage(topic, data)
  0. if topic === 'qos/pong'  → RTT/2 → window → median → latencyStats; return
  1. sleep/background is stats-only — skips steps 2–5 (live vital updates)
  2. setCurrentData(data fields)
  3. setSessionStats(data.stats)         — if present
  4. setSpo2History(prev → [...prev, data.spo2].slice(-10))
  5. setEventLog(...)                    — Critical and Important only; prepend; cap at 50
  6. setNetworkStats(...)               — count distinct seqs; delivery from data.stats delta
```

`sessionStats` is authoritative from the publisher (embedded in every payload) — the app never counts messages itself. `networkStats[tier].count` is the number of **distinct** `seq` values received since the app joined the session, and `delivery` is `count / (stats[tier] - baseline)` expressed as a percentage, where `baseline` is `stats[tier] - 1` at the first message for that tier. Recording the baseline at join means a late-joining app still reads near 100%, and resetting on `sessionId` change keeps the window aligned to one session.

### Estimated latency (RTT/2)

`mqttService.connectMQTT` exposes `publish()`, which the context uses to emit a `qos/ping` every second (cycling QoS 2 → 1 → 0). `python-publisher/echo.py`, running beside the broker, republishes each ping verbatim to `qos/pong`; the context times the round trip with the **monotonic** `performance.now()` clock and stores `RTT / 2` per QoS. Both timestamps originate on the phone, so phone↔laptop clock skew cancels.

- The per-QoS window holds up to 21 samples; samples older than 15 s are dropped, and the displayed value is the **window median** (rounded to 2 dp, so sub-millisecond values are shown).
- If the window is empty (echo responder stopped), the readout is `—`.
- These numbers are an **on-device indicator only**; the authoritative latency measurements come from the single-clock benchmark.

### useSleep() hook

```js
export function useSleep() {
  return useContext(SleepContext);
}
```

Every context consumer re-renders on every MQTT message. At the current scale (one patient device) this is acceptable.

---

## MQTT Connection

**File:** `app/services/mqttService.js` (Paho WebSocket client, port 9001)

| Aspect | Behaviour |
|---|---|
| Client ID | Random per install, persisted in `AsyncStorage` (`mqtt_client_id`) so the session is stable across restarts and two installs don't collide |
| Session | `cleanSession: false` (explicit) — with Mosquitto `persistence true`, QoS 1/2 messages queued while the app is offline are delivered on reconnect |
| Subscribe | `sleep/#` at QoS 2 and `qos/pong` at QoS 2 (single wildcard; effective QoS = min(publish QoS, 2)) |
| Publish | `publish(topic, payload, qos)` — used for latency probes; no-op when disconnected |
| Reconnect | `onConnectionLost` sets `connected = false` and retries with exponential backoff (1 s → 10 s cap) |

> **Note:** the broker host comes from `EXPO_PUBLIC_BROKER_IP` in `app/.env.development` (template: `app/.env.example`). Expo inlines it at bundle time, so restart Metro after changing it. Only one app instance per browser profile should run, since browser tabs share the persisted client ID.

---

## Authentication

**File:** `app/auth/mockAuth.js`

Entirely client-side — no backend.

| Function | Behaviour |
|---|---|
| `login(email, password)` | Synchronous `Array.find` against `MOCK_USERS`. Returns sanitised user (no password field) or `null`. |
| `storeUser(user)` | `AsyncStorage.setItem('current_user', JSON.stringify(user))` |
| `getStoredUser()` | `AsyncStorage.getItem` → `JSON.parse`. Returns `null` on missing or corrupted data. |
| `logout()` | `AsyncStorage.removeItem('current_user')` |

### Mock credentials

| Email | Password | Role |
|---|---|---|
| `doctor@sleep.com` | `1234` | doctor |
| `patient@sleep.com` | `1234` | patient |

---

## Navigation

### PatientNavigator (inline in `App.js`)

Bottom tab navigator (`@react-navigation/bottom-tabs`). Each tab is a flat screen — no nested stack.

| Tab | Screen | Icon |
|---|---|---|
| Home | `HomeScreen` | `home` |
| Alerts | `AlertsScreen` | `bell-alert` |
| Report | `ReportScreen` | `chart-bar` |
| Network | `NetworkScreen` | `wifi` |

Logout button injected via `screenOptions.headerRight` — visible on all tabs.

### DoctorNavigator (`app/navigation/DoctorNavigator.js`)

Native stack navigator (`@react-navigation/native-stack`).

```
PatientList  →  PatientDetail
  (title: "Doctor Dashboard")     (title: patient.name)
```

`PatientListScreen` calls `navigation.navigate('PatientDetail', { patient: item })` — the full patient object is passed as a route param.

Both navigators have their own `NavigationContainer` and mount exclusively (never simultaneously), so there is no nested container issue.

---

## Screens

### HomeScreen
- **Reads:** `currentData`, `spo2History`
- **Key UI:** Tier status card, vitals grid (4× VitalCard), SpO2 sparkline (inline `SparkLine` component), critical alert box (conditional), MQTT topic footer
- **Colour logic:** SpO2 < 90 → red; < 95 → amber; else green. HR outside 40–100 → red. HRV < 20 → amber.

### AlertsScreen
- **Reads:** `eventLog`, `sessionStats`
- **Local state:** `filter` — `'All' | 'Critical' | 'Important'`
- **Key UI:** Pill filter buttons, `FlatList` of event cards. Empty state distinguishes "no data yet" from "no matches for filter". Only Critical and Important events appear (context filters Normal/Background at ingestion).

### ReportScreen
- **Reads:** `sessionStats`, `currentData`
- **Key UI:** 3×2 summary card grid, per-tier bar rows (TierBar), stacked proportional bar, QoS transmission table. Percentage guard: `total` defaults to 1 to avoid division by zero.

### NetworkScreen
- **Reads:** `networkStats`, `sessionStats`, `latencyStats`
- **Key UI:** Broker card (address hardcoded as `localhost:1883` — see Limitations), per-topic delivery bars (TopicCard), QoS comparison table, "Why QoS matters" explanation panel.
- **Note:** Delivery is measured from distinct `seq` vs the publisher's `stats` delta; latency is the estimated `RTT/2` from the ping/echo probe. Both are labelled as estimates — authoritative latency figures come from the single-clock benchmark.

### LoginScreen
- **Reads:** nothing from context
- **Local state:** `email`, `password`, `error`, `loading`, `showPass`
- **Flow:** 500 ms artificial delay → synchronous `login()` → `storeUser()` → `onLoginSuccess(user)` callback to App.

### PatientListScreen (doctor)
- **Reads:** `patientSnapshots` + `sessionStats` (live overlay); the roster itself is the hardcoded `MOCK_PATIENTS` array
- **Live rule:** a roster entry whose `patientId` matches incoming payloads shows a LIVE badge and live values while messages keep arriving (10 s window, `PATIENT_LIVE_WINDOW_MS`); once a session has been observed the card also shows a "last seen" time
- **Navigation:** Taps a card → `navigation.navigate('PatientDetail', { patient })`

### PatientDetailScreen (doctor)
- **Reads:** `route.params.patient` + the same `patientSnapshots` overlay
- **Live overlay:** when the route patient is streaming, vitals, tier (from the payload), critical count and the last message topic come from the live snapshot; otherwise the seeded record is shown
- **Tier:** payload tier when live, `deriveTier(spo2)` for seeded records

---

## Components

### VitalCard

```
Props:
  label  string   — small label, e.g. "SpO2"
  value  string   — large value, e.g. "97%"
  color  string   — value text colour (default: '#ffffff')
```

Width: `47%` — designed for a 2-column `flexWrap: 'wrap'` grid with `gap: 10`. Used in HomeScreen (live readings) and PatientDetailScreen (live or seeded readings).

---

## Colour System

All colours are inline — no shared theme file. The canonical palette:

| Purpose | Hex |
|---|---|
| App background | `#0a0a0f` |
| Card background | `#13131f` |
| Card border | `#1e1e30` |
| Primary accent (indigo) | `#818cf8` |
| Critical (red) | `#ef4444` / `#f87171` |
| Important (amber) | `#f59e0b` / `#fbbf24` |
| Normal (green) | `#22c55e` / `#4ade80` |
| Background tier (grey) | `#6b7280` / `#9ca3af` |

The same `TIER_CONFIG` / `TIER_STYLE` object is duplicated in `HomeScreen`, `AlertsScreen`, and `PatientDetailScreen` — there is no shared constants file.
