import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.project_manager import ProjectManager


class TestProjectManagerExtra(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.manager = ProjectManager(Path(self.temp_dir.name) / "projects")

    def test_load_project_returns_none_for_corrupt_json(self):
        project = self.manager.create_project("Corrupt me")
        project_json = self.manager.projects_dir / project.id / "project.json"
        project_json.write_text("{not valid json", encoding="utf-8")

        self.assertIsNone(self.manager.load_project(project.id))

    def test_save_project_returns_false_on_write_error(self):
        project = self.manager.create_project("Unsaveable")
        with patch("builtins.open", side_effect=OSError("disk full")):
            self.assertFalse(self.manager.save_project(project))

    def test_list_projects_empty_when_dir_missing(self):
        empty_manager = ProjectManager(Path(self.temp_dir.name) / "does_not_exist")
        self.assertEqual(empty_manager.list_projects(), [])

    def test_list_projects_skips_non_directories_and_respects_limit(self):
        (self.manager.projects_dir).mkdir(parents=True, exist_ok=True)
        (self.manager.projects_dir / "stray_file.txt").write_text("", encoding="utf-8")
        self.manager.create_project("First")
        self.manager.create_project("Second")

        all_projects = self.manager.list_projects()
        self.assertEqual(len(all_projects), 2)

        limited = self.manager.list_projects(limit=1)
        self.assertEqual(len(limited), 1)

    def test_count_projects(self):
        self.assertEqual(self.manager.count_projects(), 0)
        self.manager.create_project("One")
        self.manager.create_project("Two")
        self.assertEqual(self.manager.count_projects(), 2)

    def test_count_projects_zero_when_dir_missing(self):
        empty_manager = ProjectManager(Path(self.temp_dir.name) / "does_not_exist_2")
        self.assertEqual(empty_manager.count_projects(), 0)

    def test_delete_project_missing_returns_false(self):
        self.assertFalse(self.manager.delete_project("does-not-exist"))

    def test_delete_project_removes_directory(self):
        project = self.manager.create_project("Deletable")
        self.assertTrue(self.manager.delete_project(project.id))
        self.assertIsNone(self.manager.load_project(project.id))

    def test_delete_project_returns_false_on_error(self):
        project = self.manager.create_project("Undeletable")
        with patch("lib.project_manager.shutil.rmtree", side_effect=OSError("busy")):
            self.assertFalse(self.manager.delete_project(project.id))

    def test_rename_project_updates_name(self):
        project = self.manager.create_project("Old Name")
        self.assertTrue(self.manager.rename_project(project.id, "New Name"))
        self.assertEqual(self.manager.load_project(project.id).name, "New Name")

    def test_rename_project_missing_returns_false(self):
        self.assertFalse(self.manager.rename_project("does-not-exist", "New Name"))

    def test_update_project_log_records_log_and_run_time(self):
        project = self.manager.create_project("Logged")
        self.assertTrue(self.manager.update_project_log(project.id, "run_123.log"))
        reloaded = self.manager.load_project(project.id)
        self.assertEqual(reloaded.last_log, "run_123.log")
        self.assertIsNotNone(reloaded.last_run)

    def test_update_project_log_missing_project_returns_false(self):
        self.assertFalse(self.manager.update_project_log("does-not-exist", "run.log"))

    def test_duplicate_project_missing_returns_none(self):
        self.assertIsNone(self.manager.duplicate_project("does-not-exist"))

    def test_duplicate_project_copies_config_with_default_name(self):
        original = self.manager.create_project("Original", config={"bids_folder": "/data/bids"})
        duplicate = self.manager.duplicate_project(original.id)
        self.assertEqual(duplicate.name, "Original (Copy)")
        self.assertEqual(duplicate.config.bids_folder, "/data/bids")
        self.assertNotEqual(duplicate.id, original.id)

    def test_import_config_missing_project_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "config.json"
            config_file.write_text("{}", encoding="utf-8")
            self.assertFalse(self.manager.import_config("does-not-exist", config_file))

    def test_import_config_missing_file_returns_false(self):
        project = self.manager.create_project("Importer")
        self.assertFalse(self.manager.import_config(project.id, Path("/no/such/config.json")))

    def test_import_config_maps_legacy_keys(self):
        project = self.manager.create_project("Importer2")
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "legacy.json"
            config_file.write_text(json.dumps({
                "BIDS_DIR": "/legacy/bids",
                "FWHM": 8,
            }), encoding="utf-8")
            self.assertTrue(self.manager.import_config(project.id, config_file))

        reloaded = self.manager.load_project(project.id)
        self.assertEqual(reloaded.config.bids_folder, "/legacy/bids")
        self.assertEqual(reloaded.config.fwhm, 8)

    def test_import_config_returns_false_on_malformed_json(self):
        project = self.manager.create_project("Importer3")
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "bad.json"
            config_file.write_text("{not valid json", encoding="utf-8")
            self.assertFalse(self.manager.import_config(project.id, config_file))

    def test_export_config_missing_project_returns_none(self):
        self.assertIsNone(self.manager.export_config("does-not-exist"))

    def test_export_config_non_bidspm_format_returns_raw_dict(self):
        project = self.manager.create_project("Exporter", config={"bids_folder": "/data/bids"})
        exported = self.manager.export_config(project.id, format="raw")
        self.assertEqual(exported["bids_folder"], "/data/bids")

    def test_get_current_project_id_none_when_file_missing(self):
        with patch("lib.project_manager.CURRENT_PROJECT_FILE", Path(self.temp_dir.name) / "missing.json"):
            self.assertIsNone(self.manager.get_current_project_id())

    def test_set_and_get_current_project_id_roundtrip(self):
        current_file = Path(self.temp_dir.name) / "current.json"
        with patch("lib.project_manager.CURRENT_PROJECT_FILE", current_file), \
             patch("lib.project_manager.DATA_DIR", Path(self.temp_dir.name)):
            self.manager.set_current_project_id("proj-42")
            self.assertEqual(self.manager.get_current_project_id(), "proj-42")

    def test_get_project_logs_dir_uses_output_folder_when_set(self):
        project = self.manager.create_project("Logs", config={"output_folder": "/data/output"})
        logs_dir = self.manager.get_project_logs_dir(project.id)
        self.assertEqual(logs_dir, Path("/data/output") / "logs")

    def test_get_project_logs_dir_falls_back_to_projects_dir(self):
        project = self.manager.create_project("NoOutput")
        logs_dir = self.manager.get_project_logs_dir(project.id)
        self.assertEqual(logs_dir, self.manager.projects_dir / project.id / "logs")


if __name__ == "__main__":
    unittest.main()
