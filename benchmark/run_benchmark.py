#!/usr/bin/env python3
"""
Single-clock MQTT QoS benchmark — driver.

One process hosts the publishing client, the measuring subscriber and a $SYS
watcher. All timestamps use time.monotonic_ns() on the same host, so latency
is one-way (t1 - t0): no clock synchronisation error, no RTT/2 estimate.

Experiments
    A  all messages at QoS 0 (uniform baseline)
    B  tiered: Critical=2, Important=1, Normal=0, Background=0
    C  all messages at QoS 2 (uniform "safe" baseline)

Scenarios
    clean         no impairment
    netem         tc netem on lo (delay 25ms 10ms loss 2%)
    outage-pNN    subscriber disconnects for 5 s at NN% of the readings

See benchmark/README.md for methodology, gates and caveats.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import random
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

BENCH_DIR = Path(__file__).resolve().parent
ROOT = BENCH_DIR.parent
sys.path.insert(0, str(ROOT / "python-publisher"))

from classifier import classify  # noqa: E402

METHOD_VERSION = "2.0.0"
SOCKETPAIR_STOCK = "stock"
SOCKETPAIR_AF_UNIX = "af_unix"
PREFLIGHT_LO_SECONDS = 10.0
RUN_IDLE_SECONDS = 5.0

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
TOPIC_FILTER = "bench/#"
TOPIC_UNIFORM = "bench/uniform"
TIER_TOPICS = {
    "Critical": "bench/critical",
    "Important": "bench/important",
    "Normal": "bench/normal",
    "Background": "bench/background",
}
TIER_QOS = {"Critical": 2, "Important": 1, "Normal": 0, "Background": 0}

DATASET_PATH = ROOT / "data" / "sleep_data_realistic.csv"
EXPECTED_DATASET_SHA256 = (
    "10e9df7fc38087b8caad72aebdee3975f752da3dd4bd5d79f7aa7aa1b3de64de")
CLASSIFIER_PATH = ROOT / "python-publisher" / "classifier.py"
ANALYSIS_PATH = BENCH_DIR / "analyze_benchmark.py"
FULL_ROWS, QUICK_ROWS, SENS_ROWS = 526, 60, 100

WARMUP_ROWS = 10
BACKGROUND_EVERY = 10
DEFAULT_INTERVAL, SENS_INTERVAL = 0.1, 1.0
OUTAGE_SECONDS = 5.0
OUTAGE_FRACTIONS = (0.25, 0.50, 0.75)
QUIET_CLEAN, QUIET_NETEM = 2.0, 5.0

SESSION_EXPIRY, KEEPALIVE, MAX_INFLIGHT = 300, 60, 100
NETEM_CMD = ["tc", "qdisc", "add", "dev", "lo", "root", "netem",
             "delay", "25ms", "10ms", "loss", "2%"]
NETEM_STRING = "tc qdisc add dev lo root netem delay 25ms 10ms loss 2%"
NETEM_DELAY_ONLY_CMD = ["tc", "qdisc", "add", "dev", "lo", "root", "netem",
                        "delay", "25ms", "10ms"]
NETEM_DELAY_ONLY_STRING = "tc qdisc add dev lo root netem delay 25ms 10ms"
NETEM_SHOW_CMD = ["tc", "qdisc", "show", "dev", "lo"]
NETEM_CLEAR_CMD = ["sudo", "-n", "tc", "qdisc", "del", "dev", "lo", "root"]

MQTT_SETTINGS = {
    "protocol": 5,
    "session_expiry_s": SESSION_EXPIRY,
    "keepalive_s": KEEPALIVE,
    "initial_clean_start": True,
    "reconnect_clean_start": False,
    "max_inflight_messages": MAX_INFLIGHT,
}

BROKER_RELEVANT = ("queue_qos0_messages", "max_queued_messages",
                   "max_inflight_messages", "persistence", "per_listener_settings")
BROKER_DEFAULTS = {
    "queue_qos0_messages": False,
    "max_queued_messages": 1000,
    "max_inflight_messages": 20,
    "persistence": False,
    "per_listener_settings": False,
}

SENT_FIELDS = ["run_id", "experiment", "scenario", "position", "rep", "seq",
               "row", "kind", "tier", "qos", "t0_ns", "ack_ns", "warmup"]
RECV_FIELDS = ["run_id", "seq", "t1_ns"]

_abort = threading.Event()
_netem_lock = threading.RLock()
_netem_applied = False


class Aborted(Exception):
    pass


class NetemClearError(RuntimeError):
    pass


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def now_iso():
    return datetime.now(timezone.utc).strftime("%I:%M %p")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def paho_version():
    try:
        import paho.mqtt as paho_pkg
        return getattr(paho_pkg, "__version__", "unknown")
    except Exception:
        return "unknown"


def install_socketpair(mode):
    """Install paho's cross-thread wake-up socketpair implementation."""
    if mode == SOCKETPAIR_STOCK:
        return
    if mode != SOCKETPAIR_AF_UNIX:
        raise SystemExit(f"unknown socketpair mode: {mode}")

    import paho.mqtt.client as paho_client
    if not hasattr(paho_client, "_socketpair_compat"):
        raise SystemExit(
            f"paho-mqtt {paho_version()} has no _socketpair_compat; "
            "AF_UNIX patching is not supported")

    def af_unix_pair():
        reader, writer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        reader.setblocking(False)
        writer.setblocking(False)
        return reader, writer

    paho_client._socketpair_compat = af_unix_pair


def enable_tcp_nodelay(client):
    sock = client.socket()
    if sock is None:
        raise RuntimeError("cannot set TCP_NODELAY: client socket is not open")
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)


def sample_lo_idle(seconds, max_pps=None):
    """Sample loopback TX traffic; record-only when max_pps is None."""
    before = read_lo_tx()
    if before is None:
        return {"seconds": seconds, "error": "cannot read lo counters"}
    started = time.monotonic()
    time.sleep(seconds)
    after = read_lo_tx()
    if after is None:
        return {"seconds": seconds, "error": "cannot re-read lo counters"}
    elapsed = time.monotonic() - started
    delta_bytes = after[0] - before[0]
    delta_packets = after[1] - before[1]
    pps = delta_packets / elapsed if elapsed else None
    flagged = None
    if max_pps is not None:
        flagged = pps is not None and pps > max_pps
    return {
        "seconds": round(elapsed, 3),
        "tx_bytes": delta_bytes,
        "tx_packets": delta_packets,
        "bytes_per_s": round(delta_bytes / elapsed, 2) if elapsed else None,
        "packets_per_s": round(pps, 2) if pps is not None else None,
        "max_pps": max_pps,
        "flagged": flagged,
    }


def sleep_until(target_ns):
    while True:
        if _abort.is_set():
            raise Aborted()
        remaining = (target_ns - time.monotonic_ns()) / 1e9
        if remaining <= 0:
            return
        time.sleep(min(remaining, 0.05))


