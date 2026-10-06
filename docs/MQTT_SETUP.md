# MQTT Setup Guide

This guide covers everything needed to run the full SleepMonitor data pipeline: Mosquitto broker, the React Native app, and the Python publisher.

---

## System Overview

```
Python Publisher  ──TCP:1883──►  Mosquitto  ──WS:9001──►  React Native App
(sleep_data.csv)                 (broker)                  (Expo / Paho JS)
```

The Python publisher connects to the broker over plain TCP (port 1883). The React Native app connects over WebSocket (port 9001) — required because the Expo/React Native JS runtime has no raw TCP socket API.

---

## 1. Mosquitto Installation

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install mosquitto mosquitto-clients
sudo systemctl enable mosquitto
```

### macOS

```bash
brew install mosquitto
brew services start mosquitto
```

### Windows

Download the installer from [mosquitto.org/download](https://mosquitto.org/download/). Add `C:\Program Files\mosquitto` to your PATH.

---

## 2. Mosquitto Configuration

The default config does not enable WebSockets. You must add a WebSocket listener.

### Linux

Create `/etc/mosquitto/conf.d/sleepmonitor.conf`:

```
# TCP listener — for Python publisher
listener 1883
allow_anonymous true

# WebSocket listener — for React Native / Paho JS
listener 9001
protocol websockets
allow_anonymous true
```

Restart:

```bash
sudo systemctl restart mosquitto
sudo systemctl status mosquitto   # confirm it's running
```

### macOS

Find the config file:

```bash
brew info mosquitto   # shows config path, usually /usr/local/etc/mosquitto/mosquitto.conf
```

Append to the config file (or create a new one in the `conf.d` directory if it exists):

```
listener 1883
allow_anonymous true

listener 9001
protocol websockets
allow_anonymous true
```

Restart:

```bash
brew services restart mosquitto
```

### Windows

Edit `C:\Program Files\mosquitto\mosquitto.conf` (or create a file next to the executable) and add the same listener blocks above. Restart the Mosquitto service from Services or run:

```
net stop mosquitto && net start mosquitto
```

---

## 3. Finding Your IP Address

The app must be told your laptop's LAN IP (not `localhost` — the phone needs to reach your laptop over Wi-Fi).

```bash
# Linux / macOS
ip addr show          # look for inet under your Wi-Fi adapter (e.g. wlan0)
# or
ifconfig | grep "inet "

# Windows
ipconfig              # look for IPv4 Address under your Wi-Fi adapter
```

Example output: `192.168.1.139`

---

## 4. Configuring the App

Edit `services/mqttService.js`:

```js
const BROKER_IP   = '192.168.1.139';  // ← your laptop's LAN IP
const BROKER_PORT = 9001;             // WebSocket port — do NOT use 1883 here
```

Your phone and laptop must be on the **same Wi-Fi network** (same subnet).

---

## 5. Verifying the Setup

Open two terminals:

**Terminal 1 — subscribe:**

```bash
mosquitto_sub -h 192.168.1.139 -p 1883 -t "sleep/#" -v
```

**Terminal 2 — publish a test message:**

```bash
mosquitto_pub -h 192.168.1.139 -p 1883 -t "sleep/normal" \
  -m '{
    "tier": "Normal",
    "spo2": 97,
    "heartRate": 62,
    "hrv": 40,
    "motion": 0,
    "timestamp": "01:00 AM",
    "reason": "",
    "qos": 0,
    "topic": "sleep/normal",
    "stats": {
      "critical": 0, "important": 0,
      "normal": 1, "background": 0, "total": 1
    }
  }'
