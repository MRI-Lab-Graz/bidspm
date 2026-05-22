import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bidspm_gui import app as flask_app
from bidspm_gui import collect_startup_preflight_checks, open_browser_when_ready
from lib.core import Pipeline, PipelineOptions
from lib.project_manager import ProjectManager


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


class TestNewFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app.config.update(TESTING=True)
        cls.client = flask_app.test_client()

    def test_model_editor_page_renders(self):
        response = self.client.get("/model_editor", query_string={"path": "studies/model.json"})

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Model Editor", text)
        self.assertIn("studies/model.json", text)

    def test_api_bids_entities_missing_path_returns_defaults(self):
        response = self.client.get("/api/bids_entities", query_string={"path": "/path/that/does/not/exist"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["entities"], [])
        self.assertEqual(payload["groupby_options"], ["subject"])
        self.assertEqual(payload["values"], {"task": [], "run": [], "session": [], "subject": []})

    def test_api_bids_entities_extracts_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            bids_dir = Path(tmp_dir) / "bids"
            sample_file = (
                bids_dir
                / "sub-01"
                / "ses-01"
                / "func"
                / "sub-01_ses-01_task-motor_run-02_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
            )
            _touch(sample_file)

            response = self.client.get("/api/bids_entities", query_string={"path": str(bids_dir)})

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            values = payload["values"]

            self.assertIn("task", payload["entities"])
            self.assertEqual(values["task"], ["motor"])
            self.assertEqual(values["run"], ["02"])
            self.assertEqual(values["session"], ["01"])
            self.assertEqual(values["subject"], ["01"])
            self.assertIn("func", values["datatype"])
            self.assertIn("bold", values["suffix"])
            self.assertIn(".nii.gz", values["extension"])
            self.assertIn("MNI152NLin2009cAsym", values["space"])
            self.assertEqual(payload["groupby_options"], ["subject", "run", "session", "task"])

    def test_get_fmriprep_spaces_filters_by_task(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            fmriprep_dir = Path(tmp_dir) / "fmriprep"

            motor_file = (
                fmriprep_dir
                / "sub-01"
                / "func"
                / "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
            )
            rest_file = (
                fmriprep_dir
                / "sub-01"
                / "func"
                / "sub-01_task-rest_space-T1w_desc-preproc_bold.nii.gz"
            )
            _touch(motor_file)
            _touch(rest_file)

            all_spaces = self.client.get("/get_fmriprep_spaces", query_string={"path": str(fmriprep_dir)})
            motor_spaces = self.client.get(
                "/get_fmriprep_spaces",
                query_string=[("path", str(fmriprep_dir)), ("tasks", "motor")],
            )

            self.assertEqual(all_spaces.status_code, 200)
            self.assertEqual(all_spaces.get_json(), ["MNI152NLin2009cAsym", "T1w"])

            self.assertEqual(motor_spaces.status_code, 200)
            self.assertEqual(motor_spaces.get_json(), ["MNI152NLin2009cAsym"])

    def test_api_model_hints_includes_participants_metadata(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            bids_dir = Path(tmp_dir) / "bids"
            event_file = bids_dir / "sub-01" / "func" / "sub-01_task-motor_events.tsv"
            event_file.parent.mkdir(parents=True, exist_ok=True)
            event_file.write_text(
                "onset\tduration\ttrial_type\n0\t1\tleft\n2\t1\tright\n",
                encoding="utf-8",
            )
            (bids_dir / "participants.tsv").write_text(
                "participant_id\tgroup\tage\nsub-01\tcontrol\t29\nsub-02\tpatient\t34\n",
                encoding="utf-8",
            )

            response = self.client.post(
                "/api/model_hints",
                json={
                    "bids_dir": str(bids_dir),
                    "model_content": {
                        "Name": "demo",
                        "BIDSModelVersion": "1.0.0",
                        "Input": {"task": ["motor"]},
                        "Nodes": []
                    }
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            participants = payload["dataset"]["participants"]

            self.assertEqual(participants["categorical_columns"], ["group"])
            self.assertEqual(participants["numeric_columns"], ["age"])
            self.assertEqual(participants["sample_values"]["group"], ["control", "patient"])
            self.assertEqual(participants["numeric_stats"]["age"]["count"], 2)

    def test_project_manager_exports_node_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            manager = ProjectManager(Path(tmp_dir) / "projects")
            project = manager.create_project(
                "demo",
                config={
                    "models_file": "studies/model.json",
                    "node_name": "dataset_level"
                }
            )

            exported = manager.export_config(project.id, "bidspm")

            self.assertEqual(exported["MODELS_FILE"], "studies/model.json")
            self.assertEqual(exported["NODE_NAME"], "dataset_level")

    def test_startup_preflight_checks_report_expected_surfaces(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "templates").mkdir()
            (root / "static").mkdir()
            (root / "config").mkdir()
            (root / "config" / "config_schema.json").write_text("{}\n", encoding="utf-8")

            checks = collect_startup_preflight_checks(app_root=root)

        labels = [check["label"] for check in checks]
        by_label = {check["label"]: check["ready"] for check in checks}

        self.assertEqual(
            labels,
            [
                "Core pipeline",
                "Project manager",
                "Templates",
                "Static assets",
                "Config schema",
                "Waitress server",
                "REST API",
                "Workflow routes",
            ],
        )
        self.assertTrue(all(by_label.values()))

    def test_startup_preflight_checks_flag_missing_assets(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            checks = collect_startup_preflight_checks(app_root=Path(tmp_dir))

        by_label = {check["label"]: check["ready"] for check in checks}

        self.assertFalse(by_label["Templates"])
        self.assertFalse(by_label["Static assets"])
        self.assertFalse(by_label["Config schema"])
        self.assertTrue(by_label["REST API"])
        self.assertTrue(by_label["Workflow routes"])

    def test_open_browser_when_ready_uses_browser_handler(self):
        url = "http://localhost:5100"

        with patch("bidspm_gui.wait_for_http_ready", return_value=True), \
             patch("webbrowser.open", return_value=True) as mock_open:
            opened, message = open_browser_when_ready(url)

        self.assertTrue(opened)
        self.assertEqual(message, "Browser opened automatically")
        mock_open.assert_called_once_with(url)

    def test_pipeline_dry_run_includes_node_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bids_dir = root / "bids"
            derivatives_dir = root / "derivatives"
            fmriprep_dir = root / "fmriprep"
            container_cfg = root / "container.json"
            apptainer_image = root / "fake.sif"
            config_file = root / "config.json"
            model_file = root / "model.json"

            bids_dir.mkdir()
            derivatives_dir.mkdir()
            (fmriprep_dir / "sub-01").mkdir(parents=True)
            apptainer_image.write_text("fake", encoding="utf-8")

            container_cfg.write_text(
                f'{{"container_type": "apptainer", "apptainer_image": "{apptainer_image}"}}',
                encoding="utf-8",
            )
            config_file.write_text(
                (
                    '{'
                    f'"WD": "{root}", '
                    f'"BIDS_DIR": "{bids_dir}", '
                    f'"DERIVATIVES_DIR": "{derivatives_dir}", '
                    f'"FMRIPREP_DIR": "{fmriprep_dir}", '
                    '"SPACE": "MNI152NLin2009cAsym", '
                    '"FWHM": 6, '
                    '"MODELS_FILE": "", '
                    '"TASKS": ["motor"], '
                    '"VERBOSITY": 2, '
                    '"container_type": "apptainer"'
                    '}'
                ),
                encoding="utf-8",
            )
            model_file.write_text(
                '{"Name": "demo", "BIDSModelVersion": "1.0.0", "Input": {"task": ["motor"]}, "Nodes": []}',
                encoding="utf-8",
            )

            options = PipelineOptions(
                actions=["dataset"],
                config_file=str(config_file),
                container_config_file=str(container_cfg),
                model_file=str(model_file),
                node_name="dataset_level",
                skip_validation=True,
                dry_run=True,
            )

            with patch("lib.core.check_command", return_value=None), \
                 patch("lib.core.validate_space_availability", return_value=True), \
                 patch("lib.core.ensure_derivatives_dataset_description", return_value=None), \
                 patch("lib.core.cleanup_tmp_directories", return_value=None):
                result = Pipeline(options).run()

            self.assertTrue(result.success)
            self.assertTrue(result.dry_run_commands)
            self.assertIn("--node_name dataset_level", result.dry_run_commands[0])


if __name__ == "__main__":
    unittest.main()