def wait_until(cond, timeout, what, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _abort.is_set():
            raise Aborted()
        if cond():
            return True
        time.sleep(interval)
    log(f"WARNING: timeout waiting for {what} ({timeout:.0f}s)")
    return False


def read_lo_tx():
    """TX-only loopback counters (loopback mirrors every packet into RX too)."""
    try:
        out = subprocess.run(["ip", "-j", "-s", "link", "show", "lo"],
                             capture_output=True, text=True, check=True).stdout
        data = json.loads(out)[0]
        stats = data.get("stats64") or data["stats"]
        return int(stats["tx"]["bytes"]), int(stats["tx"]["packets"])
    except Exception:
        return None


def netem_apply(command):
    global _netem_applied
    with _netem_lock:
        if _netem_applied:
            return
        subprocess.run(["sudo", "-n", *command], check=True,
                       capture_output=True, text=True)
        _netem_applied = True


def netem_present():
    """Check lo for netem without sudo; fail closed if tc cannot be read."""
    try:
        out = subprocess.run(NETEM_SHOW_CMD, capture_output=True, text=True,
                             check=True).stdout
    except Exception as exc:
        log(f"WARNING: cannot verify netem state: {exc!r}")
        return True
    return "netem" in out


def _netem_clear_once():
    try:
        subprocess.run(NETEM_CLEAR_CMD, capture_output=True, text=True)
    except Exception as exc:
        log(f"WARNING: netem clear command failed: {exc!r}")


def netem_clear():
    """Clear netem, verify, and retry once.

    Returns True when the first clear left no netem, False when netem was
    still present after the first clear but the retry removed it, and raises
    NetemClearError (after setting the abort flag) when it remains.
    """
    global _netem_applied
    with _netem_lock:
        if not _netem_applied:
            return True
        _netem_clear_once()
        if not netem_present():
            _netem_applied = False
            return True
        log("ERROR: netem still present after clear; retrying once")
        _netem_clear_once()
        if not netem_present():
            _netem_applied = False
            return False
        _abort.set()
        raise NetemClearError("netem still present after retry")


def check_no_netem_before_run(run_id, scenario):
    """Abort the matrix rather than start a run over a leftover qdisc."""
    if netem_present():
        log(f"FATAL {run_id} ({scenario}): netem qdisc present before run; "
            "aborting matrix")
        _abort.set()
        return False
    return True


def install_signal_handlers():
    def handler(signum, frame):
        log(f"signal {signum} received — aborting")
        _abort.set()
        try:
            netem_clear()
        except Exception:
            pass
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, handler)


class Recorder:
    """In-memory logs; no file I/O inside MQTT callbacks."""

    def __init__(self):
        self.lock = threading.Lock()
        self.sent = []
        self.recv = []
        self.mid_map = {}
        self.orphan_acks = {}
        self.invalid_payloads = 0

    def register_sent(self, rec, mid):
        with self.lock:
            self.sent.append(rec)
            ack = self.orphan_acks.pop(mid, None)
            if ack is not None:
                rec["ack_ns"] = ack
            else:
                self.mid_map[mid] = rec

    def on_ack(self, mid):
        ts = time.monotonic_ns()
        with self.lock:
            rec = self.mid_map.pop(mid, None)
            if rec is not None:
                rec["ack_ns"] = ts
            else:
                self.orphan_acks[mid] = ts

    def record_recv(self, seq, t1):
        with self.lock:
            if seq is None:
                self.invalid_payloads += 1
            else:
                self.recv.append((int(seq), t1))

    def pending_acks(self):
        with self.lock:
            return len(self.mid_map)

    def snapshot(self):
        with self.lock:
            return list(self.sent), list(self.recv), self.invalid_payloads


class Publisher:
    def __init__(self, client_id, session_id, recorder, tcp_nodelay=False):
        self.client_id = client_id
        self.session_id = session_id
        self.recorder = recorder
        self.tcp_nodelay = tcp_nodelay
        self.client = None
        self.connected = threading.Event()
        self.disconnected = threading.Event()
        self.error = None
        self.stats = {"critical": 0, "important": 0, "normal": 0,
                      "background": 0, "total": 0}

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code.is_failure:
            self.error = str(reason_code)
        self.connected.set()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.disconnected.set()

    def _on_publish(self, client, userdata, mid, reason_code, properties=None):
        self.recorder.on_ack(mid)

    def connect(self):
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                        client_id=self.client_id, protocol=mqtt.MQTTv5)
        c.max_inflight_messages = MAX_INFLIGHT
        c.on_connect = self._on_connect
        c.on_disconnect = self._on_disconnect
        c.on_publish = self._on_publish
        props = Properties(PacketTypes.CONNECT)
        props.SessionExpiryInterval = SESSION_EXPIRY
        c.connect(BROKER_HOST, BROKER_PORT, keepalive=KEEPALIVE,
                  clean_start=True, properties=props)
        if self.tcp_nodelay:
            enable_tcp_nodelay(c)
        c.loop_start()
        if not self.connected.wait(timeout=10):
            raise RuntimeError("publisher CONNACK timeout")
        if self.error:
            raise RuntimeError(f"publisher connect failed: {self.error}")
        self.client = c

    def _qos(self, tier, experiment):
        if experiment == "A":
            return 0
        if experiment == "C":
            return 2
        return TIER_QOS[tier]

    def _topic(self, tier, experiment):
        return TOPIC_UNIFORM if experiment in ("A", "C") else TIER_TOPICS[tier]

    def _emit(self, seq, row, kind, tier, experiment, payload):
        qos = self._qos(tier, experiment)
        topic = self._topic(tier, experiment)
        t0 = time.monotonic_ns()
        info = self.client.publish(topic, payload, qos=qos)
        rec = {
            "seq": seq, "row": row, "kind": kind, "tier": tier, "qos": qos,
            "t0_ns": t0, "ack_ns": None, "warmup": 0,
        }
        self.recorder.register_sent(rec, info.mid)
        return rec

    def publish_reading(self, row, seq, experiment, warmup=False):
        tier = row["tier"]
        self.stats[tier.lower()] += 1
        self.stats["total"] += 1
        qos = self._qos(tier, experiment)
        topic = self._topic(tier, experiment)
        payload = json.dumps({
            "sessionId": self.session_id,
            "patientId": "patient-001",
            "seq": seq,
            "publishedAt": int(time.time() * 1000),
            "tier": tier,
            "spo2": round(row["spo2"], 1),
            "heartRate": round(row["hr"], 1),
            "hrv": round(row["hrv"], 1),
            "motion": round(row["motion"], 2),
            "timestamp": now_iso(),
            "reason": row["reason"],
            "qos": qos,
            "topic": topic,
            "stats": self.stats.copy(),
        })
        rec = self._emit(seq, row["row"], "reading", tier, experiment, payload)
        rec["warmup"] = 1 if warmup else 0
        return rec

    def publish_background(self, seq, experiment):
        tier = "Background"
        self.stats["background"] += 1
        qos = self._qos(tier, experiment)
        topic = self._topic(tier, experiment)
        payload = json.dumps({
            "sessionId": self.session_id,
            "patientId": "patient-001",
            "seq": seq,  # benchmark-only field, needed for log joinability
            "publishedAt": int(time.time() * 1000),
            "tier": tier,
            "spo2": 0, "heartRate": 0, "hrv": 0, "motion": 0,
            "timestamp": now_iso(),
            "reason": "Periodic session statistics",
            "qos": qos,
            "topic": topic,
            "stats": self.stats.copy(),
        })
        return self._emit(seq, None, "background", tier, experiment, payload)

    def teardown(self):
        if not self.client:
            return
        self.disconnected.clear()
        props = Properties(PacketTypes.DISCONNECT)
        props.SessionExpiryInterval = 0
        try:
            self.client.disconnect(properties=props)
        except Exception:
            pass
        self.disconnected.wait(timeout=1.5)
        try:
            self.client.loop_stop()
        except Exception:
            pass
        self.client = None


