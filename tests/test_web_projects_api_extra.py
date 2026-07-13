import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import bidspm_gui
from bidspm_gui import app as flask_app
from lib.project_manager import ProjectManager
from webapp.web_projects_api import _build_project_preflight_results


def _config(**overrides):
    base = dict(bids_folder="", fmriprep_folder="", derivatives_folder="", space="")
    base.update(overrides)
    return SimpleNamespace(**base)


class TestBuildProjectPreflightResults(unittest.TestCase):
    """Unit-level coverage of every status branch (ok/warning/error/na)."""

    def test_all_folders_unconfigured_report_na(self):
        results = _build_project_preflight_results(_config())
        self.assertEqual(results["bids_folder"]["status"], "na")
        self.assertEqual(results["fmriprep_folder"]["status"], "na")
        self.assertEqual(results["events"]["status"], "na")
        self.assertEqual(results["space"]["status"], "na")
        self.assertEqual(results["smooth"]["status"], "na")

    def test_bids_folder_missing_on_disk_is_error(self):
        results = _build_project_preflight_results(_config(bids_folder="/no/such/dir"))
        self.assertEqual(results["bids_folder"]["status"], "error")

    def test_bids_folder_without_dataset_description_is_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = _build_project_preflight_results(_config(bids_folder=tmp))
            self.assertEqual(results["bids_folder"]["status"], "warning")

    def test_bids_folder_valid_is_ok_and_events_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dataset_description.json").write_text("{}", encoding="utf-8")
            events_dir = root / "sub-01" / "func"
            events_dir.mkdir(parents=True)
            (events_dir / "sub-01_task-motor_events.tsv").write_text("", encoding="utf-8")

            results = _build_project_preflight_results(_config(bids_folder=tmp))
            self.assertEqual(results["bids_folder"]["status"], "ok")
            self.assertEqual(results["events"]["status"], "ok")
            self.assertEqual(results["events"]["value"], "1")

    def test_bids_folder_valid_but_no_events_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dataset_description.json").write_text("{}", encoding="utf-8")
            results = _build_project_preflight_results(_config(bids_folder=tmp))
            self.assertEqual(results["events"]["status"], "error")

    def test_fmriprep_folder_valid_and_space_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dataset_description.json").write_text("{}", encoding="utf-8")
            space_dir = root / "sub-01" / "func"
            space_dir.mkdir(parents=True)
            (space_dir / "sub-01_task-motor_space-MNI152NLin2009cAsym_bold.nii.gz").write_text("", encoding="utf-8")

            results = _build_project_preflight_results(
                _config(fmriprep_folder=tmp, space="MNI152NLin2009cAsym")
            )
            self.assertEqual(results["fmriprep_folder"]["status"], "ok")
            self.assertEqual(results["space"]["status"], "ok")
            self.assertIn("MNI152NLin2009cAsym", results["available_spaces"])

    def test_fmriprep_folder_without_description_is_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = _build_project_preflight_results(_config(fmriprep_folder=tmp))
            self.assertEqual(results["fmriprep_folder"]["status"], "warning")

    def test_space_mismatch_warns_with_available_alternative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            space_dir = root / "sub-01" / "func"
            space_dir.mkdir(parents=True)
            (space_dir / "sub-01_task-motor_space-T1w_bold.nii.gz").write_text("", encoding="utf-8")

            results = _build_project_preflight_results(
                _config(fmriprep_folder=tmp, space="MNI152NLin6Asym")
            )
            self.assertEqual(results["space"]["status"], "warning")
            self.assertEqual(results["space"]["value"], "T1w")

    def test_space_no_spaces_detected_warns_without_alternative(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = _build_project_preflight_results(_config(fmriprep_folder=tmp, space="T1w"))
            self.assertEqual(results["space"]["status"], "warning")
            self.assertNotIn("value", results["space"])

    def test_smooth_detected_when_smth_files_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            smth_dir = root / "bidspm-preproc" / "sub-01"
            smth_dir.mkdir(parents=True)
            (smth_dir / "sub-01_task-motor_desc-smth6.0_bold.nii.gz").write_text("", encoding="utf-8")

            results = _build_project_preflight_results(_config(derivatives_folder=tmp))
            self.assertEqual(results["smooth"]["status"], "ok")
            self.assertEqual(results["smooth"]["value"], "Yes")

    def test_smooth_not_found_when_derivatives_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = _build_project_preflight_results(_config(derivatives_folder=tmp))
            self.assertEqual(results["smooth"]["status"], "na")
            self.assertEqual(results["smooth"]["value"], "No")


class TestProjectRoutesExtra(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app.config.update(TESTING=True)
        cls.client = flask_app.test_client()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.project_manager = ProjectManager(Path(self.temp_dir.name) / "projects")
        self.project_manager_patch = patch.object(bidspm_gui, "project_manager", self.project_manager)
        self.project_manager_patch.start()
        self.addCleanup(self.project_manager_patch.stop)

    def _create_project(self, **config_overrides):
        config = {"bids_folder": "", "derivatives_folder": ""}
        config.update(config_overrides)
        response = self.client.post(
            "/api/projects",
            json={"name": "Extra coverage project", "config": config},
        )
        return response.get_json()["project"]

    def test_update_project_config_endpoint(self):
        project = self._create_project()
        response = self.client.put(
            f"/api/projects/{project['id']}/config",
            json={"fwhm": 8},
        )
        self.assertEqual(response.status_code, 200)
        config_response = self.client.get(f"/api/projects/{project['id']}/config")
        self.assertEqual(config_response.get_json()["fwhm"], 8)

    def test_update_project_config_missing_project_returns_404(self):
        response = self.client.put("/api/projects/does-not-exist/config", json={"fwhm": 8})
        self.assertEqual(response.status_code, 404)

    def test_import_config_missing_path_returns_400(self):
        project = self._create_project()
        response = self.client.post(
            f"/api/projects/{project['id']}/import",
            json={"path": "/no/such/config.json"},
        )
        self.assertEqual(response.status_code, 400)

    def test_import_config_success(self):
        project = self._create_project()
        config_file = Path(self.temp_dir.name) / "external_config.json"
        config_file.write_text(json.dumps({"bids_folder": "/imported/bids"}), encoding="utf-8")

        response = self.client.post(
            f"/api/projects/{project['id']}/import",
            json={"path": str(config_file)},
        )
        self.assertEqual(response.status_code, 200)

        config_response = self.client.get(f"/api/projects/{project['id']}/config")
        self.assertEqual(config_response.get_json()["bids_folder"], "/imported/bids")

    def test_logs_endpoint_empty_when_no_logs_dir(self):
        project = self._create_project()
        response = self.client.get(f"/api/projects/{project['id']}/logs")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["logs"], [])

    def test_logs_endpoint_lists_log_files(self):
        project = self._create_project()
        logs_dir = self.project_manager.get_project_logs_dir(project["id"])
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "run_1.log").write_text("log contents", encoding="utf-8")

        response = self.client.get(f"/api/projects/{project['id']}/logs")
        payload = response.get_json()
        self.assertEqual(len(payload["logs"]), 1)
        self.assertEqual(payload["logs"][0]["name"], "run_1.log")

    def test_get_update_delete_duplicate_preflight_404_for_missing_project(self):
        missing_id = "does-not-exist"
        self.assertEqual(self.client.get(f"/api/projects/{missing_id}").status_code, 404)
        self.assertEqual(
            self.client.put(f"/api/projects/{missing_id}", json={"name": "x"}).status_code, 404
        )
        self.assertEqual(self.client.delete(f"/api/projects/{missing_id}").status_code, 404)
        self.assertEqual(
            self.client.post(f"/api/projects/{missing_id}/duplicate", json={}).status_code, 404
        )
        self.assertEqual(self.client.get(f"/api/projects/{missing_id}/preflight").status_code, 404)
        self.assertEqual(self.client.get(f"/api/projects/{missing_id}/config").status_code, 404)
        self.assertEqual(self.client.get(f"/api/projects/{missing_id}/export").status_code, 404)

    def test_routes_return_500_when_project_manager_raises(self):
        project = self._create_project()

        with patch.object(self.project_manager, "list_projects", side_effect=RuntimeError("db down")):
            self.assertEqual(self.client.get("/api/projects").status_code, 500)

        with patch.object(self.project_manager, "create_project", side_effect=RuntimeError("db down")):
            self.assertEqual(
                self.client.post("/api/projects", json={"name": "x"}).status_code, 500
            )

        with patch.object(self.project_manager, "load_project", side_effect=RuntimeError("db down")):
            self.assertEqual(self.client.get(f"/api/projects/{project['id']}").status_code, 500)
            self.assertEqual(
                self.client.put(f"/api/projects/{project['id']}", json={"name": "y"}).status_code, 500
            )
            self.assertEqual(self.client.delete(f"/api/projects/{project['id']}").status_code, 500)
            self.assertEqual(
                self.client.get(f"/api/projects/{project['id']}/preflight").status_code, 500
            )
            self.assertEqual(
                self.client.get(f"/api/projects/{project['id']}/config").status_code, 500
            )

        with patch.object(self.project_manager, "duplicate_project", side_effect=RuntimeError("db down")):
            self.assertEqual(
                self.client.post(f"/api/projects/{project['id']}/duplicate", json={}).status_code, 500
            )

        with patch.object(self.project_manager, "update_project_config", side_effect=RuntimeError("db down")):
            self.assertEqual(
                self.client.put(f"/api/projects/{project['id']}/config", json={}).status_code, 500
            )

        with patch.object(self.project_manager, "export_config", side_effect=RuntimeError("db down")):
            self.assertEqual(
                self.client.get(f"/api/projects/{project['id']}/export").status_code, 500
            )

        with patch.object(self.project_manager, "get_project_logs_dir", side_effect=RuntimeError("db down")):
            self.assertEqual(
                self.client.get(f"/api/projects/{project['id']}/logs").status_code, 500
            )

    def test_import_config_returns_500_when_manager_raises(self):
        project = self._create_project()
        config_file = Path(self.temp_dir.name) / "cfg.json"
        config_file.write_text("{}", encoding="utf-8")
        with patch.object(self.project_manager, "import_config", side_effect=RuntimeError("db down")):
            response = self.client.post(
                f"/api/projects/{project['id']}/import", json={"path": str(config_file)},
            )
        self.assertEqual(response.status_code, 500)


if __name__ == "__main__":
    unittest.main()
