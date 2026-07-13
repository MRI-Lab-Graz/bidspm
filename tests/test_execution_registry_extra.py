import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from webapp.web_execution_api import ExecutionRegistry


class TestExecutionRegistryExtra(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.manager = MagicMock()
        self.registry = ExecutionRegistry(
            get_project_manager=lambda: self.manager,
            log_dir=Path(self.temp_dir.name) / "logs",
            max_executions=50,
        )

    def test_finalize_execution_is_a_no_op_for_unknown_execution(self):
        self.registry.finalize_execution("does-not-exist", 0)  # must not raise

    def test_finalize_execution_is_a_no_op_when_already_finished(self):
        self.registry.executions["exec-1"] = {"finished": True, "return_code": 0}
        self.registry.finalize_execution("exec-1", 1)
        self.assertEqual(self.registry.executions["exec-1"]["return_code"], 0)  # unchanged

    def test_finalize_execution_without_project_skips_log_update(self):
        log_file = Path(self.temp_dir.name) / "run.log"
        log_file.write_text("", encoding="utf-8")
        self.registry.executions["exec-2"] = {
            "finished": False, "project_id": None, "log_filename": None,
            "log_file": str(log_file), "process": object(),
        }
        self.registry.finalize_execution("exec-2", 0)
        self.manager.update_project_log.assert_not_called()

    def test_monitor_execution_finalizes_with_process_return_code(self):
        fake_process = MagicMock()
        fake_process.wait.return_value = 42
        log_file = Path(self.temp_dir.name) / "run2.log"
        log_file.write_text("", encoding="utf-8")
        self.registry.executions["exec-3"] = {
            "finished": False, "project_id": None, "log_filename": None,
            "log_file": str(log_file), "process": fake_process,
        }
        self.registry.monitor_execution("exec-3", fake_process)
        self.assertEqual(self.registry.executions["exec-3"]["return_code"], 42)

    def test_monitor_execution_defaults_to_minus_one_when_wait_raises(self):
        fake_process = MagicMock()
        fake_process.wait.side_effect = RuntimeError("boom")
        log_file = Path(self.temp_dir.name) / "run3.log"
        log_file.write_text("", encoding="utf-8")
        self.registry.executions["exec-4"] = {
            "finished": False, "project_id": None, "log_filename": None,
            "log_file": str(log_file), "process": fake_process,
        }
        self.registry.monitor_execution("exec-4", fake_process)
        self.assertEqual(self.registry.executions["exec-4"]["return_code"], -1)

    def test_execution_log_location_with_project_uses_project_logs_dir(self):
        self.manager.get_project_logs_dir.return_value = Path(self.temp_dir.name) / "proj_logs"
        log_path, log_filename = self.registry.execution_log_location("proj-1", "abcdef1234567890")
        self.assertTrue(str(log_path).endswith(log_filename))
        self.assertTrue(log_filename.startswith("run_"))
        self.assertIn("abcdef12", log_filename)

    def test_execution_log_location_without_project_uses_global_log_dir(self):
        log_path, log_filename = self.registry.execution_log_location(None, "abcdef1234567890")
        self.assertTrue(log_filename.startswith("web_run_"))
        self.assertTrue(str(log_path).startswith(str(self.registry.log_dir)))

    def test_sanitize_sse_line_strips_control_characters(self):
        raw = "hello\x00world\x1f!\n"
        self.assertEqual(ExecutionRegistry.sanitize_sse_line(raw), "hello world !")

    def test_cleanup_old_executions_no_op_below_threshold(self):
        self.registry.max_executions = 10
        self.registry.executions = {"a": {"finished": True, "start_time": 1}}
        self.registry.cleanup_old_executions()
        self.assertIn("a", self.registry.executions)

    def test_cleanup_old_executions_deletes_generated_settings_files(self):
        # Each /run call can auto-generate a run_settings_*.json scratch
        # file; without this, those accumulate forever in ~/.bidspm/config
        # or a project's configs/ dir, one per run.
        settings_file = Path(self.temp_dir.name) / "run_settings_old.json"
        settings_file.write_text("{}", encoding="utf-8")

        self.registry.max_executions = 1
        self.registry.executions = {
            "old-finished": {
                "finished": True, "start_time": 1,
                "generated_settings_files": [str(settings_file)],
            },
            "new-finished": {"finished": True, "start_time": 2},
        }

        self.registry.cleanup_old_executions()

        self.assertNotIn("old-finished", self.registry.executions)
        self.assertFalse(settings_file.exists())

    def test_cleanup_old_executions_leaves_caller_provided_settings_untouched(self):
        # A settings path the caller explicitly passed in (not one this
        # server generated) must never be deleted.
        user_settings = Path(self.temp_dir.name) / "my_config.json"
        user_settings.write_text("{}", encoding="utf-8")

        self.registry.max_executions = 1
        self.registry.executions = {
            "old-finished": {
                "finished": True, "start_time": 1,
                "generated_settings_files": [],  # user-supplied settings, nothing generated
            },
            "new-finished": {"finished": True, "start_time": 2},
        }

        self.registry.cleanup_old_executions()

        self.assertTrue(user_settings.exists())

    def test_cleanup_old_executions_ignores_missing_or_unlinkable_files(self):
        self.registry.max_executions = 1
        self.registry.executions = {
            "old-finished": {
                "finished": True, "start_time": 1,
                "generated_settings_files": ["/no/such/file/ever.json"],
            },
            "new-finished": {"finished": True, "start_time": 2},
        }

        self.registry.cleanup_old_executions()  # must not raise

        self.assertNotIn("old-finished", self.registry.executions)


if __name__ == "__main__":
    unittest.main()
