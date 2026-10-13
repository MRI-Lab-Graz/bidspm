"""bidspm's launcher is try/catch + exit: a caught failure prints 'ERROR LOG SAVED:' and still exits 0."""
import sys
import unittest

from lib.utils import run_command


def _cmd(*lines: str):
    return [sys.executable, "-c", "; ".join(f"print({l!r})" for l in lines)]


class TestFailureMarkers(unittest.TestCase):
    def test_exit_zero_with_marker_is_a_failure(self):
        cmd = _cmd("working", "ERROR LOG SAVED:", "/derivatives/error_logs/e.log")
        self.assertFalse(run_command(cmd, failure_markers=("ERROR LOG SAVED:",)))

    def test_exit_zero_without_marker_is_success(self):
        self.assertTrue(run_command(_cmd("all good"), failure_markers=("ERROR LOG SAVED:",)))

    def test_markers_are_opt_in(self):
        self.assertTrue(run_command(_cmd("ERROR LOG SAVED:")))
