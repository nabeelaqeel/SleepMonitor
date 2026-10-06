# Architecture

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

All live sensor data is held in `SleepContext` (`context/SleepContext.js`). No external state library is used.

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
  critical:   { count: number, latency: number },
  important:  { count: number, latency: number },
  normal:     { count: number, latency: number },
  background: { count: number, latency: number },
}
```

### Update flow (per MQTT message)

```
onMessage(topic, data)
  1. setCurrentData(data fields)
  2. setSessionStats(data.stats)         — if present
  3. setSpo2History(prev → [...prev, data.spo2].slice(-10))
  4. setEventLog(...)                    — Critical and Important only; prepend; cap at 50
  5. setNetworkStats(...)               — increment count; set latency from data.qos
```

`sessionStats` is authoritative from the publisher (embedded in every payload) — the app never counts messages itself. `networkStats.*.count` is locally incremented by the subscriber.

### useSleep() hook

```js
export function useSleep() {
  return useContext(SleepContext);
}
```

Every context consumer re-renders on every MQTT message. At the current scale (one patient device) this is acceptable.

---

## Authentication

**File:** `auth/mockAuth.js`

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

### DoctorNavigator (`navigation/DoctorNavigator.js`)

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
- **Reads:** `networkStats`, `sessionStats`
- **Key UI:** Broker card (address hardcoded as `localhost:1883` — see Limitations), per-topic delivery bars (TopicCard), QoS comparison table, "Why QoS matters" explanation panel.
- **Note:** Latency and delivery rates are static display values, not measured at runtime.

### LoginScreen
- **Reads:** nothing from context
- **Local state:** `email`, `password`, `error`, `loading`, `showPass`
- **Flow:** 500 ms artificial delay → synchronous `login()` → `storeUser()` → `onLoginSuccess(user)` callback to App.

### PatientListScreen (doctor)
- **Reads:** nothing from context; uses hardcoded `MOCK_PATIENTS` array
- **Navigation:** Taps a card → `navigation.navigate('PatientDetail', { patient })`

### PatientDetailScreen (doctor)
- **Reads:** `route.params.patient` (static mock data)
- **Tier derived locally:** `deriveTier(spo2)` — independent of SleepContext
- **Phase 2 note:** The displayed MQTT topic `sleep/patient/{id}` is not currently subscribed to anywhere.

---

## Components

### VitalCard

```
Props:
  label  string   — small label, e.g. "SpO2"
  value  string   — large value, e.g. "97%"
  color  string   — value text colour (default: '#ffffff')
```

Width: `47%` — designed for a 2-column `flexWrap: 'wrap'` grid with `gap: 10`. Used in HomeScreen (live readings) and PatientDetailScreen (static readings).

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