class Subscriber:
    def __init__(self, client_id, recorder, tcp_nodelay=False):
        self.client_id = client_id
        self.recorder = recorder
        self.tcp_nodelay = tcp_nodelay
        self.client = None
        self.connected = threading.Event()
        self.subscribed = threading.Event()
        self.disconnected = threading.Event()
        self.session_present = None
        self.error = None

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code.is_failure:
            self.error = str(reason_code)
            self.connected.set()
            return
        self.session_present = bool(getattr(flags, "session_present", False))
        self.connected.set()
        if not self.session_present:
            client.subscribe(TOPIC_FILTER, qos=2)

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties=None):
        self.subscribed.set()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self.disconnected.set()

    def _on_message(self, client, userdata, msg):
        t1 = time.monotonic_ns()
        try:
            seq = json.loads(msg.payload.decode()).get("seq")
        except Exception:
            seq = None
        self.recorder.record_recv(seq, t1)

    def connect(self, clean_start):
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                        client_id=self.client_id, protocol=mqtt.MQTTv5)
        c.max_inflight_messages = MAX_INFLIGHT
        c.on_connect = self._on_connect
        c.on_subscribe = self._on_subscribe
        c.on_disconnect = self._on_disconnect
        c.on_message = self._on_message
        props = Properties(PacketTypes.CONNECT)
        props.SessionExpiryInterval = SESSION_EXPIRY
        c.connect(BROKER_HOST, BROKER_PORT, keepalive=KEEPALIVE,
                  clean_start=clean_start, properties=props)
        if self.tcp_nodelay:
            enable_tcp_nodelay(c)
        c.loop_start()
        self.client = c
        if not self.connected.wait(timeout=10):
            raise RuntimeError("subscriber CONNACK timeout")
        if self.error:
            raise RuntimeError(f"subscriber connect failed: {self.error}")
        if not self.session_present and not self.subscribed.wait(timeout=10):
            raise RuntimeError("subscriber SUBACK timeout")
        return self.session_present

    def disconnect_keep_session(self):
        """Normal DISCONNECT: the session survives and queues QoS 1/2."""
        if not self.client:
            return
        self.disconnected.clear()
        self.client.disconnect()
        self.disconnected.wait(timeout=2)
        self.client.loop_stop()

    def teardown(self):
        """DISCONNECT with SessionExpiryInterval=0: broker drops the session now."""
        if not self.client:
            return
        self.disconnected.clear()
        props = Properties(PacketTypes.DISCONNECT)
        props.SessionExpiryInterval = 0
        try:
            self.client.disconnect(properties=props)
        except Exception:
            pass
        self.disconnected.wait(timeout=1.5)
        try:
            self.client.loop_stop()
        except Exception:
            pass
        self.client = None


class SysWatcher:
    """Reads $SYS broker counters; non-persistent (clean start, expiry 0)."""

    def __init__(self):
        self.client = None
        self.connected = threading.Event()
        self.lock = threading.Lock()
        self.samples = []          # (monotonic_ns, topic, value)
        self.version = None
        self.baseline = None

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code.is_failure:
            return
        self.connected.set()
        for topic in ("$SYS/broker/clients/inactive",
                      "$SYS/broker/clients/connected",
                      "$SYS/broker/version"):
            client.subscribe(topic, qos=0)

    def _on_message(self, client, userdata, msg):
        ts = time.monotonic_ns()
        value = msg.payload.decode(errors="replace")
        with self.lock:
            self.samples.append((ts, msg.topic, value))
            if msg.topic == "$SYS/broker/version":
                self.version = value

    def start(self):
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                        client_id=f"bench-sys-{uuid.uuid4().hex[:8]}",
                        protocol=mqtt.MQTTv5)
        c.on_connect = self._on_connect
        c.on_message = self._on_message
        props = Properties(PacketTypes.CONNECT)
        props.SessionExpiryInterval = 0
        c.connect(BROKER_HOST, BROKER_PORT, keepalive=KEEPALIVE,
                  clean_start=True, properties=props)
        c.loop_start()
        self.client = c
        if not self.connected.wait(timeout=10):
            raise RuntimeError("$SYS watcher CONNACK timeout")

    def _latest(self, topic, after_ns=None):
        with self.lock:
            for ts, t, value in reversed(self.samples):
                if t != topic:
                    continue
                if after_ns is not None and ts < after_ns:
                    continue
                return ts, value
        return None

    def wait_baseline(self, timeout=12):
        wait_until(lambda: self._latest("$SYS/broker/clients/inactive") is not None,
                   timeout, "first $SYS inactive sample")
        wait_until(lambda: self.version is not None, 2, "$SYS broker version")
        sample = self._latest("$SYS/broker/clients/inactive")
        if sample:
            try:
                self.baseline = int(sample[1])
            except ValueError:
                self.baseline = None
        return self.baseline

    def check_inactive(self, after_ns, timeout=2.0):
        """Compare the latest inactive-session count with the matrix baseline.

        Mosquitto publishes $SYS counters on change (and retains the last value),
        so waiting for a periodic sample is wrong. Wait briefly for a post-teardown
        change, then fall back to the latest retained value. If a session leaked,
        the count changes and a fresh sample appears inside the grace window.
        """
        deadline = time.monotonic() + timeout
        fresh = False
        while time.monotonic() < deadline:
            if _abort.is_set():
                raise Aborted()
            if self._latest("$SYS/broker/clients/inactive", after_ns) is not None:
                fresh = True
                break
            time.sleep(0.05)
        sample = self._latest("$SYS/broker/clients/inactive")
        if not sample:
            return None, self.baseline, False, False
        try:
            value = int(sample[1])
        except ValueError:
            return None, self.baseline, False, fresh
        warned = self.baseline is not None and value > self.baseline
        return value, self.baseline, warned, fresh

    def stop(self):
        if not self.client:
            return
        try:
            props = Properties(PacketTypes.DISCONNECT)
            props.SessionExpiryInterval = 0
            self.client.disconnect(properties=props)
        except Exception:
            pass
        try:
            self.client.loop_stop()
        except Exception:
            pass
        self.client = None


