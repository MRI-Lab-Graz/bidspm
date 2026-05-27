import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import bidspm_gui
import web_discovery_model_api
from bidspm_gui import app as flask_app
from lib.project_manager import ProjectManager


class TestWebRoutes(unittest.TestCase):
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
        self.execution_registry = bidspm_gui.execution_registry
        self.original_executions = dict(self.execution_registry.executions)
        self.original_current_execution_id = self.execution_registry.current_execution_id
        self.original_current_project_id = self.execution_registry.current_project_id
        self.execution_registry.executions.clear()
        self.execution_registry.current_execution_id = None
        self.execution_registry.current_project_id = None
        self.addCleanup(self._restore_execution_state)

    def _restore_execution_state(self):
        self.execution_registry.executions.clear()
        self.execution_registry.executions.update(self.original_executions)
        self.execution_registry.current_execution_id = self.original_current_execution_id
        self.execution_registry.current_project_id = self.original_current_project_id

    def test_projects_page_shows_empty_state(self):
        response = self.client.get("/projects")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Manage your BIDSPM analysis projects", text)
        self.assertIn("No Projects Yet", text)

    def test_projects_page_lists_existing_project(self):
        project = self.project_manager.create_project("Demo project", description="study setup")

        response = self.client.get("/projects")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Demo project", text)
        self.assertIn(f"/analysis/{project.id}", text)

    def test_analysis_project_route_renders_project_context(self):
        bids_dir = Path(self.temp_dir.name) / "bids"
        output_dir = Path(self.temp_dir.name) / "output"
        project = self.project_manager.create_project(
            "Motor study",
            config={
                "bids_folder": str(bids_dir),
                "output_folder": str(output_dir),
            },
        )

        response = self.client.get(f"/analysis/{project.id}")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Analysis - Motor study - BIDSPM Runner", text)
        self.assertIn(str(bids_dir), text)
        self.assertIn(str(output_dir), text)
        self.assertIn('/static/css/analysis.css', text)
        self.assertIn('/static/js/analysis_model_schema.js', text)
        self.assertIn('/static/js/analysis_model_mutations.js', text)
        self.assertIn('/static/js/analysis_model_hints.js', text)

    def test_transformer_builder_project_route_links_back_to_analysis(self):
        project = self.project_manager.create_project("Transformer demo")

        response = self.client.get(f"/transformer-builder/{project.id}")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Transformer Builder", text)
        self.assertIn(f"/analysis/{project.id}", text)

    def test_transformer_builder_route_loads_split_assets(self):
        project = self.project_manager.create_project("Transformer assets demo")

        response = self.client.get(f"/transformer-builder/{project.id}")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn('/static/css/transformer_builder.css', text)
        self.assertIn('/static/js/transformer_builder_path_utils.js', text)
        self.assertIn('/static/js/transformer_builder_model_selection.js', text)
        self.assertIn('/static/js/transformer_builder_browser.js', text)
        self.assertIn('/static/js/transformer_builder_scan_preview.js', text)
        self.assertIn('/static/js/transformer_builder_columns.js', text)
        self.assertIn('/static/js/transformer_builder_pipeline.js', text)

    def test_api_create_project_requires_name(self):
        response = self.client.post("/api/projects", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Project name is required")

    def test_api_projects_crud_and_export_roundtrip(self):
        create_response = self.client.post(
            "/api/projects",
            json={
                "name": "Route coverage",
                "description": "project route smoke test",
                "config": {
                    "models_file": "studies/model.json",
                    "node_name": "dataset_level",
                    "tasks": ["motor"],
                },
            },
        )

        self.assertEqual(create_response.status_code, 201)
        created_project = create_response.get_json()["project"]
        project_id = created_project["id"]

        list_response = self.client.get("/api/projects")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.get_json()["count"], 1)

        update_response = self.client.put(
            f"/api/projects/{project_id}",
            json={
                "name": "Route coverage updated",
                "config": {
                    "models_file": "studies/updated_model.json",
                    "node_name": "subject_level",
                    "tasks": ["motor", "rest"],
                },
            },
        )
        self.assertEqual(update_response.status_code, 200)

        config_response = self.client.get(f"/api/projects/{project_id}/config")
        self.assertEqual(config_response.status_code, 200)
        self.assertEqual(config_response.get_json()["models_file"], "studies/updated_model.json")
        self.assertEqual(config_response.get_json()["tasks"], ["motor", "rest"])

        export_response = self.client.get(f"/api/projects/{project_id}/export")
        self.assertEqual(export_response.status_code, 200)
        exported = export_response.get_json()
        self.assertEqual(exported["MODELS_FILE"], "studies/updated_model.json")
        self.assertEqual(exported["NODE_NAME"], "subject_level")

        delete_response = self.client.delete(f"/api/projects/{project_id}")
        self.assertEqual(delete_response.status_code, 200)

        get_deleted_response = self.client.get(f"/api/projects/{project_id}")
        self.assertEqual(get_deleted_response.status_code, 404)

    def test_api_duplicate_project_creates_copy(self):
        project = self.project_manager.create_project("Original project")

        response = self.client.post(
            f"/api/projects/{project.id}/duplicate",
            json={"name": "Copied project"},
        )

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertEqual(payload["project"]["name"], "Copied project")

        projects = self.project_manager.list_projects()
        self.assertEqual(len(projects), 2)

    def test_api_project_preflight_reports_missing_paths(self):
        project = self.project_manager.create_project(
            "Preflight project",
            config={
                "bids_folder": str(Path(self.temp_dir.name) / "missing-bids"),
                "fmriprep_folder": str(Path(self.temp_dir.name) / "missing-fmriprep"),
                "space": "MNI152NLin2009cAsym",
            },
        )

        response = self.client.get(f"/api/projects/{project.id}/preflight")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["bids_folder"]["status"], "error")
        self.assertEqual(payload["fmriprep_folder"]["status"], "error")
        self.assertEqual(payload["events"]["status"], "na")
        self.assertEqual(payload["space"]["status"], "na")

    def test_load_config_file_returns_defaults_for_missing_path(self):
        response = self.client.get("/load_config_file", query_string={"path": str(Path(self.temp_dir.name) / "missing.json")})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["SPACE"], "MNI152NLin2009cAsym")
        self.assertEqual(payload["TASKS"], [])
        self.assertEqual(payload["container_type"], "apptainer")

    def test_validate_config_rejects_invalid_content(self):
        response = self.client.post(
            "/validate_config",
            json={
                "content": {
                    "WD": self.temp_dir.name,
                    "BIDS_DIR": self.temp_dir.name,
                    "DERIVATIVES_DIR": self.temp_dir.name,
                    "FMRIPREP_DIR": self.temp_dir.name,
                    "SPACE": "MNI152NLin2009cAsym",
                    "FWHM": 6,
                    "TASKS": [],
                }
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"valid": False, "error": "Validation failed"})

    def test_browse_filters_files_by_extension(self):
        root = Path(self.temp_dir.name)
        (root / "alpha.json").write_text("{}", encoding="utf-8")
        (root / "beta.sif").write_text("image", encoding="utf-8")
        (root / "gamma.txt").write_text("ignore", encoding="utf-8")
        (root / "delta").mkdir()

        response = self.client.get(
            "/browse",
            query_string={"path": str(root), "extensions": ".json"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        names = [item["name"] for item in payload["items"]]
        self.assertIn("..", names)
        self.assertIn("delta", names)
        self.assertIn("alpha.json", names)
        self.assertNotIn("beta.sif", names)
        self.assertNotIn("gamma.txt", names)

    def test_file_content_endpoints_roundtrip_json(self):
        target = Path(self.temp_dir.name) / "configs" / "model.json"

        save_response = self.client.post(
            "/file_content",
            json={
                "path": str(target),
                "content": '{"Name":"demo"}',
                "validate_json": True,
            },
        )

        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(save_response.get_json()["success"], True)
        self.assertEqual(target.read_text(encoding="utf-8"), '{\n  "Name": "demo"\n}\n')

        load_response = self.client.get("/file_content", query_string={"path": str(target)})
        self.assertEqual(load_response.status_code, 200)
        self.assertEqual(json.loads(load_response.get_data(as_text=True)), {"Name": "demo"})

    def test_save_file_content_blocks_registered_bids_paths(self):
        bids_dir = Path(self.temp_dir.name) / "bids"
        bids_dir.mkdir()
        self.project_manager.create_project(
            "Protected bids",
            config={"bids_folder": str(bids_dir)},
        )
        target = bids_dir / "sub-01" / "func" / "events.json"

        response = self.client.post(
            "/file_content",
            json={
                "path": str(target),
                "content": "{}",
                "validate_json": True,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["success"], False)

    def test_legacy_config_endpoints_roundtrip(self):
        folder = Path(self.temp_dir.name) / "legacy-configs"

        save_response = self.client.post(
            "/save_config",
            json={
                "config": {"SPACE": "MNI152NLin2009cAsym"},
                "folder": str(folder),
                "filename": "saved.json",
            },
        )

        self.assertEqual(save_response.status_code, 200)
        self.assertTrue((folder / "saved.json").exists())

        list_response = self.client.get("/configs", query_string={"folder": str(folder)})
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.get_json(), ["saved.json"])

        load_response = self.client.get(
            "/load_config",
            query_string={"folder": str(folder), "filename": "saved.json"},
        )
        self.assertEqual(load_response.status_code, 200)
        self.assertEqual(load_response.get_json()["SPACE"], "MNI152NLin2009cAsym")

    def test_run_requires_actions(self):
        response = self.client.post("/run", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "No actions selected")

    def test_run_rejects_missing_project(self):
        response = self.client.post(
            "/run",
            json={"actions": ["smooth"], "project_id": "missing-project"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"], "Project not found")

    def test_stream_unknown_execution_returns_error_event(self):
        response = self.client.get("/stream/missing-execution")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Error: Execution not found", response.get_data(as_text=True))

    def test_stream_existing_execution_returns_log_lines(self):
        log_file = Path(self.temp_dir.name) / "run.log"
        log_file.write_text("line one\nline two\n", encoding="utf-8")
        self.execution_registry.executions["exec-1"] = {
            "log_file": str(log_file),
            "finished": True,
        }

        response = self.client.get("/stream/exec-1")

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("data: line one", text)
        self.assertIn("data: line two", text)

    def test_stop_returns_no_process_running_when_idle(self):
        response = self.client.post("/stop")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "no process running")

    def test_stop_returns_already_finished_when_execution_done(self):
        self.execution_registry.current_execution_id = "exec-1"
        self.execution_registry.executions["exec-1"] = {
            "finished": True,
            "process": None,
            "log_file": str(Path(self.temp_dir.name) / "run.log"),
        }

        response = self.client.post("/stop")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "already finished")

    def test_api_model_create_requires_path(self):
        response = self.client.post("/api/model/create", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["success"], False)
        self.assertEqual(response.get_json()["error"], "No path provided")

    def test_api_model_create_builds_default_model_from_bids(self):
        bids_dir = Path(self.temp_dir.name) / "bids"
        target = Path(self.temp_dir.name) / "models" / "generated_model.json"
        events_file = bids_dir / "sub-01" / "func" / "sub-01_task-motor_events.tsv"
        events_file.parent.mkdir(parents=True, exist_ok=True)
        events_file.write_text(
            "onset\tduration\ttrial_type\n0\t1\tleft\n2\t1\tright\n",
            encoding="utf-8",
        )

        response = self.client.post(
            "/api/model/create",
            json={"path": str(target), "bids_dir": str(bids_dir)},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["success"], True)
        self.assertEqual(payload["source"], "bids_scan")
        self.assertEqual(payload["tasks"], ["motor"])

        model = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(model["Input"]["task"], ["motor"])
        self.assertEqual(model["Nodes"][0]["Level"], "Run")

    def test_validate_model_requires_content(self):
        response = self.client.post("/validate_model", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"valid": False, "error": "No content provided"})

    def test_get_model_tasks_returns_tasks_from_file(self):
        model_file = Path(self.temp_dir.name) / "model.json"
        model_file.write_text(
            '{"Name":"demo","Input":{"task":["motor","rest"]},"Nodes":[]}',
            encoding="utf-8",
        )

        response = self.client.get("/get_model_tasks", query_string={"path": str(model_file)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["tasks"], ["motor", "rest"])

    def test_api_model_hints_requires_object_content(self):
        response = self.client.post(
            "/api/model_hints",
            json={"model_content": ["not", "an", "object"]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Model content must be a JSON object")

    def test_api_model_hints_requires_events_in_bids_dir(self):
        bids_dir = Path(self.temp_dir.name) / "bids"
        bids_dir.mkdir()

        response = self.client.post(
            "/api/model_hints",
            json={
                "bids_dir": str(bids_dir),
                "model_content": {"Name": "demo", "Input": {"task": ["motor"]}, "Nodes": []},
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Event files are required", response.get_json()["error"])

    def test_api_scan_events_columns_reports_missing_directory(self):
        response = self.client.post(
            "/api/scan_events_columns",
            json={"bids_dir": str(Path(self.temp_dir.name) / "missing-bids")},
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("Directory not found", response.get_json()["error"])

    def test_api_scan_events_columns_extracts_preview(self):
        bids_dir = Path(self.temp_dir.name) / "bids"
        events_file = bids_dir / "sub-01" / "func" / "sub-01_task-motor_events.tsv"
        events_file.parent.mkdir(parents=True, exist_ok=True)
        events_file.write_text(
            "onset\tduration\ttrial_type\tresponse_time\n0\t1\tleft\t0.5\n2\t1\tright\t0.7\n",
            encoding="utf-8",
        )

        response = self.client.post(
            "/api/scan_events_columns",
            json={"bids_dir": str(bids_dir), "task_filter": "motor", "preview_max_rows": 1},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["events_files"], 1)
        self.assertEqual(payload["selected_task"], "motor")
        self.assertIn("trial_type", payload["columns"])
        self.assertEqual(payload["sample_headers"], ["onset", "duration", "trial_type", "response_time"])
        self.assertEqual(len(payload["sample_rows"]), 1)
        self.assertTrue(payload["sample_truncated"])

    def test_get_bids_tasks_reads_tasks_from_dataset(self):
        bids_dir = Path(self.temp_dir.name) / "bids"
        events_file = bids_dir / "sub-01" / "func" / "sub-01_task-motor_events.tsv"
        events_file.parent.mkdir(parents=True, exist_ok=True)
        events_file.write_text("onset\tduration\ttrial_type\n0\t1\tleft\n", encoding="utf-8")

        response = self.client.get("/get_bids_tasks", query_string={"path": str(bids_dir)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), ["motor"])

    def test_get_subjects_uses_loaded_config(self):
        config_file = Path(self.temp_dir.name) / "config.json"
        config_file.write_text("{}", encoding="utf-8")

        with patch.object(web_discovery_model_api, "load_config", return_value=SimpleNamespace()), \
             patch.object(web_discovery_model_api, "discover_subjects", return_value=["01", "02"]):
            response = self.client.get("/get_subjects", query_string={"config": str(config_file)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), ["01", "02"])

    def test_estimate_time_uses_loaded_config(self):
        config_file = Path(self.temp_dir.name) / "config.json"
        config_file.write_text("{}", encoding="utf-8")
        fake_config = SimpleNamespace(SUBJECTS=[], TASKS=["motor"])

        with patch.object(web_discovery_model_api, "load_config", return_value=fake_config), \
             patch.object(web_discovery_model_api, "discover_subjects", return_value=["01"]), \
             patch.object(web_discovery_model_api, "estimate_processing_time", return_value={"minutes": 12}):
            response = self.client.post(
                "/estimate_time",
                json={"config": str(config_file), "actions": ["smooth"]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"minutes": 12})

    def test_check_environment_reports_container_tools(self):
        def fake_which(tool):
            if tool == "docker":
                return "/usr/bin/docker"
            return None

        with patch("shutil.which", side_effect=fake_which):
            response = self.client.get("/check_environment")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "docker_available": True,
            "apptainer_available": False,
            "all_features_available": True,
        })

    def test_validate_model_returns_validator_payload(self):
        with patch.object(web_discovery_model_api, "validate_bids_model", return_value={"valid": True, "messages": []}):
            response = self.client.post(
                "/validate_model",
                json={"content": {"Name": "demo", "Nodes": []}},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"valid": True, "messages": []})

    def test_api_detect_spaces_requires_path(self):
        response = self.client.post("/api/detect-spaces", json={})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"spaces": [], "error": "No path provided"})

    def test_api_detect_spaces_finds_matching_space_tokens(self):
        fmriprep_dir = Path(self.temp_dir.name) / "fmriprep"
        bold_file = fmriprep_dir / "sub-01" / "func" / "sub-01_task-motor_space-T1w_desc-preproc_bold.nii.gz"
        bold_file.parent.mkdir(parents=True, exist_ok=True)
        bold_file.write_text("", encoding="utf-8")

        response = self.client.post("/api/detect-spaces", json={"path": str(fmriprep_dir)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["spaces"], ["T1w"])

    def test_api_scan_masks_groups_masks_by_datatype(self):
        preproc_dir = Path(self.temp_dir.name) / "derivatives"
        func_mask = preproc_dir / "sub-01" / "func" / "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-brain_mask.nii.gz"
        anat_mask = preproc_dir / "sub-01" / "anat" / "sub-01_space-T1w_desc-brain_mask.nii.gz"
        func_mask.parent.mkdir(parents=True, exist_ok=True)
        anat_mask.parent.mkdir(parents=True, exist_ok=True)
        func_mask.write_text("", encoding="utf-8")
        anat_mask.write_text("", encoding="utf-8")

        response = self.client.get("/api/scan_masks", query_string={"path": str(preproc_dir)})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        by_datatype = {entry["datatype"]: entry for entry in payload}
        self.assertEqual(by_datatype["func"]["count"], 1)
        self.assertEqual(by_datatype["func"]["entities"]["task"], "motor")
        self.assertEqual(by_datatype["anat"]["entities"]["space"], "T1w")

    def test_api_preflight_tools_reports_tool_availability(self):
        def fake_which(tool):
            if tool in {"docker", "octave"}:
                return f"/usr/bin/{tool}"
            return None

        with patch("shutil.which", side_effect=fake_which):
            response = self.client.get("/api/preflight/tools")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["docker"], {"available": True, "path": "/usr/bin/docker"})
        self.assertEqual(response.get_json()["apptainer"], {"available": False, "path": ""})
        self.assertEqual(response.get_json()["octave"], {"available": True, "path": "/usr/bin/octave"})

    def test_api_stats_subject_coverage_rejects_missing_project(self):
        response = self.client.post(
            "/api/stats_subject_coverage",
            json={"project_id": "missing-project"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"], "Project not found")


if __name__ == "__main__":
    unittest.main()