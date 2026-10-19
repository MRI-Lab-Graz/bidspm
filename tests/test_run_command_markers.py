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


class TestMarkerRunsStillShowOutput(unittest.TestCase):
    """With failure_markers the bidspm output must still reach the log (regression from 86fb122)."""

    def _run(self, *lines, markers=("ERROR LOG SAVED:",)):
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            ok = run_command(_cmd(*lines), failure_markers=markers)
        return ok, buf.getvalue()

    def test_plain_lines_are_printed(self):
        ok, out = self._run("x")
        self.assertTrue(ok)
        self.assertIn("x", out)

    def test_warning_block_is_printed_intact(self):
        _, out = self._run("[09:12:01] bidspm - WARNING", "something is off")
        self.assertIn("bidspm - WARNING", out)
        self.assertIn("something is off", out)

    def test_noise_is_dropped_but_warnings_kept(self):
        _, out = self._run("warning: function /x/y.m shadows a built-in function", "", "real line")
        self.assertNotIn("shadows", out)
        self.assertIn("real line", out)

    def test_error_log_saved_is_printed_and_fails(self):
        ok, out = self._run("ERROR LOG SAVED:", "/d/error_logs/e.log")
        self.assertFalse(ok)
        self.assertIn("ERROR LOG SAVED:", out)

    def test_failure_exit_code_still_fails(self):
        ok = run_command([sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"],
                         failure_markers=("ERROR LOG SAVED:",))
        self.assertFalse(ok)