class SudoKeepalive(threading.Thread):
    """Refresh the sudo timestamp during long matrices (default timeout 15 min)."""

    def __init__(self):
        super().__init__(daemon=True)
        self.stop_flag = threading.Event()

    def run(self):
        while not self.stop_flag.wait(240):
            rc = subprocess.run(["sudo", "-n", "-v"],
                                capture_output=True).returncode
            if rc != 0:
                log("WARNING: sudo timestamp refresh failed — "
                    "later netem runs may fail")

    def stop(self):
        self.stop_flag.set()


# ── Broker / git / config description ─────────────────────────

def broker_config():
    cfg_dir = Path("/etc/mosquitto")
    pattern = "queue_qos0|max_queued|max_inflight|persistence|per_listener"
    raw = ""
    try:
        raw = subprocess.run(["grep", "-rEn", pattern, str(cfg_dir)],
                             capture_output=True, text=True).stdout.strip()
    except Exception as exc:
        raw = f"(grep failed: {exc})"
    effective = dict(BROKER_DEFAULTS)
    active_lines = []
    try:
        for path in sorted(cfg_dir.rglob("*.conf")):
            for line in path.read_text(errors="replace").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                parts = stripped.split(None, 1)
                if not parts:
                    continue
                key, value = parts[0], (parts[1] if len(parts) > 1 else "")
                if key in BROKER_RELEVANT:
                    active_lines.append(f"{path}: {stripped}")
                    if key == "persistence":
                        effective[key] = value.lower() == "true"
                    elif key in ("max_queued_messages", "max_inflight_messages"):
                        effective[key] = int(value)
                    elif key == "queue_qos0_messages":
                        effective[key] = value.lower() == "true"
                    elif key == "per_listener_settings":
                        effective[key] = value.lower() == "true"
    except Exception as exc:
        active_lines.append(f"(parse failed: {exc})")
    try:
        version = subprocess.run(["dpkg-query", "-W", "-f=${Version}", "mosquitto"],
                                 capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        version = "unknown"
    return {
        "version": version or "unknown",
        "config_dir": str(cfg_dir),
        "raw_grep": raw,
        "active_lines": active_lines,
        "resolved": effective,
        "defaults_note": ("Mosquitto 2.x defaults are used where no active "
                          "directive overrides them."),
    }


def git_info():
    def run(*args):
        try:
            return subprocess.run(["git", "-C", str(ROOT), *args],
                                  capture_output=True, text=True).stdout.strip()
        except Exception:
            return ""
    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(run("status", "--porcelain")),
        "note": "informational only — deliberately excluded from config_hash",
    }


def env_info():
    import platform
    return {
        "hostname": socket.gethostname(),
        "kernel": platform.release(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "paho_mqtt": paho_version(),
        "pandas": pd.__version__,
    }


def build_config(args, rows, broker):
    return {
        "method_version": METHOD_VERSION,
        "runner_sha256": sha256_file(Path(__file__)),
        "dataset_sha256": sha256_file(DATASET_PATH),
        "classifier_sha256": sha256_file(CLASSIFIER_PATH),
        "dataset_rows": len(rows),
        "pacing_interval_s": args.interval,
        "socketpair": args.socketpair,
        "paho_mqtt": paho_version(),
        "tcp_nodelay": bool(args.tcp_nodelay),
        "idle_max_pps": args.idle_max_pps,
        "warmup_rows": WARMUP_ROWS,
        "background_every": BACKGROUND_EVERY,
        "tier_qos": TIER_QOS,
        "netem": args.netem_string if "netem" in args.scenario_list else None,
        "outage_seconds": args.outage_seconds,
        "outage_fractions": args.outage_fractions,
        "mqtt": MQTT_SETTINGS,
        "broker": {"version": broker["version"], "resolved": broker["resolved"]},
    }


def config_hash(config):
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def load_rows(limit):
    actual = sha256_file(DATASET_PATH)
    if actual != EXPECTED_DATASET_SHA256:
        raise SystemExit(
            f"dataset hash mismatch: {DATASET_PATH}\n"
            f"  expected {EXPECTED_DATASET_SHA256}\n  actual   {actual}\n"
            "The frozen methodology requires this exact file; restore it or "
            "update the constant deliberately.")
    df = pd.read_csv(DATASET_PATH).head(limit)
    rows = []
    for idx, row in df.iterrows():
        spo2 = float(row.get("bo", row.get("spo2", 97)))
        hr = float(row.get("hr", row.get("heart_rate", 60)))
        hrv = float(row.get("hrv", 35))
        motion = float(row.get("lm", row.get("motion", 0)))
        tier, reason, _ = classify(spo2, hr, hrv, motion)
        rows.append({"row": int(idx), "spo2": spo2, "hr": hr, "hrv": hrv,
                     "motion": motion, "tier": tier, "reason": reason})
    return rows


def audit_windows(rows, interval, outage_seconds, fractions):
    span = max(1, round(outage_seconds / interval))
    table = []
    for frac in fractions:
        start = min(max(round(frac * len(rows)), 0), len(rows) - 1)
        window = rows[start:start + span]
        counts = Counter(r["tier"] for r in window)
        table.append({
            "fraction": frac, "start_row": start, "span_messages": span,
            "critical": counts.get("Critical", 0),
            "important": counts.get("Important", 0),
            "normal": counts.get("Normal", 0),
        })
    crits = [Counter(r["tier"] for r in rows[i:i + span]).get("Critical", 0)
             for i in range(0, max(1, len(rows) - span + 1))]
    summary = {
        "window_messages": span,
        "critical_per_window_min": min(crits) if crits else 0,
        "critical_per_window_max": max(crits) if crits else 0,
        "critical_per_window_mean": round(sum(crits) / len(crits), 2) if crits else 0,
        "zero_critical_windows": sum(1 for c in crits if c == 0),
        "windows_total": len(crits),
        "table": table,
        "note": ("Counts cover readings only; the live outage window also "
                 "contains background-stat messages (~1 per 10 readings)."),
    }
    return summary


def print_audit(summary):
    print("\nOutage-window audit (deterministic dataset)")
    print(f"  window = {summary['window_messages']} readings")
    for row in summary["table"]:
        print(f"  {row['fraction']:.0%}: rows {row['start_row']}.."
              f"{row['start_row'] + row['span_messages'] - 1} -> Critical "
              f"{row['critical']}, Important {row['important']}, Normal {row['normal']}")
    print(f"  across all windows: critical {summary['critical_per_window_min']}.."
          f"{summary['critical_per_window_max']} (mean "
          f"{summary['critical_per_window_mean']}); zero-critical windows "
          f"{summary['zero_critical_windows']}/{summary['windows_total']}\n")


# ── Preflight / atomic output ──────────────────────────────────

def preflight(args):
    problems = []
    idle = None
    try:
        socket.create_connection((BROKER_HOST, BROKER_PORT), timeout=3).close()
    except OSError as exc:
        problems.append(f"broker {BROKER_HOST}:{BROKER_PORT} not reachable ({exc})")
    try:
        out = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}|{{.Image}}|{{.Ports}}"],
            capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            name, _, rest = line.partition("|")
            image, _, ports = rest.partition("|")
            if ("mosquitto" in image.lower() or "mqtt" in image.lower()
                    or "1883" in ports):
                problems.append(f"MQTT looks containerised: {line}")
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    try:
        qdisc = subprocess.run(["tc", "qdisc", "show", "dev", "lo"],
                               capture_output=True, text=True)
    except FileNotFoundError:
        return problems + ["tc not found; cannot verify or apply netem"], idle
    if "netem" in qdisc.stdout:
        log("leftover netem on lo — attempting removal")
        subprocess.run(["sudo", "-n", "tc", "qdisc", "del", "dev", "lo", "root"],
                       capture_output=True, text=True)
        qdisc = subprocess.run(["tc", "qdisc", "show", "dev", "lo"],
                               capture_output=True, text=True)
        if "netem" in qdisc.stdout:
            problems.append("leftover netem qdisc could not be removed")
    if "netem" in args.scenario_list:
        if subprocess.run(["sudo", "-n", "tc", "qdisc", "show", "dev", "lo"],
                          capture_output=True).returncode != 0:
            log("netem requested — requesting sudo (one prompt)")
            if subprocess.run(["sudo", "-v"]).returncode != 0:
                problems.append("sudo unavailable; netem scenarios cannot run")

    idle = sample_lo_idle(PREFLIGHT_LO_SECONDS, args.idle_max_pps)
    if idle.get("error"):
        problems.append(f"preflight idle check: {idle['error']}")
    else:
        log(f"preflight idle: {idle['tx_packets']} lo TX packets in "
            f"{idle['seconds']:.1f}s = {idle['packets_per_s']:.2f} pkt/s "
            f"(threshold {idle['max_pps']} pps)")
        if idle.get("flagged"):
            problems.append(
                f"background loopback traffic: {idle['packets_per_s']:.2f} pkt/s "
                f"exceeds {idle['max_pps']} pps")
    return problems, idle


