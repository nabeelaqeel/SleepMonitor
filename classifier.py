import pandas as pd
import paho.mqtt.client as mqtt
import time
import json
import sys

# ─────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────

BROKER      = "localhost"
PORT        = 1883
CSV_FILE    = "sleep_data_realistic.csv"
DELAY       = 1.0          # seconds between each reading (simulate live sensor)

# ── Map these to your actual CSV column names ─────────────
# Run this first to find your columns:
# python -c "import pandas as pd; df = pd.read_csv('sleep_data.csv'); print(df.columns.tolist())"

SPO2_COL   = "bo"         # blood oxygen / SpO2
HR_COL     = "hr"         # heart rate
HRV_COL    = "rr"         # HRV or respiration rate
MOTION_COL = None         # set to column name if you have motion data, else None

# ─────────────────────────────────────────────────────────
#  QoS CLASSIFICATION ENGINE
#  Based on clinical thresholds from published literature
# ─────────────────────────────────────────────────────────

def classify(spo2, heart_rate, hrv):
    """
    Rule-based QoS classifier.

    Tier definitions:
    - CRITICAL   : SpO2 < 90%  OR  HR < 40  OR  HR > 100
                   → Suspected apnea / oxygen desaturation
                   → MQTT QoS 2 (guaranteed exactly-once delivery)

    - IMPORTANT  : SpO2 90-94%  OR  HR 40-50 / 90-100  OR  HRV < 20ms
                   → Abnormal physiological trend
                   → MQTT QoS 1 (at least once delivery)

    - NORMAL     : SpO2 95-99%, HR 50-90, HRV stable
                   → Routine sleep data
                   → MQTT QoS 0 (best effort, buffered)

    - BACKGROUND : All other readings (motion, stats)
                   → Aggregated statistics
                   → MQTT QoS 0 (batch upload)

    Clinical references:
    - Wang et al. (2022) Nat. Sci. Sleep — SpO2 < 90% threshold
    - Xu et al. (2023) PMC10250969 — T90% diagnostic marker
    - Tran et al. (2023) Medicina MDPI — HRV and OSA correlation
    """

    # ── CRITICAL tier ─────────────────────────────────────
    if spo2 < 90:
        return "Critical", 2, "SpO2 below 90% — apnea suspected"

    if heart_rate < 40:
        return "Critical", 2, "HR below 40 bpm — severe bradycardia"

    if heart_rate > 100:
        return "Critical", 2, "HR above 100 bpm — nocturnal tachycardia"

    # ── IMPORTANT tier ────────────────────────────────────
    if 90 <= spo2 < 95:
        return "Important", 1, "SpO2 90-94% — monitoring zone"

    if heart_rate < 50 or heart_rate > 90:
        return "Important", 1, "HR outside normal sleep range"

    if hrv < 20:
        return "Important", 1, "HRV low — possible autonomic stress"

    # ── NORMAL tier ───────────────────────────────────────
    if spo2 >= 95 and 50 <= heart_rate <= 90:
        return "Normal", 0, "Routine sleep reading"

    # ── BACKGROUND tier ───────────────────────────────────
    return "Background", 0, "Background statistics"


# ─────────────────────────────────────────────────────────
#  MQTT SETUP
# ─────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✓ Connected to MQTT broker at localhost:1883")
    else:
        print(f"✗ Connection failed with code {rc}")
        sys.exit(1)

client = mqtt.Client()
client.on_connect = on_connect
client.connect(BROKER, PORT)
client.loop_start()
time.sleep(1)  # wait for connection

# ─────────────────────────────────────────────────────────
#  TOPIC MAP
# ─────────────────────────────────────────────────────────

TOPICS = {
    "Critical":   "sleep/critical",
    "Important":  "sleep/important",
    "Normal":     "sleep/normal",
    "Background": "sleep/background",
}

