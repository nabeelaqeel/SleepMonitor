#!/usr/bin/env python3
"""Synthetic (no sudo, no real netem) tests for the v2 netem guards."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BENCH_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH_DIR))

import run_benchmark as rb  # noqa: E402

CLEAN_QDISC = "qdisc noqueue 0: root refcnt 2\n"
NETEM_QDISC = ("qdisc netem 8001: root refcnt 2 limit 1000 "
               "delay 25.0ms 10.0ms loss 2%\n")


class FakeTc:
    """Fake `subprocess.run` for tc show/delete only."""

    def __init__(self, show_outputs):
        """Queue the scripted `tc qdisc show` outputs and record every command seen."""
        self.show_outputs = list(show_outputs)
        self.calls = []

    def __call__(self, command, **kwargs):
        """Serve show/delete results from the script; replay exhaustion or an unexpected command raises instead of guessing."""
        self.calls.append(list(command))
        if command == rb.NETEM_SHOW_CMD:
            if not self.show_outputs:
                raise AssertionError("unexpected extra tc qdisc show")
            return SimpleNamespace(stdout=self.show_outputs.pop(0),
                                   returncode=0)
        if command == rb.NETEM_CLEAR_CMD:
            return SimpleNamespace(stdout="", returncode=0)
        raise AssertionError(f"unexpected command: {command!r}")


class NetemGuardTests(unittest.TestCase):
    def setUp(self):
        """Reset run_benchmark's abort flag and netem-applied marker per test."""
        rb._abort.clear()
        rb._netem_applied = False

    def tearDown(self):
        """Same reset after the test so module state never leaks between suites."""
        rb._abort.clear()
        rb._netem_applied = False

    @contextmanager
    def run_tc(self, fake):
        """Patch subprocess.run with the fake tc driver and capture the guard's stdout for assertion."""
        output = io.StringIO()
        with patch.object(rb.subprocess, "run", side_effect=fake), \
                redirect_stdout(output):
            yield output

    def test_clear_retry_succeeds_but_run_is_dirty(self):
        """A leftover qdisc that clears on retry succeeds exactly once but still marks the run dirty and does NOT abort the matrix."""
        fake = FakeTc([NETEM_QDISC, CLEAN_QDISC])
        rb._netem_applied = True
        with self.run_tc(fake):
            first_clear_clean = rb.netem_clear()

        self.assertFalse(first_clear_clean)
        self.assertFalse(rb._netem_applied)
        self.assertFalse(rb._abort.is_set())
        self.assertEqual(
            fake.calls.count(rb.NETEM_CLEAR_CMD), 2,
            "a leftover qdisc must trigger exactly one retry")

    def test_clear_still_present_aborts_matrix(self):
        """A netem qdisc that survives the retry raises NetemClearError and sets the abort flag."""
        fake = FakeTc([NETEM_QDISC, NETEM_QDISC])
        rb._netem_applied = True
        with self.run_tc(fake):
            with self.assertRaises(rb.NetemClearError):
                rb.netem_clear()

        self.assertTrue(rb._abort.is_set())
        self.assertTrue(rb._netem_applied)
        self.assertEqual(fake.calls.count(rb.NETEM_CLEAR_CMD), 2)

    def test_pre_run_leftover_aborts_matrix(self):
        """Leftover netem before a run aborts the matrix after exactly one show call; the run is refused."""
        fake = FakeTc([NETEM_QDISC])
        with self.run_tc(fake):
            allowed = rb.check_no_netem_before_run("A-clean-r01", "clean")

        self.assertFalse(allowed)
        self.assertTrue(rb._abort.is_set())
        self.assertEqual(fake.calls, [rb.NETEM_SHOW_CMD])

    def test_pre_run_clean_allows_run(self):
        """Clean interface at run start allows the run and leaves the abort flag untouched."""
        fake = FakeTc([CLEAN_QDISC])
        with self.run_tc(fake):
            allowed = rb.check_no_netem_before_run("A-netem-r01", "netem")

        self.assertTrue(allowed)
        self.assertFalse(rb._abort.is_set())
        self.assertEqual(fake.calls, [rb.NETEM_SHOW_CMD])


if __name__ == "__main__":
    unittest.main(verbosity=2)