def atomic_write_text(path, text):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def write_csv(path, fields, rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    atomic_write_text(path, buf.getvalue())


def write_json(path, obj):
    atomic_write_text(path, json.dumps(obj, indent=2, sort_keys=True))


def run_paths(out_dir, run_id):
    return (out_dir / f"sent_{run_id}.csv",
            out_dir / f"recv_{run_id}.csv",
            out_dir / f"meta_{run_id}.json")


# ── One run ────────────────────────────────────────────────────

def run_single(spec, rows, args, cfg_hash, config, broker, sysw, out_dir, idle):
    run_id = spec.run_id
    started = datetime.now(timezone.utc).isoformat()
    recorder = Recorder()
    session_id = f"bench-{run_id}"
    subscriber = Subscriber(f"bench-sub-{run_id}", recorder,
                            tcp_nodelay=args.tcp_nodelay)
    publisher = Publisher(f"bench-pub-{run_id}", session_id, recorder,
                          tcp_nodelay=args.tcp_nodelay)
    holder = {"sub": subscriber}
    counter = {"n": 0}

    def next_seq():
        value = counter["n"]
        counter["n"] += 1
        return value

    netem_on = spec.scenario == "netem"
    interval_ns = int(args.interval * 1e9)
    outage = {"fraction": spec.position, "trigger_row": None, "t_off_ns": None,
              "t_on_ns": None, "session_present": None, "error": None}
    status, error = "complete", None
    wire_before = wire_after = None
    wire_started = None
    drain = {}
    syscheck = {}
    teardown_ns = None
    idle = idle if idle is not None else {}

    try:
        if netem_on:
            netem_apply(args.netem_cmd)
            time.sleep(0.3)
        holder["sub"].connect(clean_start=True)
        publisher.connect()

        t_warm = time.monotonic_ns()
        for i in range(min(WARMUP_ROWS, len(rows))):
            sleep_until(t_warm + i * interval_ns)
            publisher.publish_reading(rows[i], next_seq(), spec.experiment,
                                      warmup=True)
        time.sleep(0.2)

        trigger = threading.Event()
        done = threading.Event()
        disconnected = threading.Event()
        trigger_row = None
        if spec.position is not None:
            trigger_row = max(1, min(len(rows) - 1,
                                     round(spec.position * len(rows))))
            outage["trigger_row"] = trigger_row

            def outage_worker():
                trigger.wait()
                outage["t_off_ns"] = time.monotonic_ns()
                try:
                    try:
                        holder["sub"].disconnect_keep_session()
                    finally:
                        disconnected.set()
                    time.sleep(args.outage_seconds)
                    fresh = Subscriber(f"bench-sub-{run_id}", recorder,
                                       tcp_nodelay=args.tcp_nodelay)
                    outage["session_present"] = fresh.connect(clean_start=False)
                    holder["sub"] = fresh
                except Exception as exc:  # capture, do not kill the publisher
                    outage["error"] = repr(exc)
                finally:
                    outage["t_on_ns"] = time.monotonic_ns()
                    done.set()

            threading.Thread(target=outage_worker, daemon=True).start()

        wire_started = time.monotonic()
        wire_before = read_lo_tx()
        t_measured = time.monotonic_ns()
        for i, row in enumerate(rows):
            if _abort.is_set():
                raise Aborted()
            if trigger_row is not None and i == trigger_row:
                # Disconnect before the first message of the audited window, so
                # rows trigger_row..trigger_row+span-1 are the affected ones.
                trigger.set()
                if not disconnected.wait(timeout=5):
                    log(f"WARNING {run_id}: subscriber did not disconnect in time")
            sleep_until(t_measured + i * interval_ns)
            publisher.publish_reading(row, next_seq(), spec.experiment)
            if (i + 1) % BACKGROUND_EVERY == 0:
                publisher.publish_background(next_seq(), spec.experiment)
        if trigger_row is not None:
            trigger.set()
            done.wait(timeout=max(15, args.outage_seconds + 10))

        t_drain = time.monotonic()
        wait_until(lambda: recorder.pending_acks() == 0, 30, "outstanding acks")
        pending_left = recorder.pending_acks()
        sent_now, _, _ = recorder.snapshot()
        t_off, t_on = outage["t_off_ns"], outage["t_on_ns"]
        lost_in_window = 0
        if t_off and t_on:
            lost_in_window = sum(
                1 for r in sent_now
                if r["warmup"] == 0 and r["qos"] == 0
                and t_off <= r["t0_ns"] <= t_on)
        measured_sent = sum(1 for r in sent_now if r["warmup"] == 0)
        measured_seqs_now = {r["seq"] for r in sent_now if r["warmup"] == 0}
        expected = measured_sent - lost_in_window
        boundary_tolerance = 2  # async DISCONNECT can lose a QoS 0 just before t_off
        expected_min = max(0, expected - boundary_tolerance)
        wait_until(
            lambda: len({s for s, _ in recorder.snapshot()[1]
                         if s in measured_seqs_now}) >= expected_min,
            25, "expected deliveries")
        quiet = QUIET_NETEM if netem_on else QUIET_CLEAN
        time.sleep(quiet)
        wire_after = read_lo_tx()
        drain = {
            "seconds": round(time.monotonic() - t_drain, 2),
            "pending_acks_left": pending_left,
            "measured_sent": measured_sent,
            "qos0_lost_in_outage_window": lost_in_window,
            "expected_received": expected,
            "expected_received_min": expected_min,
            "quiet_seconds": quiet,
        }
    except Aborted:
        status, error = "aborted", "aborted by signal"
    except Exception as exc:
        status, error = "failed", repr(exc)
    finally:
        try:
            holder["sub"].teardown()
        except Exception:
            pass
        try:
            publisher.teardown()
        except Exception:
            pass
        if netem_on:
            try:
                first_clear_clean = netem_clear()
                if first_clear_clean is False:
                    status = "failed"
                    msg = ("netem present after first clear; retry succeeded "
                           "— run discarded")
                    error = f"{error}; {msg}" if error else msg
            except NetemClearError as exc:
                status = "failed"
                msg = f"netem still present after retry: {exc}"
                error = f"{error}; {msg}" if error else msg
            except Exception as exc:
                status = "failed"
                msg = f"netem clear failed: {exc!r}"
                error = f"{error}; {msg}" if error else msg
                _abort.set()
        teardown_ns = time.monotonic_ns()

    if status == "complete" and sysw is not None:
        try:
            value, baseline, warned, fresh = sysw.check_inactive(teardown_ns, timeout=2.0)
            syscheck = {"inactive": value, "baseline": baseline,
                        "warned": warned, "fresh_sample": fresh}
            if warned:
                log(f"WARNING {run_id}: $SYS inactive {value} > baseline {baseline}")
        except Aborted:
            pass

    sent, received, invalid_payloads = recorder.snapshot()
    recv_unique = len({seq for seq, _ in received})
    measured_seqs = {r["seq"] for r in sent if r["warmup"] == 0}
    recv_unique_measured = len({seq for seq, _ in received if seq in measured_seqs})
    sent_measured = sum(1 for r in sent if r["warmup"] == 0)
    reading_t0 = [r["t0_ns"] for r in sent
                  if r["warmup"] == 0 and r["kind"] == "reading"]
    intervals = [(b - a) / 1e6 for a, b in zip(reading_t0, reading_t0[1:])]
    wire = None
    if wire_before and wire_after and sent_measured:
        db = wire_after[0] - wire_before[0]
        dp = wire_after[1] - wire_before[1]
        wire_seconds = (time.monotonic() - wire_started
                        if wire_started is not None else None)
        idle_pkt_s = idle.get("packets_per_s") or 0.0
        idle_B_s = idle.get("bytes_per_s") or 0.0
        corrected_bytes = max(0, round(db - idle_B_s * (wire_seconds or 0)))
        corrected_packets = max(0, round(dp - idle_pkt_s * (wire_seconds or 0)))
        wire = {
            "tx_bytes": db, "tx_packets": dp,
            "seconds": round(wire_seconds, 3) if wire_seconds is not None else None,
            "bytes_per_msg": round(db / sent_measured, 2),
            "packets_per_msg": round(dp / sent_measured, 2),
            "raw_bytes_per_msg": round(db / sent_measured, 2),
            "raw_packets_per_msg": round(dp / sent_measured, 2),
            "corrected_tx_bytes": corrected_bytes,
            "corrected_tx_packets": corrected_packets,
            "corrected_bytes_per_msg": round(corrected_bytes / sent_measured, 2),
            "corrected_packets_per_msg": round(corrected_packets / sent_measured, 2),
            "idle_packets_per_s": idle_pkt_s,
            "idle_bytes_per_s": idle_B_s,
            "idle_max_pps": args.idle_max_pps,
            "idle_flagged": idle.get("flagged"),
            # Corrected counters are diagnostic only. A flagged run must be
            # deleted and rerun; analysis hard-fails while it remains.
            "primary": "raw",
            "messages": sent_measured,
        }

    sent_rows = [{
        "run_id": run_id, "experiment": spec.experiment,
        "scenario": spec.scenario,
        "position": "" if spec.position is None else spec.position,
        "rep": spec.rep, "seq": r["seq"],
        "row": "" if r["row"] is None else r["row"],
        "kind": r["kind"], "tier": r["tier"], "qos": r["qos"],
        "t0_ns": r["t0_ns"],
        "ack_ns": "" if r["ack_ns"] is None else r["ack_ns"],
        "warmup": r["warmup"],
    } for r in sent]
    recv_rows = [{"run_id": run_id, "seq": seq, "t1_ns": t1}
                 for seq, t1 in received]

    meta = {
        "run_id": run_id, "study": args.study,
        "seed": args.seed,
        "experiment": spec.experiment, "scenario": spec.scenario,
        "position": spec.position, "rep": spec.rep,
        "quick": bool(args.quick), "status": status, "error": error,
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "idle_max_pps": args.idle_max_pps,
        "config_hash": cfg_hash, "config": config,
        "dataset": {"path": str(DATASET_PATH),
                    "sha256": config["dataset_sha256"],
                    "rows": len(rows)},
        "classifier_sha256": config["classifier_sha256"],
        "netem": {"applied": netem_on, "command": args.netem_string if netem_on else None},
        "idle": idle,
        "pacing": {
            "interval_s": args.interval,
            "mean_interval_ms": round(sum(intervals) / len(intervals), 3) if intervals else None,
            "warmup_rows": WARMUP_ROWS,
            "measured_readings": len(reading_t0),
            "background_messages": sum(1 for r in sent if r["kind"] == "background"),
        },
        "counts": {"sent_total": len(sent), "sent_measured": sent_measured,
                   "recv_raw": len(received), "recv_unique": recv_unique,
                   "recv_unique_measured": recv_unique_measured,
                   "duplicates": len(received) - recv_unique,
                   "invalid_payloads": invalid_payloads},
        "outage": outage, "drain": drain, "wire": wire, "sys": syscheck,
        "mqtt": MQTT_SETTINGS, "broker": broker,
        "analysis_sha256": (sha256_file(ANALYSIS_PATH)
                            if ANALYSIS_PATH.exists() else None),
        "git": git_info(), "env": env_info(),
    }

    sent_path, recv_path, meta_path = run_paths(out_dir, run_id)
    write_csv(sent_path, SENT_FIELDS, sent_rows)
    write_csv(recv_path, RECV_FIELDS, recv_rows)
    write_json(meta_path, meta)
    return meta


# ── Plan / resume / CLI ────────────────────────────────────────

@dataclass
class RunSpec:
    run_id: str
    experiment: str
    scenario: str
    position: float | None
    rep: int


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Single-clock MQTT QoS benchmark (Expo publisher model).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--experiments", default="A,B,C",
                        help="comma list from A (all QoS 0), B (tiered), C (all QoS 2)")
    parser.add_argument("--scenarios", default=None,
                        help="comma list from clean,netem,outage")
    parser.add_argument("--reps", type=int, default=None)
    parser.add_argument("--interval", type=float, default=None,
                        help="publish interval in seconds")
    parser.add_argument("--rows", type=int, default=None,
                        help="number of dataset rows to publish")
    parser.add_argument("--outage-seconds", type=float, default=OUTAGE_SECONDS)
    parser.add_argument("--outage-fractions", default="0.25,0.5,0.75")
    parser.add_argument("--socketpair", choices=[SOCKETPAIR_STOCK, SOCKETPAIR_AF_UNIX],
                        default=SOCKETPAIR_AF_UNIX,
                        help="paho cross-thread wake-up socketpair implementation")
    parser.add_argument("--tcp-nodelay", action="store_true",
                        help="set TCP_NODELAY on both benchmark clients (client-side only)")
    parser.add_argument("--netem-delay-only", action="store_true",
                        help="use delay/jitter only (no loss) for calibration")
    parser.add_argument("--idle-max-pps", type=float, default=None,
                        help="max idle lo TX packets/second; required for "
                             "main and sensitivity matrices")
    parser.add_argument("--out-dir", default=None,
                        help="override the study output directory")
    parser.add_argument("--quick", action="store_true",
                        help="smoke test into benchmark/results_quick_v2 (refused by analysis)")
    parser.add_argument("--sensitivity", action="store_true",
                        help="1 msg/s pacing study into benchmark/results_v2_sensitivity")
    parser.add_argument("--calibration", action="store_true",
                        help="calibration mode: idle threshold may be omitted")
    parser.add_argument("--force", action="store_true",
                        help="rerun every planned run, even complete ones")
    parser.add_argument("--audit-windows", action="store_true",
                        help="print the deterministic outage-window audit and exit")
    parser.add_argument("--seed", type=int, default=42,
                        help="recorded for reproducibility; dataset order is fixed")
    args = parser.parse_args(argv)
    args.netem_cmd = NETEM_DELAY_ONLY_CMD if args.netem_delay_only else NETEM_CMD
    args.netem_string = (NETEM_DELAY_ONLY_STRING if args.netem_delay_only
                         else NETEM_STRING)

    if sum((args.quick, args.sensitivity, args.calibration)) > 1:
        parser.error("--quick, --sensitivity and --calibration are mutually exclusive")

    if args.quick:
        args.study = "quick"
        default_out = BENCH_DIR / "results_quick_v2"
        defaults = {"rows": QUICK_ROWS, "reps": 1, "scenarios": "clean",
                    "interval": DEFAULT_INTERVAL}
    elif args.sensitivity:
        args.study = "sensitivity"
        default_out = BENCH_DIR / "results_v2_sensitivity"
        defaults = {"rows": SENS_ROWS, "reps": 2, "scenarios": "clean,netem",
                    "interval": SENS_INTERVAL}
    elif args.calibration:
        args.study = "calibration"
        default_out = BENCH_DIR / "calibration_v2"
        defaults = {"rows": FULL_ROWS, "reps": 5, "scenarios": "clean,netem,outage",
                    "interval": DEFAULT_INTERVAL}
    else:
        args.study = "main"
        default_out = BENCH_DIR / "results_v2"
        defaults = {"rows": FULL_ROWS, "reps": 5, "scenarios": "clean,netem,outage",
                    "interval": DEFAULT_INTERVAL}
    args.out_dir = Path(args.out_dir) if args.out_dir else default_out

    args.rows = defaults["rows"] if args.rows is None else args.rows
    args.reps = defaults["reps"] if args.reps is None else args.reps
    args.interval = defaults["interval"] if args.interval is None else args.interval
    scenarios = defaults["scenarios"] if args.scenarios is None else args.scenarios
    args.scenario_list = [s.strip() for s in scenarios.split(",") if s.strip()]
    args.experiment_list = [e.strip().upper() for e in args.experiments.split(",") if e.strip()]
    args.outage_fractions = [float(f) for f in args.outage_fractions.split(",") if f.strip()]

    if not set(args.scenario_list) <= {"clean", "netem", "outage"}:
        parser.error(f"unknown scenario in {args.scenario_list}")
    if not set(args.experiment_list) <= {"A", "B", "C"}:
        parser.error(f"unknown experiment in {args.experiment_list}")
    if not (0 < args.interval <= 5):
        parser.error("--interval must be in (0, 5] seconds")
    if args.rows < WARMUP_ROWS + 1 or args.rows > FULL_ROWS:
        parser.error(f"--rows must be between {WARMUP_ROWS + 1} and {FULL_ROWS}")
    if args.reps < 1:
        parser.error("--reps must be >= 1")
    if args.idle_max_pps is not None and args.idle_max_pps < 0:
        parser.error("--idle-max-pps must be >= 0")
    if (args.idle_max_pps is None
            and not (args.quick or args.calibration or args.audit_windows)):
        parser.error("--idle-max-pps is required for main/sensitivity matrices")
    if any(not (0.05 <= f <= 0.95) for f in args.outage_fractions):
        parser.error("--outage-fractions entries must be in [0.05, 0.95]")
    return args


