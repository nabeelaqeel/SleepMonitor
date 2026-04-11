import pandas as pd
import paho.mqtt.client as mqtt
import time
import json

# ── MQTT setup ─────────────────────────────────────────
BROKER   = "localhost"
PORT     = 1883

client = mqtt.Client()
client.connect(BROKER, PORT)
client.loop_start()

print("Connected to MQTT broker")

# ── Classification rules ───────────────────────────────
def classify(spo2, heart_rate, hrv):
    """
    Rule-based QoS classifier based on clinical thresholds.
    Returns tier string and MQTT QoS level.
    """
    # CRITICAL — immediate danger
    if spo2 < 90:
        return "Critical", 2

    # IMPORTANT — abnormal trend
    if spo2 < 95 or heart_rate < 40 or heart_rate > 100 or hrv < 20:
        return "Important", 1

    # NORMAL — routine sleep
    if spo2 >= 95 and 40 <= heart_rate <= 100:
        return "Normal", 0

    # BACKGROUND — statistics only
    return "Background", 0


# ── Topic map ──────────────────────────────────────────
TOPICS = {
    "Critical":   "sleep/critical",
    "Important":  "sleep/important",
    "Normal":     "sleep/normal",
    "Background": "sleep/background",
}


# ── Load dataset ───────────────────────────────────────
print("Loading dataset...")
df = pd.read_csv("sleep_data.csv")
print(f"Loaded {len(df)} rows")
print(f"Columns: {list(df.columns)}")


# ── Map your dataset columns here ─────────────────────
# Check what your CSV columns are called and map them below.
# Common names: 'spo2', 'sr' (stress rate), 'rr' (respiration rate),
#               'hr' (heart rate), 'hrv', 'bo' (blood oxygen)

# CHANGE THESE to match your actual column names
SPO2_COL  = "bo"     # blood oxygen / SpO2 column
HR_COL    = "hr"     # heart rate column  
HRV_COL   = "rr"     # HRV or respiration rate column


# ── Replay loop ────────────────────────────────────────
print("\nStarting data replay... Press Ctrl+C to stop.\n")

for index, row in df.iterrows():

    try:
        spo2       = float(row[SPO2_COL])
        heart_rate = float(row[HR_COL])
        hrv        = float(row[HRV_COL])
    except (KeyError, ValueError):
        print(f"Row {index} skipped — missing values")
        continue

    tier, qos = classify(spo2, heart_rate, hrv)
    topic     = TOPICS[tier]

    # Build the message payload
    payload = json.dumps({
        "index":      index,
        "spo2":       round(spo2, 1),
        "heartRate":  round(heart_rate, 1),
        "hrv":        round(hrv, 1),
        "tier":       tier,
        "topic":      topic,
        "timestamp":  time.strftime("%I:%M %p"),
    })

    # Publish with appropriate QoS
    client.publish(topic, payload=payload, qos=qos)

    print(f"Row {index:4d} | SpO2={spo2:5.1f}% | HR={heart_rate:5.1f} | "
          f"Tier={tier:10s} | Topic={topic}")

    # 1 second delay — simulates live sensor sending one reading per second
    time.sleep(1)

print("\nDataset replay complete.")
client.loop_stop()
client.disconnect()