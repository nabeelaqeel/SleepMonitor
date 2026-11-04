# AI Recommendation Module

This module is a **supplementary, non-diagnostic** layer. It is completely
separate from the RB-QoSPCTF QoS tiering and the publisher/ingest pipeline.

It uses the trained Random Forest model from the AI-recommendation repo to
produce post-night guidance bands: Healthy / Monitor / See Doctor. It does not
compute AHI, does not use respiratory events, and does not diagnose any
condition.

## Deployment

```text
session ends
    → ingest worker persists readings
    → nightly analysis job loads the session
    → `ai/nightly_adapter.py` maps the session to nightly features
    → `ai/classifier.py` produces the guidance band
    → the app displays the band and disclaimer
```

It is intentionally never run during the live session. The model requires a
10-minute / night-level rolling buffer, and the app only needs the completed
band, not per-reading inference.

## Non-diagnostic disclaimer

Every output includes:

```text
Research guidance band only. Not a diagnosis, not clinically validated, and not
a substitute for medical review.
```

The model artifacts and clinical config stay local. The model is trained from
PAAWS, not SleepMonitor data, so the app treats the output as a research
prototype and never as a clinical finding.

## Command used after nightly analysis

```bash
.venv-dev/bin/python -m ai.recommend --session-id <session-id>
```

Optionally publish the result to the broker:

```bash
.venv-dev/bin/python -m ai.recommend --session-id <session-id> --publish
```

The message is delivered on `sleep/recommendation` with:

- QoS 1
- retain false by default
- non-diagnostic disclaimer

```json
{
  "sessionId": "...",
  "patientId": "...",
  "band": "Monitor",
  "p_positive": 0.31,
  "thresholdFlagged": false,
  "disclaimer": "Research guidance band only. Not a diagnosis, not clinically validated.",
  "computedAt": "..."
}
```

## Related modules

| Path | Purpose |
|---|---|
| `ai/config.py` | Phase-2 config loader (`config/phase2.yaml`) |
| `ai/features.py` | Nightly feature computation from session readings |
| `ai/classifier.py` | Trained model wrapper |
| `ai/nightly_adapter.py` | Session-to-nightly-feature bridge |
| `ai/nightly.py` | Optional post-night CLI |
| `ai/mqtt.py` | Broker publisher used by the AI module only |
| `models/rf_phase2.joblib` | Trained model artifact (kept local, gitignored) |
| `config/phase2.yaml` | Band boundaries and feature thresholds |
