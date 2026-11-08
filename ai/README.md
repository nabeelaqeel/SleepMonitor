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

## Demo mode (container, off by default)

`ai/demo.py` fabricates a synthetic night of readings in-process (no database)
and runs them through the REAL trained model, so everything it prints/publishes
is a genuine model output. Scenarios — `healthy`, `monitor`, `apnea` — mirror
the three research bands by episode cadence and nightly SpO2 profile.
`rotate` cycles all three in order.

```bash
# Local, print only (what the model says for a synthetic night)
.venv-dev/bin/python -m ai.demo --scenario apnea

# Local, publish to the host broker
.venv-dev/bin/python -m ai.demo --scenario monitor --publish \
  --patient-id 00000000-0000-0000-0000-000000000002 --host localhost
```

Container demo (AWS stack) — demo mode is a compose profile, OFF by default:

```bash
# ON: one extra flag — sleep-ai-demo publishes every AI_DEMO_INTERVAL seconds
docker compose -f docker-compose.aws.yml --env-file .env.development \
  --profile ai-demo up -d --build

# Script form (deploys): ./deploy/deploy-update.sh --ai-demo — same profile,
# added on top of the mode's profile (TEST keeps local-db), and sleep-ai-demo
# joins the post-deploy container verification.
#
# ⚠ Existing deployments: --ai-demo does NOT write the patient id into
# .env.development. If the file lacks AI_DEMO_PATIENT_ID, compose falls back
# to the demo's built-in placeholder patient (demo-patient) — the container
# looks healthy and verification passes, but the account you actually log
# into never receives the band. Set AI_DEMO_PATIENT_ID to the login
# account's patient UUID first (the seeded patient@sleep.com account is
# 00000000-0000-0000-0000-000000000002), or use ./deploy/bootstrap.sh
# --ai-demo, which appends the seeded value (existing keys are preserved).

# OFF: drop the flag, then:
docker compose -f docker-compose.aws.yml --env-file .env.development up -d
```

While demo mode is ON, the sleep-ai-demo service publishes (retained) to
`sleep/recommendation` every `AI_DEMO_INTERVAL` seconds with
`AI_DEMO_PATIENT_ID` as the payload's patientId — so the app account you log
into with that patientId shows the band on the Home screen. Drops of ~0.1
probability aside, the bands match the model's real behaviour for the staged
night.

> Demo-only caveat: the trained model artifact (`ai/models/rf_phase2.joblib`)
> is baked into the image so the demo profile can run it. Keep demo images
> private (they are built on the server, never pushed).

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
| `ai/config.py` | Phase-2 config loader (`ai/config/phase2.yaml`) |
| `ai/features.py` | Nightly feature computation from session readings |
| `ai/classifier.py` | Trained model wrapper (`ai/models/rf_phase2.joblib`) |
| `ai/nightly_adapter.py` | Session-to-nightly-feature bridge |
| `ai/nightly.py` | Optional post-night CLI |
| `ai/mqtt.py` | Broker publisher used by the AI module only |
| `ai/config/phase2.yaml` | Band boundaries and feature thresholds |
