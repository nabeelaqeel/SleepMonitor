import pandas as pd
import numpy as np
import random

random.seed(42)
np.random.seed(42)

TOTAL_MINUTES = 480      # 8 hours
APNEA_PROBABILITY = 0.04 # ~4% of readings trigger an apnea event

rows = []
spo2 = 97.0              # start at normal SpO2
hr   = 58.0              # normal sleeping heart rate
hrv  = 35.0              # normal HRV

for minute in range(TOTAL_MINUTES):

    # Simulate apnea event — SpO2 drops gradually then recovers
    if random.random() < APNEA_PROBABILITY:
        # Apnea episode — 3 to 6 minutes of desaturation
        episode_length = random.randint(3, 6)
        for i in range(episode_length):
            if minute + i >= TOTAL_MINUTES:
                break
            drop = random.uniform(4, 12)      # drop 4–12% SpO2
            spo2 = max(82, spo2 - drop)       # floor at 82%
            hr   = random.uniform(48, 58)     # HR drops slightly
            hrv  = random.uniform(10, 18)     # HRV drops during apnea
            rows.append({
                'minute':    minute + i,
                'spo2':      round(spo2, 1),
                'hr':        round(hr, 1),
                'hrv':       round(hrv, 1),
                'motion':    round(random.uniform(0.1, 0.4), 2),
                'event':     'apnea'
            })
        # Recovery after episode
        spo2 = random.uniform(94, 97)
        hr   = random.uniform(55, 65)
        hrv  = random.uniform(28, 40)
        continue

    # Normal sleep — small realistic fluctuations
    spo2 = spo2 + random.uniform(-0.3, 0.3)
    spo2 = round(max(94.0, min(99.0, spo2)), 1)   # clamp 94–99%
    hr   = hr   + random.uniform(-1.0, 1.0)
    hr   = round(max(48.0, min(70.0, hr)),   1)    # clamp 48–70 bpm
    hrv  = hrv  + random.uniform(-2.0, 2.0)
    hrv  = round(max(20.0, min(55.0, hrv)),  1)    # clamp 20–55 ms

    rows.append({
        'minute':  minute,
        'spo2':    spo2,
        'hr':      hr,
        'hrv':     hrv,
        'motion':  round(random.uniform(0.0, 0.2), 2),
        'event':   'normal'
    })

df = pd.DataFrame(rows)
df.to_csv('sleep_data_realistic.csv', index=False)
print(f"Generated {len(df)} rows")
print(f"SpO2 range: {df['spo2'].min()} – {df['spo2'].max()}")
print(f"Critical rows (SpO2 < 90): {len(df[df['spo2'] < 90])}")
print(f"Apnea events: {df[df['event'] == 'apnea'].shape[0]} readings")
print(df.head(10))