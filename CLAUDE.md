# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Start development server (Expo Go / browser)
npx expo start

# Run on Android
npx expo run:android

# Run on iOS
npx expo run:ios

# Run on web
npx expo start --web
```

No linter, formatter, or test suite is configured in this project.

## Architecture Overview

This is an **Expo React Native** app for real-time QoS-aware sleep monitoring. It uses **MQTT** to receive classified physiological data from an external publisher (e.g. a laptop running a Python classifier on `sleep_data.csv`).

### Data flow

```
External MQTT publisher (Python classifier)
  → Mosquitto broker (localhost:1883, WebSocket on 9001)
    → mqttService.js (Paho WebSocket client)
      → SleepContext.js (global state via React Context)
        → All screens via useSleep() hook
```

### MQTT topics and QoS levels

| Topic              | QoS | Purpose                          |
|--------------------|-----|----------------------------------|
| `sleep/critical`   | 2   | Apnea suspected — guaranteed delivery |
| `sleep/important`  | 1   | Abnormal trend — at least once   |
| `sleep/normal`     | 0   | Routine sleep — best effort      |
| `sleep/background` | 0   | Session statistics — batch       |

### Key files

- **`services/mqttService.js`** — Paho MQTT WebSocket client. `BROKER_IP` (line 8) must be changed to the local machine's IP address before use. Port 9001 is the WebSocket port; the broker runs on 1883.
- **`context/SleepContext.js`** — Single source of truth. Connects to MQTT on mount, populates `currentData`, `sessionStats`, `spo2History`, `eventLog`, and `networkStats`. All screens consume this via `useSleep()`.
- **`auth/mockAuth.js`** — Hardcoded credentials (`doctor@sleep.com / 1234`, `patient@sleep.com / 1234`). Session persisted with `AsyncStorage`.
- **`App.js`** — Root component. Checks persisted session on launch, then renders `LoginScreen`, `DoctorNavigator` (doctor role), or `PatientNavigator` (patient role) accordingly.

### Navigation structure

- **Patient role** — `PatientNavigator` in `App.js`: bottom-tab navigator with Home, Alerts, Report, Network tabs.
- **Doctor role** — `navigation/DoctorNavigator.js`: native stack with PatientList → PatientDetail.

### Screens

| Screen | Role | Description |
|---|---|---|
| `HomeScreen` | Patient | Live vitals (SpO2, HR, HRV, motion), SpO2 sparkline, tier status card |
| `AlertsScreen` | Patient | Filterable event log (Critical / Important only) |
| `ReportScreen` | Patient | Session statistics, tier distribution bars, QoS transmission summary |
| `NetworkScreen` | Patient | MQTT broker status, per-topic delivery rates, QoS comparison |
| `PatientListScreen` | Doctor | Mock patient list with status badges and vitals |
| `PatientDetailScreen` | Doctor | Individual patient vitals derived from static mock data |

### Tier classification (color coding)

Tier colours are defined per-screen (not centrally). The canonical mapping:

| Tier | Colour | Meaning |
|---|---|---|
| Critical | `#f87171` (red) | SpO2 < 90% |
| Important | `#fbbf24` (amber) | SpO2 90–94% |
| Normal | `#4ade80` (green) | SpO2 ≥ 95% |
| Background | `#9ca3af` (gray) | Stats only |

### Components

- **`VitalCard`** — Reusable 47%-width card displaying a label and a coloured value. Used in HomeScreen and PatientDetailScreen.

### Doctor patient data

`PatientListScreen` and `PatientDetailScreen` use hardcoded `MOCK_PATIENTS` array — they are **not** connected to the live MQTT stream. Live data integration is noted as Phase 2.