def build_plan(experiments, scenarios, fractions, reps):
    conditions = []
    if "clean" in scenarios:
        conditions.append(("clean", None))
    if "netem" in scenarios:
        conditions.append(("netem", None))
    if "outage" in scenarios:
        for frac in fractions:
            conditions.append((f"outage-p{int(round(frac * 100)):02d}", frac))
    plan = []
    for rep in range(1, reps + 1):
        exp_offset = (rep - 1) % len(experiments)
        exp_order = experiments[exp_offset:] + experiments[:exp_offset]
        cond_offset = (rep - 1) % len(conditions)
        cond_order = conditions[cond_offset:] + conditions[:cond_offset]
        for condition, position in cond_order:
            for experiment in exp_order:
                scenario = condition.split("-")[0]
                run_id = f"{experiment}-{condition}-r{rep:02d}"
                plan.append(RunSpec(run_id, experiment, scenario, position, rep))
    return plan


def scan_existing(out_dir, cfg_hash):
    complete, mismatched = {}, []
    for meta_path in sorted(out_dir.glob("meta_*.json")):
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            continue
        run_id = meta.get("run_id")
        if not run_id:
            continue
        if meta.get("status") == "complete":
            sent_path, recv_path, _ = run_paths(out_dir, run_id)
            if not sent_path.exists() or not recv_path.exists():
                continue  # complete meta without logs: rerun
            if meta.get("config_hash") == cfg_hash:
                complete[run_id] = meta
            else:
                mismatched.append(run_id)
    return complete, mismatched


