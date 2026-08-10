import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import lib.core as core
from lib.config import Config, ContainerConfig


def _make_config(root: Path, models_file: str = "") -> Config:
    wd = root / "wd"
    bids_dir = root / "bids"
    derivatives_dir = root / "derivatives"
    fmriprep_dir = derivatives_dir / "fmriprep"
    for path in [wd, bids_dir, derivatives_dir, fmriprep_dir]:
        path.mkdir(parents=True, exist_ok=True)
    return Config(
        WD=wd,
        BIDS_DIR=bids_dir,
        DERIVATIVES_DIR=derivatives_dir,
        SPACE="MNI152NLin2009cAsym",
        FWHM=6.0,
        MODELS_FILE=models_file,
        TASKS=["motor"],
        FMRIPREP_DIR=fmriprep_dir,
        VERBOSITY=2,
        SUBJECTS=["01", "02"],
        CONTAINER_TYPE="docker",
    )


class TestCoreHelpers(unittest.TestCase):
    def test_build_docker_command_maps_model_inside_and_outside_derivatives(self):
        with tempfile.TemporaryDirectory() as tmp_dir, \
             patch("lib.core._seed_cpp_roi_atlas_cache"):
            root = Path(tmp_dir)
            config = _make_config(root)
            model_inside = config.DERIVATIVES_DIR / "models" / "demo.json"
            model_inside.parent.mkdir(parents=True, exist_ok=True)
            model_inside.write_text("{}", encoding="utf-8")

            command, model_path = core.build_docker_command(
                ContainerConfig(container_type="docker", docker_image="bidspm/test:latest"),
                config,
                ["/raw", "/derivatives", "subject", "stats"],
                model_inside,
            )

            self.assertIn("docker", command[0])
            self.assertIn("bidspm/test:latest", command)
            self.assertEqual(model_path, "/derivatives/models/demo.json")

            external_model = root / "external_model.json"
            external_model.write_text("{}", encoding="utf-8")
            external_command, external_model_path = core.build_docker_command(
                ContainerConfig(container_type="docker", docker_image="bidspm/test:latest"),
                config,
                ["/raw", "/derivatives", "subject", "stats"],
                external_model,
            )

            self.assertEqual(external_model_path, "/models/smdl.json")
            self.assertIn(f"{external_model}:/models/smdl.json", external_command)
            self.assertFalse(any("bidspm_overrides" in part for part in external_command))

    def test_build_apptainer_command_creates_runtime_wrapper_and_external_model_bind(self):
        with tempfile.TemporaryDirectory() as tmp_dir, \
             patch("lib.core._seed_cpp_roi_atlas_cache"):
            root = Path(tmp_dir)
            config = _make_config(root)
            image_path = root / "bidspm.sif"
            image_path.write_text("image", encoding="utf-8")
            model_path = root / "model.json"
            model_path.write_text("{}", encoding="utf-8")

            command, model_container_path = core.build_apptainer_command(
                ContainerConfig(container_type="apptainer", apptainer_image=str(image_path)),
                config,
                ["/raw", "/derivatives", "dataset", "stats"],
                model_path,
            )

            self.assertEqual(command[0], "env")
            self.assertIn("APPTAINERENV_PREPEND_PATH=/opt/bidspm_runtime", command[1])
            self.assertIn("apptainer", command)
            self.assertEqual(model_container_path, "/models/smdl.json")
            tmp_runs = list((config.WD / "tmp").glob("run_*"))
            self.assertEqual(len(tmp_runs), 1)
            self.assertTrue((tmp_runs[0] / "octave").exists())
            self.assertFalse(any("bidspm_overrides" in part for part in command))

    def test_build_container_command_dispatches_and_rejects_unknown_type(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = _make_config(Path(tmp_dir))
            with patch("lib.core.build_docker_command", return_value=(["docker"], None)) as build_docker:
                cmd, model_path = core.build_container_command(
                    ContainerConfig(container_type="docker", docker_image="image"),
                    config,
                    ["arg"],
                    None,
                )

            self.assertEqual(cmd, ["docker"])
            self.assertIsNone(model_path)
            build_docker.assert_called_once()

            with self.assertRaises(ValueError):
                core.build_container_command(ContainerConfig(container_type="unknown"), config, [], None)

    def test_discovery_helpers_and_check_subject_processed_cover_expected_shapes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config = _make_config(root)

            subject_dir = config.FMRIPREP_DIR / "sub-01" / "func"
            subject_dir.mkdir(parents=True, exist_ok=True)
            (subject_dir / "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz").write_text("", encoding="utf-8")
            (subject_dir / "sub-01_task-rest_space-T1w_desc-preproc_bold.nii.gz").write_text("", encoding="utf-8")

            bids_func = config.BIDS_DIR / "sub-01" / "func"
            bids_func.mkdir(parents=True, exist_ok=True)
            (bids_func / "sub-01_task-motor_events.tsv").write_text("onset\tduration\n", encoding="utf-8")
            (bids_func / "sub-01_task-rest_events.tsv").write_text("onset\tduration\n", encoding="utf-8")

            smooth_file = config.DERIVATIVES_DIR / "bidspm-preproc" / "sub-01" / "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-smth6.0_bold.nii.gz"
            smooth_file.parent.mkdir(parents=True, exist_ok=True)
            smooth_file.write_text("", encoding="utf-8")

            stats_dir = config.DERIVATIVES_DIR / "bidspm-stats" / "sub-01" / "task-motor_space-MNI152NLin2009cAsym_FWHM-6.0_node-subjectLevel"
            stats_dir.mkdir(parents=True, exist_ok=True)
            (stats_dir / "beta_0001.nii").write_text("", encoding="utf-8")

            self.assertEqual(core.discover_subjects(config), ["01"])
            self.assertEqual(core.discover_tasks(config.BIDS_DIR), ["motor", "rest"])
            self.assertEqual(core.discover_spaces(config.FMRIPREP_DIR, ["motor"]), ["MNI152NLin2009cAsym"])
            self.assertTrue(core.check_subject_processed(config, "01", "motor", "smooth"))
            self.assertTrue(core.check_subject_processed(config, "01", "motor", "stats"))
            self.assertFalse(core.check_subject_processed(config, "02", "motor", "smooth"))

    def test_estimate_processing_time_accounts_for_dataset_actions(self):
        estimate = core.estimate_processing_time(["01", "02"], ["smooth", "dataset"], ["motor", "rest"])

        self.assertEqual(estimate["total_minutes"], 80)
        self.assertEqual(estimate["formatted"], "1h 20m")
        self.assertEqual(estimate["breakdown"]["dataset"], 60)

    def test_validate_bids_model_handles_missing_invalid_and_schema_success(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            missing_result = core.validate_bids_model(root / "missing.json")
            self.assertFalse(missing_result["valid"])

            invalid_json = root / "invalid.json"
            invalid_json.write_text("{invalid}", encoding="utf-8")
            invalid_result = core.validate_bids_model(invalid_json)
            self.assertFalse(invalid_result["valid"])

            model_path = root / "model.json"
            model_path.write_text(json.dumps({"Name": "demo", "BIDSModelVersion": "1.0.0", "Nodes": []}), encoding="utf-8")
            fake_response = SimpleNamespace(json=lambda: {"type": "object"})
            core._fetch_bids_stats_schema.cache_clear()
            with patch("requests.get", return_value=fake_response) as mock_get, \
                 patch("jsonschema.validate"):
                valid_result = core.validate_bids_model(model_path)
                cached_result = core.validate_bids_model(model_path)

            self.assertEqual(valid_result, {"valid": True})
            self.assertEqual(cached_result, {"valid": True})
            mock_get.assert_called_once()

    def test_model_normalization_helpers_fix_legacy_shapes(self):
        model = {
            "Nodes": [
                {
                    "Model": {"X": ["trial_type"]},
                    "Contrasts": [{"Name": "go", "ConditionList": ["go"], "Weights": [1], "Type": "t"}],
                    "DummyContrasts": {"Type": "pass", "Contrasts": [1]},
                    "Software": ["SPM", "MarsBaR"],
                    "Transformations": {"Instructions": []},
                }
            ]
        }

        changes = core._prepare_model_content_for_execution(model)

        self.assertEqual(len(changes), 3)
        node = model["Nodes"][0]
        self.assertEqual(node["Contrasts"][0]["Test"], "t")
        self.assertEqual(node["DummyContrasts"]["Test"], "pass")
        self.assertEqual(node["Model"]["Type"], "glm")
        self.assertEqual(node["Software"], {"SPM": {}, "MarsBaR": {}})
        self.assertNotIn("Transformations", node)

    def test_check_empty_contrasts_reports_missing_fields(self):
        issues = core._check_empty_contrasts(
            {
                "Steps": [
                    {
                        "Level": "Run",
                        "Contrasts": [
                            {"Name": "", "ConditionList": [], "Weights": []},
                            {"ConditionList": ["go"]},
                        ],
                    }
                ]
            }
        )

        self.assertTrue(any("missing 'Name'" in issue for issue in issues))
        self.assertTrue(any("empty 'ConditionList'" in issue for issue in issues))
        self.assertTrue(any("empty 'Weights'" in issue for issue in issues))

    def test_pipeline_validate_config_checks_file_json_and_schema(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            missing_pipeline = core.Pipeline(core.PipelineOptions(actions=["smooth"], config_file=str(root / "missing.json")))
            self.assertFalse(missing_pipeline.validate_config())

            config_path = root / "config.json"
            config_path.write_text("{}", encoding="utf-8")
            invalid_json_pipeline = core.Pipeline(core.PipelineOptions(actions=["smooth"], config_file=str(config_path)))
            with patch("docs.json_validator.JSONValidator.is_valid_json", return_value=False):
                self.assertFalse(invalid_json_pipeline.validate_config())

            valid_pipeline = core.Pipeline(core.PipelineOptions(actions=["smooth"], config_file=str(config_path)))
            with patch("docs.json_validator.JSONValidator.is_valid_json", return_value=True), \
                 patch("docs.json_validator.JSONValidator.validate_with_schema", return_value=True):
                self.assertTrue(valid_pipeline.validate_config())

    def test_pipeline_resolve_model_file_prefers_cli_cwd_and_config_derivatives(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config = _make_config(root, models_file="saved_model.json")
            cli_model = root / "cwd_model.json"
            cli_model.write_text("{}", encoding="utf-8")
            derivative_model = config.DERIVATIVES_DIR / "models" / "saved_model.json"
            derivative_model.parent.mkdir(parents=True, exist_ok=True)
            derivative_model.write_text("{}", encoding="utf-8")

            pipeline = core.Pipeline(core.PipelineOptions(actions=["stats"], model_file="cwd_model.json", skip_validation=True))
            pipeline.config = config
            original_cwd = os.getcwd()
            os.chdir(root)
            try:
                self.assertTrue(pipeline._resolve_model_file())
            finally:
                os.chdir(original_cwd)

            self.assertEqual(pipeline.model_file_path, cli_model.resolve())

            config_pipeline = core.Pipeline(core.PipelineOptions(actions=["stats"], skip_validation=True))
            config_pipeline.config = config
            self.assertTrue(config_pipeline._resolve_model_file())
            self.assertEqual(config_pipeline.model_file_path, derivative_model)

    def test_pipeline_resolve_model_file_sanitizes_legacy_model(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config = _make_config(root)
            model_path = root / "legacy_model.json"
            model_path.write_text(
                json.dumps(
                    {
                        "Nodes": [
                            {
                                "Model": {"X": ["trial_type"]},
                                "Software": "SPM",
                                "Transformations": {"Instructions": []},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            pipeline = core.Pipeline(core.PipelineOptions(actions=["stats"], model_file=str(model_path), skip_validation=True))
            pipeline.config = config
            self.assertTrue(pipeline._resolve_model_file())

            self.assertIsNotNone(pipeline.execution_model_temp_path)
            self.assertTrue(pipeline.execution_model_temp_path.exists())
            self.assertIn("Execution model sanitized", pipeline.warnings[0])
            pipeline._cleanup_execution_model_file()

    def test_pipeline_subject_selection_and_skip_logic(self):
        config = _make_config(Path(tempfile.mkdtemp()))

        pilot_pipeline = core.Pipeline(core.PipelineOptions(actions=["smooth"], pilot=True))
        pilot_pipeline.config = config
        with patch("lib.core.random.choice", return_value="02"):
            self.assertEqual(pilot_pipeline.get_subjects_to_process(), ["02"])

        skip_pipeline = core.Pipeline(core.PipelineOptions(actions=["smooth", "stats"]))
        skip_pipeline.config = config
        with patch("lib.core.check_subject_processed", side_effect=[True, True]):
            self.assertTrue(skip_pipeline._skip_if_processed("01", "motor"))

    def test_pipeline_run_parallelizes_subjects_and_matches_sequential_outcome(self):
        config = _make_config(Path(tempfile.mkdtemp()))
        outcomes = {"01": True, "02": False, "03": True, "04": True}

        def run_with_workers(stats_workers):
            pipeline = core.Pipeline(core.PipelineOptions(
                actions=["stats"], force=True, stats_workers=stats_workers
            ))
            pipeline.config = config
            pipeline.setup = lambda: True
            pipeline.get_subjects_to_process = lambda: list(outcomes.keys())
            pipeline._process_subject = lambda subject, task: outcomes[subject]
            with patch("lib.core.validate_space_availability", return_value=True) as mock_space, \
                 patch("lib.core.validate_events_availability", return_value=True) as mock_events, \
                 patch("lib.core.ensure_derivatives_dataset_description"), \
                 patch("lib.core.cleanup_tmp_directories"):
                result = pipeline.run()
            # Validation must run exactly once per subject in the main thread,
            # regardless of how many worker threads process them.
            self.assertEqual(mock_space.call_count, len(outcomes))
            self.assertEqual(mock_events.call_count, len(outcomes))
            return result

        sequential = run_with_workers(1)
        parallel = run_with_workers(4)

        self.assertEqual(sorted(sequential.subjects_processed), ["01", "03", "04"])
        self.assertEqual(sorted(sequential.subjects_failed), ["02"])
        self.assertEqual(sorted(sequential.subjects_processed), sorted(parallel.subjects_processed))
        self.assertEqual(sorted(sequential.subjects_failed), sorted(parallel.subjects_failed))

    def test_pipeline_dry_run_with_stats_workers_matches_sequential_commands(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config = _make_config(root)
            model_path = root / "model.json"
            model_path.write_text("{}", encoding="utf-8")
            subjects = ["01", "02", "03"]

            def run_with_workers(stats_workers):
                pipeline = core.Pipeline(core.PipelineOptions(
                    actions=["stats"], force=True, dry_run=True,
                    stats_workers=stats_workers
                ))
                pipeline.config = config
                pipeline.model_file_path = model_path
                pipeline.container_config = ContainerConfig(container_type="docker", docker_image="bidspm/test:latest")
                pipeline.setup = lambda: True
                pipeline.get_subjects_to_process = lambda: list(subjects)
                with patch("lib.core.validate_space_availability", return_value=True), \
                     patch("lib.core.validate_events_availability", return_value=True), \
                     patch("lib.core.ensure_derivatives_dataset_description"), \
                     patch("lib.core.cleanup_tmp_directories"), \
                     patch("lib.core._seed_cpp_roi_atlas_cache"):
                    result = pipeline.run()
                return result, pipeline.dry_run_commands

            sequential_result, sequential_commands = run_with_workers(1)
            parallel_result, parallel_commands = run_with_workers(3)

            self.assertEqual(sorted(sequential_result.subjects_processed), subjects)
            self.assertEqual(sorted(parallel_result.subjects_processed), subjects)
            self.assertEqual(len(sequential_commands), len(subjects))
            # Each run's per-subject tmp bind mount embeds a fresh timestamp, so
            # normalize it away before comparing that both runs built the same
            # underlying commands.
            normalize = lambda commands: sorted(re.sub(r"run_\d+_\d+_\d+", "run_TS", cmd) for cmd in commands)
            self.assertEqual(normalize(sequential_commands), normalize(parallel_commands))


class TestProcessSubjectDelegation(unittest.TestCase):
    def test_process_subject_calls_smooth_container_action(self):
        """_process_subject must invoke _run_container_action("smooth", ...) directly."""
        import tempfile
        from lib.core import Pipeline, PipelineOptions
        opts = PipelineOptions(actions=["smooth"], config_file="config/config.json")
        pipeline = Pipeline(opts)
        pipeline.config = _make_config(Path(tempfile.mkdtemp()))
        pipeline.container_config = ContainerConfig(
            container_type="docker", docker_image="test:latest"
        )
        pipeline.model_file_path = None
        pipeline.stats_node_name = None

        calls = []
        with patch.object(pipeline, "_run_container_action", side_effect=lambda *a: calls.append(a) or True):
            pipeline._process_subject("01", "motor")

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], ("smooth", "01", "motor"))