# Tier colours for terminal output
TIER_COLORS = {
    "Critical":   "\033[91m",   # red
    "Important":  "\033[93m",   # yellow
    "Normal":     "\033[92m",   # green
    "Background": "\033[90m",   # gray
}
RESET = "\033[0m"

# ─────────────────────────────────────────────────────────
#  LOAD DATASET
# ─────────────────────────────────────────────────────────

print(f"\nLoading dataset: {CSV_FILE}")
try:
    df = pd.read_csv(CSV_FILE)
except FileNotFoundError:
    print(f"✗ File not found: {CSV_FILE}")
    print("  Make sure sleep_data.csv is in the same folder as classifier.py")
    sys.exit(1)

print(f"✓ Loaded {len(df)} rows")
print(f"  Columns: {list(df.columns)}\n")

# ─────────────────────────────────────────────────────────
#  SESSION STATISTICS TRACKER
# ─────────────────────────────────────────────────────────

stats = {
    "Critical":   0,
    "Important":  0,
    "Normal":     0,
    "Background": 0,
    "total":      0,
}

# ─────────────────────────────────────────────────────────
#  REPLAY LOOP — main engine
# ─────────────────────────────────────────────────────────

print("Starting data replay — press Ctrl+C to stop\n")
print(f"{'Row':<6} {'SpO2':>6} {'HR':>6} {'HRV':>6}  {'Tier':<12} {'Reason'}")
print("─" * 70)

try:
    for index, row in df.iterrows():

        # ── Extract values ─────────────────────────────
        try:
            spo2       = float(row[SPO2_COL])
            heart_rate = float(row[HR_COL])
            hrv        = float(row[HRV_COL])
            motion     = float(row[MOTION_COL]) if MOTION_COL else 0.0
        except (KeyError, ValueError) as e:
            print(f"Row {index} skipped — {e}")
            continue

        # ── Classify ───────────────────────────────────
        tier, qos, reason = classify(spo2, heart_rate, hrv)
        topic             = TOPICS[tier]
        color             = TIER_COLORS[tier]

        # ── Build payload ──────────────────────────────
        payload = json.dumps({
            "index":      int(index),
            "spo2":       round(spo2, 1),
            "heartRate":  round(heart_rate, 1),
            "hrv":        round(hrv, 1),
            "motion":     round(motion, 1),
            "tier":       tier,
            "topic":      topic,
            "qos":        qos,
            "reason":     reason,
            "timestamp":  time.strftime("%I:%M %p"),
            "stats": {
                "critical":   stats["Critical"],
                "important":  stats["Important"],
                "normal":     stats["Normal"],
                "background": stats["Background"],
                "total":      stats["total"],
            }
        })

        # ── Publish to MQTT ────────────────────────────
        result = client.publish(topic, payload=payload, qos=qos)

        # ── Update stats ───────────────────────────────
        stats[tier]    += 1
        stats["total"] += 1

        # ── Terminal output ────────────────────────────
        print(
            f"{color}"
            f"{index:<6} "
            f"SpO2={spo2:5.1f}% "
            f"HR={heart_rate:5.1f} "
            f"HRV={hrv:5.1f}  "
            f"{tier:<12} "
            f"{reason}"
            f"{RESET}"
        )

        time.sleep(DELAY)

except KeyboardInterrupt:
    print("\n\nStopped by user.")

finally:
    # ── Print session summary ──────────────────────────
    print("\n" + "─" * 70)
    print("SESSION SUMMARY")
    print("─" * 70)
    print(f"  Total readings  : {stats['total']}")
    print(f"  Critical events : {stats['Critical']}")
    print(f"  Important events: {stats['Important']}")
    print(f"  Normal readings : {stats['Normal']}")
    print(f"  Background      : {stats['Background']}")
    if stats['total'] > 0:
        pct = round((stats['Critical'] / stats['total']) * 100, 1)
        print(f"  Critical rate   : {pct}%")
    print("─" * 70)
    client.loop_stop()
    client.disconnect()
    print("Disconnected from MQTT broker.")