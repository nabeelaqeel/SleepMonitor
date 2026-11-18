"""Payload-contract tests for the publisher's identity fields.

Parallel demo watches are only collision-free if every message a publisher
instance emits carries the identity triple the backend registry binds on:
patientId + deviceId + sessionId (camelCase, exactly as the ingest worker
reads them). These tests pin that contract offline: the publish functions
are driven against an in-memory fake client — no broker, no network — and
publisher/start_sim_device.sh is exercised at subprocess level against a
stub interpreter that dumps its environment.

publisher.py is loaded fresh per test by file path (test_tier_rules.py
documents why: script directories legitimately end up on sys.path and a
`publisher.` package import would then resolve to publisher.py the MODULE).
Each load re-mints SESSION_ID and re-reads the environment, so tests stay
independent of each other and of .env.development contents.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLISHER_FILE = REPO_ROOT / "publisher" / "publisher.py"
LAUNCHER_FILE = REPO_ROOT / "publisher" / "start_sim_device.sh"

ENV_KEYS = ("DEVICE_ID", "PATIENT_ID", "CSV_PATH", "MQTT_HOST", "MQTT_PORT")
_module_counter = itertools.count()


def _load_publisher(monkeypatch, **env):
    """Load publisher.py as a fresh module with `env` exported; return it.

    Values from `env` win; anything unset falls through to .env.development
    (load_dotenv never overrides already-set variables). sys.path needs the
    publisher/ directory so the module's `from tier_rules import classify`
    resolves.
    """
    monkeypatch.syspath_prepend(str(REPO_ROOT / "publisher"))
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location(
        f"publisher_contract_under_test_{next(_module_counter)}", PUBLISHER_FILE
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _PublishedResult:
    def wait_for_publish(self, timeout=None):
        return True


class FakeClient:
    """In-memory paho-mqtt stand-in recording every publish() as (topic, payload-dict, qos)."""

    def __init__(self):
        self.published = []

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append((topic, json.loads(payload), qos))
        return _PublishedResult()


def _publish_one_of_each(module):
    """Drive every message type through the module against a FakeClient."""
    client = FakeClient()
    module.publish_session_event(client, "start")
    module.publish_session_event(client, "end", reason="clean shutdown")
    row = pd.Series({"bo": 97.0, "hr": 65.0, "hrv": 40.0, "lm": 0.0})
    module.publish_reading(client, row, row_idx=0)
    module.publish_background_stats(client)
    return client


def test_every_message_type_carries_identity_triple(monkeypatch):
    """session/start, session/end, a reading and background stats all bind the same patient/device/session."""
    module = _load_publisher(
        monkeypatch, PATIENT_ID="patient-042", DEVICE_ID="sleepband-042"
    )
    client = _publish_one_of_each(module)

    assert [topic for topic, _payload, _qos in client.published] == [
        "session/start", "session/end", "sleep/normal", "sleep/background",
    ]
    for topic, payload, _qos in client.published:
        assert payload["patientId"] == "patient-042", topic
        assert payload["deviceId"] == "sleepband-042", topic
        assert payload["sessionId"] == module.SESSION_ID, topic


def test_reading_payload_identity_matches_module_env(monkeypatch):
    """A reading binds whatever identity the process was configured with."""
    module = _load_publisher(monkeypatch)
    client = FakeClient()
    module.publish_reading(
        client, pd.Series({"spo2": 95.0, "hr": 60.0, "hrv": 30.0}), row_idx=7
    )
    _topic, payload, _qos = client.published[0]
    assert payload["patientId"] == module.PATIENT_ID
    assert payload["deviceId"] == module.DEVICE_ID
    assert payload["sessionId"] == module.SESSION_ID


def test_seq_monotonic_within_session_and_reset_per_load(monkeypatch):
    """`_seq` counts up across readings and restarts at 0 for a fresh session (new process)."""
    module = _load_publisher(monkeypatch)
    client = FakeClient()
    row = pd.Series({"bo": 97.0, "hr": 65.0, "hrv": 40.0})
    module.publish_reading(client, row, row_idx=0)
    module.publish_reading(client, row, row_idx=1)
    assert [payload["seq"] for _t, payload, _q in client.published] == [0, 1]

    fresh = _load_publisher(monkeypatch)
    fresh_client = FakeClient()
    fresh.publish_reading(fresh_client, row, row_idx=0)
    assert fresh_client.published[0][1]["seq"] == 0
    assert fresh.SESSION_ID != module.SESSION_ID


class _StubMqttClient:
    """Records constructor/will/credentials/connect args; connect() is a no-op."""

    def __init__(self, callback_api_version, client_id="", protocol=None):
        self.client_id = client_id
        self.will = None
        self.credentials = None
        self.connect_args = None

    def username_pw_set(self, user, password=None):
        self.credentials = (user, password)

    def will_set(self, topic, payload=None, qos=0, retain=False):
        self.will = (topic, payload, qos, retain)

    def connect(self, host, port, keepalive=0):
        self.connect_args = (host, port, keepalive)
        return 0


def _build_with_stub_mqtt(monkeypatch, module):
    """Swap the module's paho handle for a stub namespace so build_client() stays offline."""
    fake_mqtt = SimpleNamespace(
        CallbackAPIVersion=SimpleNamespace(VERSION2=object()),
        MQTTv5=object(),
        Client=_StubMqttClient,
    )
    monkeypatch.setattr(module, "mqtt", fake_mqtt)
    return module.build_client()


