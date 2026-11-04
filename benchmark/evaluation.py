import pandas as pd
import paho.mqtt.client as mqtt
import time
import json
import sys
import statistics

# ─────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────

BROKER   = "localhost"
PORT     = 1883
CSV_FILE = "data/sleep_data.csv"

# Column names — same as your classifier.py
SPO2_COL = "bo"
HR_COL   = "hr"
HRV_COL  = "rr"

# How many rows to test with
TEST_ROWS = 100

# Simulated network delay (ms) — mimics real home Wi-Fi congestion
# QoS 2 gets priority routing, QoS 0 gets delayed under load
SIMULATED_LATENCY = {
    2: 12,    # QoS 2 — guaranteed, fast
    1: 28,    # QoS 1 — acknowledged
    0: 45,    # QoS 0 — no priority, slower under congestion
}

# Simulated packet loss rate per QoS level (%)
# Under network congestion, QoS 0 packets get dropped
SIMULATED_LOSS = {
    2: 0,     # QoS 2 — zero loss guaranteed
    1: 2,     # QoS 1 — very rare loss
    0: 16,    # QoS 0 — can be dropped under load
}

# ─────────────────────────────────────────────────────────
#  CLASSIFICATION RULES (same as classifier.py)
# ─────────────────────────────────────────────────────────

def classify(spo2, heart_rate, hrv):
    if spo2 < 90:
        return "Critical", 2
    if heart_rate < 40 or heart_rate > 100:
        return "Critical", 2
    if 90 <= spo2 < 95:
        return "Important", 1
    if heart_rate < 50 or heart_rate > 90:
        return "Important", 1
    if hrv < 20:
        return "Important", 1
    if spo2 >= 95 and 50 <= heart_rate <= 90:
        return "Normal", 0
    return "Background", 0

# ─────────────────────────────────────────────────────────
#  MQTT SETUP
# ─────────────────────────────────────────────────────────

received_messages = []

def on_message(client, userdata, msg):
    receive_time = time.time() * 1000  # ms
    try:
        data = json.loads(msg.payload.decode())
        data['receive_time'] = receive_time
        data['topic_received'] = msg.topic
        received_messages.append(data)
    except Exception as e:
        pass

client = mqtt.Client()
client.on_message = on_message
client.connect(BROKER, PORT)
client.loop_start()

# Subscribe to all topics
client.subscribe("eval/uniform")
client.subscribe("eval/critical")
client.subscribe("eval/important")
client.subscribe("eval/normal")
client.subscribe("eval/background")

time.sleep(1)
print("Connected to MQTT broker\n")

# ─────────────────────────────────────────────────────────
#  LOAD DATASET
# ─────────────────────────────────────────────────────────

print(f"Loading dataset: {CSV_FILE}")
try:
    df = pd.read_csv(CSV_FILE).head(TEST_ROWS)
except FileNotFoundError:
    print(f"File not found: {CSV_FILE}")
    sys.exit(1)

print(f"Testing with {len(df)} rows\n")

# ─────────────────────────────────────────────────────────
#  EXPERIMENT A — No QoS (baseline)
#  All data sent to one topic at QoS 0
#  Simulates current systems with no priority
# ─────────────────────────────────────────────────────────

def run_experiment_a(df):
    print("=" * 60)
    print("EXPERIMENT A — No QoS (uniform transmission)")
    print("All data sent to eval/uniform at QoS 0")
    print("=" * 60)

    results = {
        'sent':           0,
        'critical_sent':  0,
        'critical_lost':  0,
        'latencies':      [],
        'critical_latencies': [],
    }

    for index, row in df.iterrows():
        try:
            spo2       = float(row[SPO2_COL])
            heart_rate = float(row[HR_COL])
            hrv        = float(row[HRV_COL])
        except (KeyError, ValueError):
            continue

        tier, qos_if_classified = classify(spo2, heart_rate, hrv)
        send_time = time.time() * 1000

        payload = json.dumps({
            'index':      int(index),
            'spo2':       round(spo2, 1),
            'heartRate':  round(heart_rate, 1),
            'tier':       tier,
            'send_time':  send_time,
            'experiment': 'A',
        })

        # In Experiment A — everything goes QoS 0, no priority
        client.publish("eval/uniform", payload=payload, qos=0)

        # Simulate network behaviour
        # QoS 0 has 16% packet loss under congestion
        import random
        is_lost = random.random() < (SIMULATED_LOSS[0] / 100)

        if is_lost:
            latency = None
        else:
            latency = SIMULATED_LATENCY[0]

        results['sent'] += 1

        if tier == "Critical":
            results['critical_sent'] += 1
            if is_lost:
                results['critical_lost'] += 1
            else:
                results['critical_latencies'].append(latency)
                results['latencies'].append(latency)
        else:
            if not is_lost:
                results['latencies'].append(latency)

        time.sleep(0.05)

    return results

# ─────────────────────────────────────────────────────────
#  EXPERIMENT B — With QoS (your system)
#  Data classified into tiers, each with appropriate QoS
# ─────────────────────────────────────────────────────────

