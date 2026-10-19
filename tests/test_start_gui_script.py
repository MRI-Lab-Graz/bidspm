"""scripts/start_gui.sh starts the GUI inside the project venv (with the venv's python and the chosen port)."""
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "start_gui.sh"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


class TestStartGuiScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        # a stand-in venv whose activate script only leaves a marker
        (self.dir / "venv" / "bin").mkdir(parents=True)
        (self.dir / "venv" / "bin" / "activate").write_text(f'echo activated > "{self.dir}/activated"\n')
        # a wrapper, not a symlink: a symlink to a venv's python loses that venv (no pyvenv.cfg next to it)
        fake_python = self.dir / "venv" / "bin" / "python"
        fake_python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        fake_python.chmod(0o755)
        self.port = _free_port()
        self.proc = None

    def tearDown(self):
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGKILL)
        self.tmp.cleanup()

    def start(self, *args, **env):
        full = {**os.environ, "BIDSPM_VENV": str(self.dir / "venv"), "BIDSPM_PORT": str(self.port),
                "HOME": str(self.dir / "home"), **env}
        self.proc = subprocess.Popen(["bash", str(SCRIPT), *args], env=full, cwd=str(self.dir),
                                     start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def wait_listening(self, seconds: float = 30) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            if _listening(self.port):
                return True
            time.sleep(0.2)
        return False

    def test_activates_the_venv_and_serves_the_gui_on_the_chosen_port(self):
        self.start("--no-browser")
        self.assertTrue(self.wait_listening(), "GUI never started")
        self.assertEqual((self.dir / "activated").read_text().strip(), "activated")

    def test_stopping_the_script_stops_the_server(self):
        self.start("--no-browser")
        self.assertTrue(self.wait_listening())
        os.killpg(self.proc.pid, signal.SIGINT)
        self.proc.wait(timeout=20)
        for _ in range(50):
            if not _listening(self.port):
                break
            time.sleep(0.2)
        self.assertFalse(_listening(self.port))

    def test_without_a_venv_it_fails_fast_and_says_how_to_create_one(self):
        self.start(BIDSPM_VENV=str(self.dir / "missing"))
        out, _ = self.proc.communicate(timeout=20)
        self.assertNotEqual(self.proc.returncode, 0)
        self.assertIn("setup.sh", out)

    def test_a_venv_with_a_dangling_python_is_refused_not_silently_replaced(self):
        # a dangling bin/python makes activation fall through to whatever python is first on PATH (e.g. FSL's)
        (self.dir / "venv" / "bin" / "python").unlink()
        (self.dir / "venv" / "bin" / "python").symlink_to("/nonexistent/python")
        self.start()
        out, _ = self.proc.communicate(timeout=20)
        self.assertNotEqual(self.proc.returncode, 0)
        self.assertIn("python", out.lower())
        self.assertIn("setup.sh", out)
        self.assertFalse(_listening(self.port))

    def test_arguments_are_passed_to_the_gui(self):
        self.start("--help")
        out, _ = self.proc.communicate(timeout=30)
        self.assertEqual(self.proc.returncode, 0)
        self.assertIn("--host", out)

    def _listener(self, *marker):
        """A python process listening on self.port; extra argv entries let it pose as another command line."""
        code = ("import http.server,sys;"
                f"http.server.HTTPServer(('127.0.0.1',{self.port}),http.server.BaseHTTPRequestHandler).serve_forever()")
        proc = subprocess.Popen([sys.executable, "-c", code, *marker], start_new_session=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: proc.poll() is None and os.killpg(proc.pid, signal.SIGKILL))
        self.assertTrue(self.wait_listening(10), "fake listener did not start")
        return proc

    def test_a_foreign_process_on_the_port_is_not_killed(self):
        foreign = self._listener()
        self.start("--no-browser")
        out, _ = self.proc.communicate(timeout=30)
        self.assertNotEqual(self.proc.returncode, 0)
        self.assertIsNone(foreign.poll(), "the foreign listener was killed")
        self.assertIn(str(foreign.pid), out)
        self.assertIn("--port", out)

    def test_an_old_gui_instance_on_the_port_is_replaced(self):
        old = self._listener("bidspm_gui.py")
        self.start("--no-browser")
        old.wait(timeout=15)  # SIGTERM'd by the new instance
        self.assertTrue(self.wait_listening(30), "new GUI never came up")

    def test_the_startup_self_check_reaches_a_redirected_log(self):
        log = self.dir / "gui.log"
        full = {**os.environ, "BIDSPM_VENV": str(self.dir / "venv"), "BIDSPM_PORT": str(self.port),
                "HOME": str(self.dir / "home")}
        with open(log, "w") as fh:
            self.proc = subprocess.Popen(["bash", str(SCRIPT), "--no-browser"], env=full, cwd=str(self.dir),
                                         start_new_session=True, stdout=fh, stderr=subprocess.STDOUT)
            end = time.time() + 30
            while time.time() < end and "Pre-flight check" not in log.read_text():
                time.sleep(0.2)
        self.assertIn("Pre-flight check", log.read_text())


if __name__ == "__main__":
    unittest.main()