def test_client_id_reflects_patient_id(monkeypatch):
    module = _load_publisher(monkeypatch, PATIENT_ID="patient-042")
    client = _build_with_stub_mqtt(monkeypatch, module)
    assert client.client_id == "sleep-publisher-patient-042"
    assert client.connect_args == (module.MQTT_HOST, module.MQTT_PORT, 60)


def test_last_will_payload_carries_identity(monkeypatch):
    module = _load_publisher(
        monkeypatch, PATIENT_ID="patient-042", DEVICE_ID="sleepband-042"
    )
    client = _build_with_stub_mqtt(monkeypatch, module)

    topic, payload, qos, retain = client.will
    assert topic == "session/end"
    parsed = json.loads(payload)
    assert parsed["sessionId"] == module.SESSION_ID
    assert parsed["patientId"] == "patient-042"
    assert parsed["deviceId"] == "sleepband-042"
    assert parsed["event"] == "end"
    assert qos == 1
    assert retain is False


def _stub_interpreter(venv_bin: Path) -> Path:
    venv_bin.mkdir(parents=True)
    stub = venv_bin / "python"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os\n"
        f"print(json.dumps({{k: os.environ.get(k) for k in {ENV_KEYS!r}}}))\n"
    )
    stub.chmod(
        stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    )
    return stub


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_launcher_passes_env_through(tmp_path):
    """The real launcher, run from a temp tree with a stub interpreter, forwards required and optional vars."""
    (tmp_path / "publisher").mkdir()
    shutil.copy(LAUNCHER_FILE, tmp_path / "publisher" / "start_sim_device.sh")
    _stub_interpreter(tmp_path / ".venv-dev" / "bin")

    env = dict(os.environ)
    env.update({
        "DEVICE_ID": "sleepband-042",
        "PATIENT_ID": "patient-042",
        "CSV_PATH": "data/other_night.csv",
        "MQTT_HOST": "127.0.0.1",
        "MQTT_PORT": "1884",
    })
    result = subprocess.run(
        ["bash", str(tmp_path / "publisher" / "start_sim_device.sh")],
        check=False, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout)
    assert seen == {
        "DEVICE_ID": "sleepband-042",
        "PATIENT_ID": "patient-042",
        "CSV_PATH": "data/other_night.csv",
        "MQTT_HOST": "127.0.0.1",
        "MQTT_PORT": "1884",
    }


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_launcher_leaves_unset_optionals_unexported(tmp_path):
    """Optional variables absent from the caller's env must not be exported as empty strings (that would clobber publisher defaults)."""
    (tmp_path / "publisher").mkdir()
    shutil.copy(LAUNCHER_FILE, tmp_path / "publisher" / "start_sim_device.sh")
    _stub_interpreter(tmp_path / ".venv-dev" / "bin")

    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ENV_KEYS  # also strips values leaked into pytest's own env by dotenv loaders
    }
    env.update({"DEVICE_ID": "sleepband-042", "PATIENT_ID": "patient-042"})
    result = subprocess.run(
        ["bash", str(tmp_path / "publisher" / "start_sim_device.sh")],
        check=False, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout)
    assert seen["DEVICE_ID"] == "sleepband-042"
    assert seen["PATIENT_ID"] == "patient-042"
    assert seen["CSV_PATH"] is None
    assert seen["MQTT_HOST"] is None
    assert seen["MQTT_PORT"] is None


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")
def test_launcher_usage_without_required_ids():
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("DEVICE_ID", "PATIENT_ID")
    }
    result = subprocess.run(
        ["bash", str(LAUNCHER_FILE)],
        check=False, cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0
    assert "DEVICE_ID" in result.stderr
    assert "PATIENT_ID" in result.stderr
