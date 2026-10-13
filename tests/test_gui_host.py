"""The web GUI has no login, so it must listen on loopback unless asked otherwise."""
import subprocess
import sys
import time
import unittest
from pathlib import Path

import bidspm_gui

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestGuiArgs(unittest.TestCase):
    def test_host_defaults_to_loopback(self):
        self.assertEqual(bidspm_gui.parse_gui_args([]).host, "127.0.0.1")

    def test_host_can_be_opened_up_explicitly(self):
        self.assertEqual(bidspm_gui.parse_gui_args(["--host", "0.0.0.0"]).host, "0.0.0.0")


@unittest.skipUnless(Path("/proc/net/tcp").exists(), "needs Linux /proc")
class TestGuiListensOnLoopbackOnly(unittest.TestCase):
    def _listening_addr(self, port: int):
        hex_port = f"{port:04X}"
        for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
            fields = line.split()
            addr, state = fields[1], fields[3]
            if addr.endswith(":" + hex_port) and state == "0A":  # LISTEN
                return addr.split(":")[0]
        return None

    def test_real_server_binds_127_0_0_1(self):
        port = bidspm_gui.find_free_port(5400)
        proc = subprocess.Popen([sys.executable, "bidspm_gui.py", "--no-browser", "-p", str(port)],
                                cwd=str(REPO_ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            addr = None
            for _ in range(100):
                addr = self._listening_addr(port)
                if addr:
                    break
                time.sleep(0.25)
            self.assertEqual(addr, "0100007F")  # 127.0.0.1, not 00000000
        finally:
            proc.terminate()
            proc.wait(timeout=10)