```

Terminal 1 should print the topic and payload. If it does, the broker is working. Open the app — the HomeScreen should update.

---

## 6. MQTT Topics and QoS

| Topic | QoS | Delivery Guarantee | Use Case |
|---|---|---|---|
| `sleep/critical` | 2 | Exactly once (4-way handshake) | SpO2 < 90% — apnea suspected |
| `sleep/important` | 1 | At least once (PUBACK) | SpO2 90–94% — abnormal trend |
| `sleep/normal` | 0 | Best effort (fire and forget) | SpO2 ≥ 95% — routine readings |
| `sleep/background` | 0 | Best effort | Session statistics batch |

### QoS 2 — Exactly Once

The broker stores the message and completes a four-message handshake (PUBLISH → PUBREC → PUBREL → PUBCOMP) before delivery. No message is lost; no message is delivered twice. Used for life-critical apnea events where a missed alert is a patient safety failure.

### QoS 1 — At Least Once

The broker retransmits until it receives a PUBACK. The message is guaranteed to arrive but may be duplicated if the PUBACK is lost in transit. Duplicates in the event log are acceptable; missing an important trend is not.

### QoS 0 — Best Effort

The publisher sends once and moves on. No acknowledgement, no retransmission. Acceptable for high-frequency routine readings where the next sample arrives in seconds.

> **Subscribe QoS note:** The current app subscribes to all topics without specifying a QoS level, which defaults to QoS 0. This means the broker-to-app leg of `sleep/critical` messages is QoS 0 even though the publisher sends at QoS 2. To fix this, update `mqttService.js`:
>
> ```js
> client.subscribe('sleep/critical',   { qos: 2 });
> client.subscribe('sleep/important',  { qos: 1 });
> client.subscribe('sleep/normal',     { qos: 0 });
> client.subscribe('sleep/background', { qos: 0 });
> ```

---

## 7. Python Publisher — Example

Below is a minimal publisher that replays `sleep_data.csv` and classifies each row:

```python
import csv, time, json
import paho.mqtt.client as mqtt

BROKER  = '192.168.1.139'
PORT    = 1883

client = mqtt.Client()
client.connect(BROKER, PORT)

stats = {'critical': 0, 'important': 0, 'normal': 0, 'background': 0, 'total': 0}

with open('sleep_data.csv') as f:
    reader = csv.DictReader(f)
    for row in reader:
        spo2       = float(row['bo'])      # processed SpO2 column
        heart_rate = float(row['hr'])
        # hrv and motion can be derived from other columns as needed

        # Tier classification
        if spo2 < 90:
            tier, topic, qos = 'Critical',   'sleep/critical',   2
            reason = f'SpO2 below critical threshold ({spo2:.0f}%)'
        elif spo2 < 95:
            tier, topic, qos = 'Important',  'sleep/important',  1
            reason = f'SpO2 in borderline range ({spo2:.0f}%)'
        else:
            tier, topic, qos = 'Normal',     'sleep/normal',     0
            reason = ''

        stats[tier.lower()] += 1
        stats['total']       += 1

        payload = json.dumps({
            'tier':      tier,
            'spo2':      round(spo2, 1),
            'heartRate': round(heart_rate, 1),
            'hrv':       35,          # derive from data if available
            'motion':    0,
            'timestamp': time.strftime('%I:%M %p'),
            'reason':    reason,
            'qos':       qos,
            'topic':     topic,
            'stats':     stats.copy(),
        })

        client.publish(topic, payload, qos=qos)
        print(f'[{tier}] spo2={spo2:.1f}% → {topic} (QoS {qos})')
        time.sleep(2)   # simulate 2-second reading interval
```

---

## 8. Reconnection (Current Limitation)

The app currently does **not** reconnect after a dropout. `onConnectionLost` only logs the error. Until this is fixed, restart the app if the broker restarts or the network changes.

A minimal fix for `mqttService.js`:

```js
client.onConnectionLost = (response) => {
  console.log('MQTT connection lost:', response.errorMessage);
  // Simple fixed retry after 3 seconds
  setTimeout(() => connectMQTT(onMessage), 3000);
};
```

For production, use exponential backoff (1s → 2s → 4s → … up to 60s cap).

---

## 9. TLS / SSL (Not Configured)

The current setup uses unencrypted WebSocket (`useSSL: false`). This is acceptable on a local development LAN. For any real deployment, configure TLS:

1. Generate a certificate for your broker (self-signed for dev, CA-signed for prod).
2. Configure Mosquitto to use it on port 8883 (MQTTS) or 443 (WSS).
3. In `mqttService.js`: set `BROKER_PORT = 8883` and `useSSL: true`.