def main(argv=None):
    args = parse_args(argv)
    if paho_version() == "unknown":
        log("FATAL: cannot determine paho-mqtt version; refusing v2 run")
        return 2
    install_socketpair(args.socketpair)
    install_signal_handlers()
    random.seed(args.seed)
    rows = load_rows(args.rows)
    audit = audit_windows(rows, args.interval, args.outage_seconds,
                          args.outage_fractions)
    if args.audit_windows:
        print_audit(audit)
        return 0
    if "outage" in args.scenario_list:
        print_audit(audit)

    problems, preflight_idle = preflight(args)
    if problems:
        for problem in problems:
            log(f"PREFLIGHT FAIL: {problem}")
        return 2

    broker = broker_config()
    config = build_config(args, rows, broker)
    cfg_hash = config_hash(config)
    plan = build_plan(args.experiment_list, args.scenario_list,
                      args.outage_fractions, args.reps)
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    if "outage" in args.scenario_list:
        write_json(out_dir / "window_audit.json",
                   {**audit, "rows": args.rows, "interval_s": args.interval,
                    "outage_seconds": args.outage_seconds})

    expected_rows = args.rows
    if len(rows) != expected_rows:
        log(f"FATAL: dataset has {len(rows)} rows, expected {expected_rows}")
        return 2

    complete, mismatched = scan_existing(out_dir, cfg_hash)
    planned_ids = {spec.run_id for spec in plan}
    stale = [rid for rid in mismatched if rid not in planned_ids]
    if mismatched and not args.force:
        log("refusing to mix methodologies: complete runs use a different config_hash")
        for rid in mismatched:
            log(f"  mismatched: {rid}")
        log("rerun with --force to overwrite planned runs, or move the old files away")
        return 3
    if stale:
        log(f"WARNING: {len(stale)} mismatched run(s) outside the current plan remain "
            f"in {out_dir}: {', '.join(sorted(stale))}")

    matrix = {
        "study": args.study,
        "config_hash": cfg_hash,
        "config": config,
        "broker": broker,
        "env": env_info(),
        "git": git_info(),
        "audit": audit,
        "preflight": {"idle": preflight_idle},
        "idle_max_pps": args.idle_max_pps,
        "plan": [{"run_id": s.run_id, "experiment": s.experiment,
                  "scenario": s.scenario, "position": s.position,
                  "rep": s.rep} for s in plan],
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "sys_baseline_inactive": None,
        "broker_sys_version": None,
        "status": "running",
    }

    log(f"study={args.study}  runs={len(plan)}  rows/run={args.rows}  "
        f"interval={args.interval}s  out={out_dir}")
    log(f"config_hash={cfg_hash[:16]}  broker={broker['version']}  "
        f"dataset_sha={config['dataset_sha256'][:12]}")

    sudo_keepalive = SudoKeepalive() if "netem" in args.scenario_list else None
    if sudo_keepalive:
        sudo_keepalive.start()
    write_json(out_dir / "matrix.json", matrix)

    counts = Counter()
    failures = []
    skipped = 0
    sysw = None
    sys_baseline_recorded = False
    try:
        for index, spec in enumerate(plan, 1):
            if _abort.is_set():
                break
            if not args.force and spec.run_id in complete and spec.run_id not in mismatched:
                skipped += 1
                log(f"[{index}/{len(plan)}] skip {spec.run_id} (complete, same config)")
                continue
            if not check_no_netem_before_run(spec.run_id, spec.scenario):
                break
            for path in run_paths(out_dir, spec.run_id):
                if path.exists():
                    path.unlink()
            log(f"[{index}/{len(plan)}] {spec.run_id}  scenario={spec.scenario} "
                f"rep={spec.rep} interval={args.interval}s")
            before = time.monotonic()

            # The previous run has returned: clients are torn down, netem is
            # cleared and the $SYS watcher is stopped. Sample before the next
            # watcher and before any client connects or netem is applied.
            idle = sample_lo_idle(RUN_IDLE_SECONDS, args.idle_max_pps)
            if idle.get("error"):
                log(f"WARNING {spec.run_id}: idle sample failed: {idle['error']}")
            elif idle.get("flagged"):
                log(f"WARNING {spec.run_id}: idle lo traffic "
                    f"{idle['packets_per_s']:.2f} pkt/s exceeds "
                    f"{idle['max_pps']} pps; run flagged, delete and rerun")

            sysw = SysWatcher()
            try:
                sysw.start()
                baseline = sysw.wait_baseline(timeout=12)
                log(f"$SYS baseline inactive sessions = {baseline}")
                if not sys_baseline_recorded:
                    matrix["sys_baseline_inactive"] = baseline
                    matrix["broker_sys_version"] = sysw.version
                    sys_baseline_recorded = True
                    write_json(out_dir / "matrix.json", matrix)
            except Exception as exc:
                log(f"WARNING: $SYS watcher disabled ({exc!r})")
                try:
                    sysw.stop()
                except Exception:
                    pass
                sysw = None

            try:
                meta = run_single(spec, rows, args, cfg_hash, config, broker,
                                  sysw, out_dir, idle)
                counts[meta["status"]] += 1
                elapsed = time.monotonic() - before
                if meta["status"] == "complete":
                    log(f"    done in {elapsed:.1f}s  "
                        f"unique_recv={meta['counts']['recv_unique_measured']} "
                        f"sent={meta['counts']['sent_measured']} "
                        f"wire={meta.get('wire', {}).get('bytes_per_msg')} B/msg")
                else:
                    failures.append(spec.run_id)
                    log(f"    ended {meta['status']}: {meta.get('error')}")
            except Aborted:
                log("aborted by signal")
                break
            finally:
                if sysw:
                    sysw.stop()
                    sysw = None
    finally:
        if sudo_keepalive:
            sudo_keepalive.stop()
        if sysw:
            sysw.stop()
        matrix["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        matrix["completed_runs"] = dict(counts)
        matrix["failed_runs"] = failures
        matrix["status"] = ("aborted" if _abort.is_set()
                            else "complete" if not failures else "complete_with_failures")
        try:
            write_json(out_dir / "matrix.json", matrix)
        except Exception as exc:
            log(f"could not update matrix.json: {exc!r}")

    log(f"matrix finished: completed={dict(counts)} skipped={skipped} "
        f"failed={failures or 'none'}")
    if _abort.is_set():
        return 130
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
