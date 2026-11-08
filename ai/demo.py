"""Synthetic AI-recommendation demo — shows what the trained model would say.

This module exists ONLY for the demo (docker compose `ai-demo` profile or a
manual host run). It fabricates a plausible night of readings in-process —
WITHOUT touching Postgres or the ingest pipeline — and runs the REAL trained
model (`ai/nightly_adapter.get_recommendation`), so the band / probability /
disclaimer it publishes are genuine model outputs for that synthetic night.

Scenario profiles deliberately mirror the research bands of the trained model
(3-class AHI boundaries in ai/config/phase2.yaml: healthy < 5, monitor 5–15,
see_doctor >= 15 events per night), staged over an 8 h night of 30-second
epochs — 960 readings:

    healthy : no clinically meaningful desaturations (≤ 1 small dip)
    monitor : ~9 moderate episodes in the 5–15 range
    apnea   : ~27 deep, frequent episodes (≥ 15 range)

CLI:
    # print the analysis only — nothing is sent anywhere
    .venv-dev/bin/python -m ai.demo --scenario apnea

    # host one-shot publish to sleep/recommendation
    .venv-dev/bin/python -m ai.demo --scenario apnea --publish \
        --patient-id <app-user-patientId>

    # container/demo mode: publish on a loop (used by the ai-demo compose service)
    docker compose -f docker-compose.aws.yml --env-file .env.development \
        --profile ai-demo up -d     # demo ON; drop the flag + up -d for OFF

The published payload's patientId must equal the app account's patientId —
the app stores recommendations keyed by that field (SleepContext.js), so a
mismatched id never shows on the Home screen. Each publish carries extra
`demoScenario` / `synthetic` keys (the app ignores them) to make broker logs
self-explanatory.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import signal
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from .mqtt import publish
from .nightly_adapter import get_recommendation
from .recommend import recommendation_payload

DEFAULT_TOPIC = "sleep/recommendation"

EPOCH_SECONDS = 30          # matches ai/config/phase2.yaml features.epoch_seconds
DEFAULT_EPOCHS = 960        # 8 h night = 960 * 30 s
SCENARIOS = ("healthy", "monitor", "apnea")
SCENARIO_SEEDS = {"healthy": 11, "monitor": 22, "apnea": 33}


# ─── synthetic night generator ────────────────────────────────────────────────

class _ScenarioProfile:
    """Episode cadence + physiologic baselines for one scenario."""

    __slots__ = ("name", "episode_every", "episode_max_epochs", "drop_min",
                 "desat_floor", "spo2_range", "hr_range", "hrv_range")

    def __init__(self, name: str):
        """Fill in episode cadence and physiologic ranges for the requested scenario name."""
        self.name = name
        if name == "healthy":
            self.episode_every = 480      # ≤ 2 shallow dips across the night
            self.episode_max_epochs = 1
            self.drop_min = 1.0
            self.desat_floor = 93.8
            self.spo2_range = (96.2, 98.2)
            self.hr_range = (50.0, 62.0)
            self.hrv_range = (30.0, 55.0)
        elif self.name == "monitor":
            self.episode_every = 70       # ~12 events / 8 h (5–15 range)
            self.episode_max_epochs = 4   # episodes last 1–2 min
            self.drop_min = 3.0
            self.desat_floor = 89.5
            self.spo2_range = (94.0, 95.0)
            self.hr_range = (52.0, 66.0)
            self.hrv_range = (20.0, 50.0)
        else:  # apnea
            self.episode_every = 32       # ~1 event per 16 min -> ~27 / 8 h
            self.episode_max_epochs = 6   # episodes last 1–3 min
            self.drop_min = 6.0
            self.desat_floor = 81.5
            self.spo2_range = (92.6, 94.2)
            self.hr_range = (55.0, 70.0)
            self.hrv_range = (12.0, 45.0)


def synth_night(scenario: str, *, epochs: int = DEFAULT_EPOCHS,
                base_seed: int = 42) -> list[dict]:
    """Epoch-cadence night shaped for `get_recommendation`.

    Each reading carries the canonical adapter names:
    {timestamp, spo2, heart_rate, hrv, motion} (hrv -> rmssd_ms, heart_rate -> hr).
    """
    profile = _ScenarioProfile(scenario)
    profile.name = scenario
    rng = random.Random(base_seed + SCENARIO_SEEDS.get(scenario, 0))

    start = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start -= timedelta(seconds=(start.minute % 2) * EPOCH_SECONDS)

    def wiggle(value, lo, hi, step):
        """One bounded random-walk step; landing outside [lo, hi] snaps to a fresh uniform draw inside."""
        value += rng.uniform(-step, step)
        if value < lo or value > hi:
            value = rng.uniform(lo, hi)
        return value

    def next_epoch_ts(i: int) -> str:
        """ISO timestamp (Z-suffixed, seconds) of epoch i on the minute-aligned start."""
        ts = start + timedelta(seconds=i * EPOCH_SECONDS)
        return ts.isoformat(timespec="seconds").replace("+00:00", "Z")

    spo2 = rng.uniform(*profile.spo2_range)
    hr = rng.uniform(*profile.hr_range)
    hrv = rng.uniform(*profile.hrv_range)

    readings: list[dict] = []
    # Episode bookkeeping
    ep_start = -1
    ep_len = 0
    ep_spo2_from = ep_spo2_target = 0.0
    ep_extra_hr = 0.0
    ep_hrv_cap = 0.0

    for i in range(epochs):
        ts = next_epoch_ts(i)

        # Episode scheduling (healthy: never)
        start_new = (
            profile.episode_every
            and ep_start < 0
            and i % profile.episode_every == 0
        )
        if start_new:
            ep_len = rng.randint(1, max(1, profile.episode_max_epochs))
            ep_start = i
            ep_spo2_from = spo2
            ep_spo2_target = rng.uniform(
                profile.desat_floor,
                profile.desat_floor + profile.drop_min,
            )
            ep_extra_hr = rng.uniform(8.0, 16.0)
            ep_hrv_cap = rng.uniform(6.0, max(14.0, profile.hrv_range[0] - 6.0))

        if 0 <= ep_start <= i < ep_start + ep_len:
            # Within an episode: SpO2 ramps from baseline to the target floor,
            # heart rate raises (arousal response), RMSSD falls. A 1-epoch
            # episode dips fully in that single epoch.
            progress = (i - ep_start + 1) / max(1, ep_len)
            spo2 = ep_spo2_from + (ep_spo2_target - ep_spo2_from) * progress
            hr = wiggle(hr, profile.hr_range[1] + 4.0,
                        profile.hr_range[1] + ep_extra_hr, 2.0)
            hrv = wiggle(hrv, 5.0, ep_hrv_cap, 3.0)
            motion = rng.uniform(0.0, 0.8)
        else:
            if ep_start >= 0 and ep_len and i >= ep_start + ep_len:
                # Just ended — abrupt rebound to baseline, like real recovery.
                spo2 = rng.uniform(*profile.spo2_range)
                hr = rng.uniform(*profile.hr_range)
                hrv = rng.uniform(*profile.hrv_range)
                ep_start = -1
                ep_len = 0
            spo2 = wiggle(spo2, profile.spo2_range[0], profile.spo2_range[1], 0.15)
            hr = wiggle(hr, profile.hr_range[0], profile.hr_range[1], 0.8)
            hrv = wiggle(hrv, profile.hrv_range[0], profile.hrv_range[1], 1.5)
            motion = rng.uniform(0.0, 0.3)

        readings.append({
            "timestamp":  ts,
            "spo2":       round(min(100.0, max(80.0, spo2)), 1),
            "heart_rate": round(hr, 1),
            "hrv":        round(min(200.0, max(5.0, hrv)), 1),
            "motion":     round(motion, 2),
        })
    return readings


# ─── one scenario through the real model ─────────────────────────────────────

def analyse(scenario: str, *, epochs: int, base_seed: int,
            session_id: str, patient_id: str | None) -> dict:
    """Synthetic readings -> real model -> the payload the app would receive."""
    readings = synth_night(scenario, epochs=epochs, base_seed=base_seed)
    result = get_recommendation(
        readings,
        session_id=session_id,
        patient_id=patient_id,
    )
    payload = recommendation_payload(result)
    payload["demoScenario"] = scenario   # extras are ignored by the app
    payload["synthetic"] = True
    return payload


def describe(payload: dict) -> str:
    """One-line verdict rendering: band, p_positive and any nightly error tag."""
    band = payload.get("band")
    p = payload.get("p_positive")
    p = "n/a" if p is None else f"{p:.2f}"
    err = (payload.get("nightly") or {}).get("error")
    tag = f" ({err})" if err else ""
    return f"band={band!r} p_positive={p}{tag}"


# ─── main ────────────────────────────────────────────────────────────────────

def main() -> int:
    """Argparse entry: run the scenario(s) through the real model — print-only by default, --publish one-shot, or --publish-loop every --interval seconds for the container mode."""
    # Same convention as ai/session_loader / ai/nightly: env comes from
    # .env.development (MQTT host/auth, AI_DEMO_PATIENT_ID).
    load_dotenv(".env.development")
    parser = argparse.ArgumentParser(
        description="Synthetic AI-recommendation demo (no DB, real model)",
    )
    parser.add_argument(
        "--scenario", choices=tuple(SCENARIOS) + ("rotate",), default="rotate",
        help="synthetic night profile; rotate cycles all three (default)",
    )
    parser.add_argument(
        "--patient-id",
        default=os.getenv("AI_DEMO_PATIENT_ID") or "demo-patient",
        help="app-user patientId the payload pretends to belong to "
             "(default: AI_DEMO_PATIENT_ID env). Must match the account you "
             "log into for the band to show on the Home screen",
    )
    parser.add_argument("--publish", action="store_true",
        help="publish each result to MQTT (default: print only)")
    parser.add_argument("--publish-loop", action="store_true",
        help="publish forever every --interval seconds (container mode)")
    parser.add_argument("--interval", type=int, default=60, metavar="SECONDS",
        help="seconds between publishes in --publish-loop mode (60)")
    parser.add_argument("--retain", action="store_true",
        help="publish with MQTT retain so the app shows the band on connect")
    parser.add_argument("--topic", default=DEFAULT_TOPIC)
    parser.add_argument("--host", default=None,
        help="MQTT broker host override (default: MQTT_HOST env, "
             "'broker' inside compose / localhost on this machine)")
    parser.add_argument("--port", type=int, default=None,
        help="MQTT broker port override (default: MQTT_PORT env or 1883)")
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS, metavar="N",
        help=f"30s epochs per night ({DEFAULT_EPOCHS})")
    parser.add_argument("--seed", type=int, default=42, metavar="N",
        help="base random seed (42); each scenario unpacks its own seed")
    args = parser.parse_args()

    run_state = {"stop": False}

    def _on_stop(_sig, _frame):
        """SIGINT/SIGTERM handler — flips the shared stop flag; the sleep loop picks it up within a second."""
        run_state["stop"] = True

    signal.signal(signal.SIGINT, _on_stop)
    signal.signal(signal.SIGTERM, _on_stop)

    def interruptible_sleep(seconds: int) -> bool:
        """Sleep seconds in 1 s slices so a stop flag ends the wait early; returns True when interrupted."""
        for _ in range(max(1, seconds)):
            if run_state["stop"]:
                return True
            time.sleep(1)
        return False

    def one(scenario: str) -> dict | None:
        """Analyse one scenario through the real model; errors become a stderr note and None instead of crashing the loop."""
        try:
            return analyse(
                scenario,
                epochs=args.epochs,
                base_seed=args.seed,
                session_id=str(uuid.uuid4()),
                patient_id=args.patient_id or None,
            )
        except Exception as e:  # model missing / config mis-load etc
            print(f"[ai-demo] scenario={scenario} FAILED: {e}", file=sys.stderr)
            return None

    def emit(payload: dict) -> None:
        """Log a timestamped verdict line (+ the JSON payload) and publish to MQTT in publish modes, with host/topic/retain from args and env."""
        now = datetime.now(timezone.utc).strftime("%H:%M:%SZ")
        line = (f"[ai-demo] {now} scenario={payload['demoScenario']:<7} "
                f"{describe(payload)}")
        if args.publish or args.publish_loop:
            host = args.host or os.getenv("MQTT_HOST", "localhost")
            port = args.port or int(os.getenv("MQTT_PORT", "1883"))
            publish(args.topic, payload, qos=1, retain=args.retain,
                    host=host, port=port)
            line += f"  → {args.topic} @ {host}:{port} (retain={bool(args.retain)})"
        else:
            line += "  → printed only (add --publish to send)"
        print(line, flush=True)
        print(json.dumps(payload, indent=2, default=str), flush=True)

    scenarios = SCENARIOS if args.scenario == "rotate" else (args.scenario,)

    if args.publish_loop:
        print(f"[ai-demo] loop: publish every {args.interval}s to {args.topic} "
              f"(retain={bool(args.retain)}, patientId={args.patient_id!r}, "
              f"scenario={args.scenario})", flush=True)
        cycle = itertools.cycle(scenarios)
        while not run_state["stop"]:
            for scenario in cycle:
                payload = one(scenario)
                if payload:
                    emit(payload)
                if interruptible_sleep(args.interval) or run_state["stop"]:
                    break
        print("[ai-demo] demo loop stopped.", flush=True)
        return 0

    # One-shot: print (or --publish) each scenario once, in order.
    for scenario in scenarios:
        payload = one(scenario)
        if payload:
            emit(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
