import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "check_run_log", Path(__file__).resolve().parent.parent / "scripts" / "check_run_log.py")
check_run_log = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_run_log)

CLEAN = """\
warning: 
[12:35:20] bidspm - WARNING				labelActivations
no significant voxels in file:
Could not find specified file for mask/montage.
Warning: OpenGL Startup options have been removed.
warning: No voxels survive height threshold at u=3.1
   Subjects failed: 0
"""


class TestCheckRunLog(unittest.TestCase):
    def test_known_data_warnings_pass(self):
        self.assertEqual(check_run_log.find_problems(CLEAN), [])

    def test_unknown_warning_is_reported(self):
        out = check_run_log.find_problems(CLEAN + "warning: something new broke\n")
        self.assertEqual(out, ["warning: something new broke"])

    def test_unknown_bidspm_warning_function_is_reported(self):
        out = check_run_log.find_problems("[1:1:1] bidspm - WARNING\t\tsomeNewFunction\n")
        self.assertEqual(len(out), 1)

    def test_errors_and_tracebacks_are_reported(self):
        for line in ["error: 'x' undefined", "Traceback (most recent call last):",
                     "sh: 1: bids-validator: not found",
                     "Could not find a corresponding Node with", "Permission denied", "Subjects failed: 2"]:
            self.assertEqual(check_run_log.find_problems(line), [line], line)

    def test_cli_exit_code(self):
        import subprocess, sys, tempfile
        script = Path(check_run_log.__file__)
        with tempfile.NamedTemporaryFile("w", suffix=".log") as ok, tempfile.NamedTemporaryFile("w", suffix=".log") as bad:
            ok.write(CLEAN); ok.flush(); bad.write("error: boom\n"); bad.flush()
            self.assertEqual(subprocess.run([sys.executable, str(script), ok.name]).returncode, 0)
            self.assertEqual(subprocess.run([sys.executable, str(script), bad.name], capture_output=True).returncode, 1)