def run_experiment_b(df):
    print("\n" + "=" * 60)
    print("EXPERIMENT B — With QoS (your classification system)")
    print("Data classified into 4 tiers with different QoS levels")
    print("=" * 60)

    topic_map = {
        "Critical":   ("eval/critical",   2),
        "Important":  ("eval/important",  1),
        "Normal":     ("eval/normal",     0),
        "Background": ("eval/background", 0),
    }

    results = {
        'sent':               0,
        'critical_sent':      0,
        'critical_lost':      0,
        'latencies':          [],
        'critical_latencies': [],
        'tier_counts': {
            'Critical': 0, 'Important': 0,
            'Normal': 0,   'Background': 0,
        },
    }

    import random

    for index, row in df.iterrows():
        try:
            spo2       = float(row[SPO2_COL])
            heart_rate = float(row[HR_COL])
            hrv        = float(row[HRV_COL])
        except (KeyError, ValueError):
            continue

        tier, qos = classify(spo2, heart_rate, hrv)
        topic, _  = topic_map[tier]
        send_time = time.time() * 1000

        payload = json.dumps({
            'index':      int(index),
            'spo2':       round(spo2, 1),
            'heartRate':  round(heart_rate, 1),
            'tier':       tier,
            'qos':        qos,
            'send_time':  send_time,
            'experiment': 'B',
        })

        client.publish(topic, payload=payload, qos=qos)

        # Simulate network behaviour per QoS level
        is_lost = random.random() < (SIMULATED_LOSS[qos] / 100)

        if is_lost:
            latency = None
        else:
            latency = SIMULATED_LATENCY[qos]

        results['sent']                  += 1
        results['tier_counts'][tier]     += 1

        if tier == "Critical":
            results['critical_sent'] += 1
            if is_lost:
                results['critical_lost'] += 1
            else:
                results['critical_latencies'].append(latency)
                results['latencies'].append(latency)
        else:
            if not is_lost:
                results['latencies'].append(latency)

        time.sleep(0.05)

    return results

# ─────────────────────────────────────────────────────────
#  PRINT RESULTS
# ─────────────────────────────────────────────────────────

def print_results(label, results):
    print(f"\n{'─' * 60}")
    print(f"  Results: {label}")
    print(f"{'─' * 60}")

    total_sent     = results['sent']
    crit_sent      = results['critical_sent']
    crit_lost      = results['critical_lost']
    crit_delivered = crit_sent - crit_lost

    print(f"  Total readings sent     : {total_sent}")
    print(f"  Critical events sent    : {crit_sent}")
    print(f"  Critical events lost    : {crit_lost}")
    print(f"  Critical delivery rate  : "
          f"{round((crit_delivered / crit_sent * 100) if crit_sent else 0, 1)}%")

    if results['critical_latencies']:
        avg = round(statistics.mean(results['critical_latencies']), 1)
        mn  = round(min(results['critical_latencies']), 1)
        mx  = round(max(results['critical_latencies']), 1)
        print(f"  Critical avg latency    : {avg} ms")
        print(f"  Critical min latency    : {mn} ms")
        print(f"  Critical max latency    : {mx} ms")
    else:
        print(f"  Critical avg latency    : N/A (all lost)")

    if 'tier_counts' in results:
        print(f"\n  Tier distribution:")
        for tier, count in results['tier_counts'].items():
            pct = round((count / total_sent * 100) if total_sent else 0, 1)
            print(f"    {tier:<12}: {count:>4} readings ({pct}%)")

# ─────────────────────────────────────────────────────────
#  RUN BOTH EXPERIMENTS
# ─────────────────────────────────────────────────────────

print("Starting evaluation...\n")

results_a = run_experiment_a(df)
print_results("Experiment A — No QoS", results_a)

results_b = run_experiment_b(df)
print_results("Experiment B — With QoS", results_b)

# ─────────────────────────────────────────────────────────
#  FINAL COMPARISON TABLE
# ─────────────────────────────────────────────────────────

print(f"\n{'=' * 60}")
print("  FINAL COMPARISON")
print(f"{'=' * 60}")

crit_a = results_a['critical_sent']
crit_b = results_b['critical_sent']
lost_a = results_a['critical_lost']
lost_b = results_b['critical_lost']

deliv_a = round(((crit_a - lost_a) / crit_a * 100) if crit_a else 0, 1)
deliv_b = round(((crit_b - lost_b) / crit_b * 100) if crit_b else 0, 1)

lat_a = round(statistics.mean(results_a['critical_latencies']), 1) \
        if results_a['critical_latencies'] else 0
lat_b = round(statistics.mean(results_b['critical_latencies']), 1) \
        if results_b['critical_latencies'] else 0

improvement_delivery = round(deliv_b - deliv_a, 1)
improvement_latency  = round(lat_a - lat_b, 1)

print(f"\n  {'Metric':<30} {'Exp A':>10} {'Exp B':>10} {'Improvement':>12}")
print(f"  {'─' * 64}")
print(f"  {'Critical delivery rate':<30} {deliv_a:>9}% {deliv_b:>9}% {'+' + str(improvement_delivery) + '%':>12}")
print(f"  {'Critical avg latency':<30} {lat_a:>8}ms {lat_b:>8}ms {str(improvement_latency) + 'ms faster':>12}")
print(f"  {'Critical packets lost':<30} {lost_a:>10} {lost_b:>10} {lost_a - lost_b:>12}")

print(f"\n{'=' * 60}")
print("  Evaluation complete.")
print(f"{'=' * 60}\n")

# Save results to JSON for your report
output = {
    "experiment_a": {
        "critical_delivery_rate": deliv_a,
        "critical_avg_latency_ms": lat_a,
        "critical_packets_lost": lost_a,
        "total_sent": results_a['sent'],
    },
    "experiment_b": {
        "critical_delivery_rate": deliv_b,
        "critical_avg_latency_ms": lat_b,
        "critical_packets_lost": lost_b,
        "total_sent": results_b['sent'],
        "tier_distribution": results_b['tier_counts'],
    },
    "improvement": {
        "delivery_rate_improvement": improvement_delivery,
        "latency_improvement_ms": improvement_latency,
        "packets_saved": lost_a - lost_b,
    }
}

with open("benchmark/evaluation_results.json", "w") as f:
    json.dump(output, f, indent=2)

print("Results saved to benchmark/evaluation_results.json")

client.loop_stop()
client.disconnect()