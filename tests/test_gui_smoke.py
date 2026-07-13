"""End-to-end smoke test: boots the real bidspm_gui.py entrypoint as a
subprocess (not the in-process Flask test client used by the rest of the
suite) and probes it the way a researcher's first visit would. This is
exactly the manual check used when assessing whether the GUI actually
starts -- automated here so a regression (e.g. a startup-time import error,
a crash before the first request) fails CI instead of only surfacing when
someone happens to launch the app by hand.
"""

import json
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestGuiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = _find_free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.process = subprocess.Popen(
            [sys.executable, "bidspm_gui.py", "--no-browser", "-p", str(cls.port)],
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if not cls._wait_for_ready(f"{cls.base_url}/", timeout=25):
            output = ""
            if cls.process.stdout:
                cls.process.stdout.close()
            cls.process.kill()
            try:
                output = cls.process.communicate(timeout=5)[0] or ""
            except Exception:
                pass
            raise RuntimeError(
                f"bidspm_gui.py did not become ready on {cls.base_url} within timeout.\n"
                f"Process output:\n{output}"
            )

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait()
        if cls.process.stdout:
            cls.process.stdout.close()

    @staticmethod
    def _wait_for_ready(url: str, timeout: float = 25.0, interval: float = 0.3) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2.0) as response:
                    if 200 <= response.status < 400:
                        return True
            except Exception:
                time.sleep(interval)
        return False

    def _get(self, path: str):
        return urllib.request.urlopen(f"{self.base_url}{path}", timeout=10)

    def test_page_routes_respond_ok(self):
        # urllib follows redirects transparently, so /analysis (which may
        # 302 to a resumed project) still resolves to a final 200 here.
        for path in ("/", "/projects", "/analysis", "/transformer-builder"):
            with self.subTest(path=path):
                response = self._get(path)
                self.assertEqual(response.status, 200)

    def test_api_routes_return_json(self):
        for path in ("/check_environment", "/api/preflight/tools", "/api/projects"):
            with self.subTest(path=path):
                response = self._get(path)
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), "application/json")
                payload = json.loads(response.read())
                self.assertIsInstance(payload, dict)

    def test_unknown_route_returns_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/this-route-does-not-exist")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
