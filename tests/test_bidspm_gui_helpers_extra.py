import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import bidspm_gui
from bidspm_gui import (
    _get_all_bids_dirs,
    _is_inside_bids_dir,
    _normalize_token_list,
    _pids_listening_on_port,
    _resolve_fs_path,
    collect_startup_preflight_checks,
    kill_existing_on_port,
    open_browser_when_ready,
    print_startup_preflight_report,
    resolve_python_executable,
    static_version,
)


class TestStartupPreflight(unittest.TestCase):
    def test_collect_startup_preflight_checks_all_ready(self):
        checks = collect_startup_preflight_checks()
        labels = {c["label"] for c in checks}
        self.assertIn("Core pipeline", labels)
        self.assertIn("REST API", labels)
        self.assertTrue(all(isinstance(c["ready"], bool) for c in checks))

    def test_collect_startup_preflight_checks_flags_missing_templates_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            checks = collect_startup_preflight_checks(app_root=Path(tmp))
            by_label = {c["label"]: c["ready"] for c in checks}
            self.assertFalse(by_label["Templates"])
            self.assertFalse(by_label["Static assets"])
            self.assertFalse(by_label["Config schema"])

    def test_print_startup_preflight_report_returns_overall_readiness(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = print_startup_preflight_report()
        self.assertIsInstance(result, bool)
        self.assertIn("Pre-flight check", buf.getvalue())

    def test_print_startup_preflight_report_false_when_something_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = print_startup_preflight_report(app_root=Path(tmp))
            self.assertFalse(result)
            self.assertIn("missing", buf.getvalue())


class TestOpenBrowserWhenReady(unittest.TestCase):
    def test_returns_false_when_server_never_becomes_ready(self):
        with patch("bidspm_gui.wait_for_http_ready", return_value=False):
            ok, message = open_browser_when_ready("http://localhost:9999")
        self.assertFalse(ok)
        self.assertIn("did not become ready", message)

    def test_opens_browser_successfully(self):
        with patch("bidspm_gui.wait_for_http_ready", return_value=True), \
             patch("webbrowser.open", return_value=True):
            ok, message = open_browser_when_ready("http://localhost:5100")
        self.assertTrue(ok)
        self.assertEqual(message, "Browser opened automatically")

    def test_browser_open_returns_false_reports_manual_fallback(self):
        with patch("bidspm_gui.wait_for_http_ready", return_value=True), \
             patch("webbrowser.open", return_value=False):
            ok, message = open_browser_when_ready("http://localhost:5100")
        self.assertFalse(ok)
        self.assertIn("Open manually", message)

    def test_browser_open_raising_is_caught(self):
        with patch("bidspm_gui.wait_for_http_ready", return_value=True), \
             patch("webbrowser.open", side_effect=RuntimeError("no display")):
            ok, message = open_browser_when_ready("http://localhost:5100")
        self.assertFalse(ok)
        self.assertIn("Unable to open browser automatically", message)


class TestPidsListeningOnPort(unittest.TestCase):
    def test_linux_branch_parses_ss_output(self):
        fake_result = MagicMock(stdout="LISTEN 0 128 *:5100 *:* users:((\"python\",pid=4242,fd=6))\n")
        with patch("sys.platform", "linux"), \
             patch("bidspm_gui.subprocess.run", return_value=fake_result):
            pids = _pids_listening_on_port(5100)
        self.assertEqual(pids, [4242])

    def test_darwin_branch_uses_lsof(self):
        fake_result = MagicMock(stdout="4242\n4343\n")
        with patch("sys.platform", "darwin"), \
             patch("bidspm_gui.subprocess.run", return_value=fake_result):
            pids = _pids_listening_on_port(5100)
        self.assertEqual(pids, [4242, 4343])

    def test_exception_returns_empty_list(self):
        with patch("bidspm_gui.subprocess.run", side_effect=OSError("no ss binary")):
            self.assertEqual(_pids_listening_on_port(5100), [])


class TestKillExistingOnPort(unittest.TestCase):
    def test_returns_false_when_nothing_listening(self):
        with patch("bidspm_gui._pids_listening_on_port", return_value=[]):
            self.assertFalse(kill_existing_on_port(5100))

    def test_sigterm_stops_process_gracefully(self):
        calls = {"count": 0}

        def fake_pids(port):
            calls["count"] += 1
            return [1234] if calls["count"] == 1 else []

        with patch("bidspm_gui._pids_listening_on_port", side_effect=fake_pids), \
             patch("bidspm_gui.os.kill") as mock_kill:
            result = kill_existing_on_port(5100)

        self.assertTrue(result)
        mock_kill.assert_called_once()

    def test_force_kills_lingering_process_after_grace_period(self):
        with patch("bidspm_gui._pids_listening_on_port", return_value=[1234]), \
             patch("bidspm_gui.os.kill"), \
             patch("bidspm_gui.time.time", side_effect=[0, 100, 100]), \
             patch("bidspm_gui.time.sleep"):
            result = kill_existing_on_port(5100)

        self.assertTrue(result)

    def test_ignores_processes_that_already_exited(self):
        with patch("bidspm_gui._pids_listening_on_port", return_value=[1234]), \
             patch("bidspm_gui.os.kill", side_effect=ProcessLookupError):
            result = kill_existing_on_port(5100)
        self.assertFalse(result)


class TestBidsDirHelpers(unittest.TestCase):
    def test_get_all_bids_dirs_collects_configured_folders(self):
        fake_project = type("P", (), {"config": type("C", (), {"bids_folder": "/data/bids"})()})()
        with patch.object(bidspm_gui.project_manager, "list_projects", return_value=[fake_project]):
            dirs = _get_all_bids_dirs()
        self.assertEqual(len(dirs), 1)
        self.assertTrue(dirs[0].endswith("/data/bids"))

    def test_get_all_bids_dirs_swallows_exceptions(self):
        with patch.object(bidspm_gui.project_manager, "list_projects", side_effect=RuntimeError("boom")):
            self.assertEqual(_get_all_bids_dirs(), [])

    def test_is_inside_bids_dir_true_for_subpath(self):
        with patch("bidspm_gui._get_all_bids_dirs", return_value=["/data/bids"]):
            self.assertTrue(_is_inside_bids_dir("/data/bids/sub-01/func"))
            self.assertTrue(_is_inside_bids_dir("/data/bids"))

    def test_is_inside_bids_dir_false_outside(self):
        with patch("bidspm_gui._get_all_bids_dirs", return_value=["/data/bids"]):
            self.assertFalse(_is_inside_bids_dir("/data/other"))


class TestResolveFsPath(unittest.TestCase):
    def test_empty_path_returns_empty_string(self):
        self.assertEqual(_resolve_fs_path("  "), "")

    def test_absolute_path_is_normalized(self):
        self.assertEqual(_resolve_fs_path("/tmp/../tmp/foo"), "/tmp/foo")

    def test_relative_existing_cwd_path_resolves_against_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing_dir"
            target.mkdir()
            import os
            orig_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                resolved = _resolve_fs_path("existing_dir")
            finally:
                os.chdir(orig_cwd)
            self.assertEqual(resolved, str(target.resolve()))

    def test_relative_new_path_anchors_to_app_root(self):
        resolved = _resolve_fs_path("definitely_does_not_exist_xyz")
        self.assertTrue(resolved.endswith("definitely_does_not_exist_xyz"))
        self.assertTrue(Path(resolved).is_absolute())


class TestNormalizeTokenListNone(unittest.TestCase):
    def test_none_returns_empty_list(self):
        self.assertEqual(_normalize_token_list(None), [])


class TestResolvePythonExecutable(unittest.TestCase):
    def _run_in_dir(self, tmp_dir, env=None):
        orig_cwd = os.getcwd()
        os.chdir(tmp_dir)
        try:
            with patch.dict(os.environ, env or {}, clear=False):
                # Ensure a stale BIDSPM_PYTHON from the real environment
                # doesn't leak into scenarios that don't set it explicitly.
                if not env or "BIDSPM_PYTHON" not in env:
                    os.environ.pop("BIDSPM_PYTHON", None)
                return resolve_python_executable()
        finally:
            os.chdir(orig_cwd)

    def test_env_override_used_when_it_points_at_a_real_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_python = Path(tmp) / "custom_python"
            real_python.write_text("", encoding="utf-8")
            resolved = self._run_in_dir(tmp, env={"BIDSPM_PYTHON": str(real_python)})
        self.assertEqual(resolved, str(real_python))

    def test_env_override_ignored_when_file_does_not_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolved = self._run_in_dir(tmp, env={"BIDSPM_PYTHON": "/no/such/python"})
        # Falls through to sys.executable since no .bidspm venv exists either.
        self.assertEqual(resolved, sys.executable)

    def test_venv_python_used_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            venv_python = Path(tmp) / ".bidspm" / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            venv_python.write_text("", encoding="utf-8")
            resolved = self._run_in_dir(tmp)
        self.assertEqual(resolved, str(venv_python))

    def test_dangling_venv_symlink_falls_back_to_sys_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            venv_bin = Path(tmp) / ".bidspm" / "bin"
            venv_bin.mkdir(parents=True)
            (venv_bin / "python").symlink_to("/no/such/target")
            resolved = self._run_in_dir(tmp)
        self.assertEqual(resolved, sys.executable)

    def test_falls_back_to_sys_executable_when_nothing_else_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            resolved = self._run_in_dir(tmp)
        self.assertEqual(resolved, sys.executable)


class TestStaticVersion(unittest.TestCase):
    def test_returns_mtime_based_token_for_existing_asset(self):
        asset_path = bidspm_gui.APP_ROOT / "static" / "css" / "main.css"
        expected = str(int(asset_path.stat().st_mtime))
        self.assertEqual(static_version("css/main.css"), expected)

    def test_token_changes_when_file_is_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_root = Path(tmp)
            (fake_root / "static").mkdir()
            asset = fake_root / "static" / "demo.js"
            asset.write_text("v1", encoding="utf-8")
            os.utime(asset, (1000, 1000))

            with patch.object(bidspm_gui, "APP_ROOT", fake_root):
                first = static_version("demo.js")
                os.utime(asset, (2000, 2000))
                second = static_version("demo.js")

        self.assertEqual(first, "1000")
        self.assertEqual(second, "2000")
        self.assertNotEqual(first, second)

    def test_returns_fallback_for_missing_asset(self):
        self.assertEqual(static_version("js/does_not_exist_at_all.js"), "0")


if __name__ == "__main__":
    unittest.main()
