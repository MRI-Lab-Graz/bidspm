import json
import os
import subprocess
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
        CONTAINER_TYPE="local",
    )


class TestCoreHelpers(unittest.TestCase):
    def test_detect_matlab_licensed_reports_toolbox_capabilities(self):
        with patch(
            "lib.core.subprocess.run",
            side_effect=[
                SimpleNamespace(returncode=0, stdout="ok", stderr=""),
                SimpleNamespace(stdout="1\n0\n1\n"),
            ],
        ):
            caps = core._detect_matlab_licensed("/usr/bin/matlab")

        self.assertEqual(caps.environment, core.MatlabEnvironment.MATLAB_LICENSED)
        self.assertEqual(caps.path, "/usr/bin/matlab")
        self.assertTrue(caps.can_compile_mex)
        self.assertTrue(caps.has_statistics_toolbox)
        self.assertFalse(caps.has_image_processing_toolbox)
        self.assertTrue(caps.can_use_parallel)

    def test_detect_matlab_licensed_handles_license_and_timeout_paths(self):
        with patch(
            "lib.core.subprocess.run",
            return_value=SimpleNamespace(returncode=1, stdout="", stderr="license checkout failed"),
        ):
            license_caps = core._detect_matlab_licensed("/usr/bin/matlab")

        self.assertEqual(license_caps.environment, core.MatlabEnvironment.MATLAB_LICENSED)
        self.assertFalse(license_caps.can_run_arbitrary_scripts)
        self.assertIn("license unavailable", license_caps.limitations[0].lower())

        with patch("lib.core.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["matlab"], timeout=30)):
            timeout_caps = core._detect_matlab_licensed("/usr/bin/matlab")

        self.assertEqual(timeout_caps.environment, core.MatlabEnvironment.MATLAB_LICENSED)
        self.assertIn("slow to respond", timeout_caps.limitations[0])

    def test_detect_octave_success_and_failure_paths(self):
        with patch(
            "lib.core.subprocess.run",
            side_effect=[
                SimpleNamespace(stdout="GNU Octave, version 8.4.0\n"),
                SimpleNamespace(stdout="package list"),
            ],
        ):
            caps = core._detect_octave("/usr/bin/octave")

        self.assertEqual(caps.environment, core.MatlabEnvironment.OCTAVE)
        self.assertEqual(caps.version, "8.4.0")
        self.assertFalse(caps.can_use_parallel)

        with patch("lib.core.subprocess.run", side_effect=RuntimeError("boom")):
            fallback_caps = core._detect_octave("/usr/bin/octave")

        self.assertIn("error detecting capabilities", fallback_caps.limitations[0])

    def test_check_feature_availability_handles_none_and_standalone(self):
        none_caps = core.MatlabCapabilities(environment=core.MatlabEnvironment.NONE)
        standalone_caps = core.MatlabCapabilities(environment=core.MatlabEnvironment.MATLAB_STANDALONE)

        none_features = core.check_feature_availability(none_caps)
        standalone_features = core.check_feature_availability(standalone_caps)
        container_features = core.check_feature_availability(none_caps, using_container=True)

        self.assertFalse(none_features.smooth)
        self.assertIn("all", none_features.unavailable_reasons)
        self.assertFalse(standalone_features.roi_analysis)
        self.assertIn("custom_contrasts", standalone_features.unavailable_reasons)
        self.assertTrue(container_features.smooth)

    def test_build_docker_command_maps_model_inside_and_outside_derivatives(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
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

    def test_build_apptainer_command_creates_runtime_wrapper_and_external_model_bind(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
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

            smooth_file = config.DERIVATIVES_DIR / "bidspm-preproc" / "sub-01" / "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
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
            core._schema_cache.clear()
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
                    actions=["stats"], local=True, force=True, dry_run=True,
                    stats_workers=stats_workers
                ))
                pipeline.config = config
                pipeline.model_file_path = model_path
                pipeline.matlab_caps = core.MatlabCapabilities(
                    environment=core.MatlabEnvironment.OCTAVE, path="/usr/bin/octave"
                )
                pipeline.setup = lambda: True
                pipeline.get_subjects_to_process = lambda: list(subjects)
                with patch("lib.core.validate_space_availability", return_value=True), \
                     patch("lib.core.validate_events_availability", return_value=True), \
                     patch("lib.core.ensure_derivatives_dataset_description"), \
                     patch("lib.core.cleanup_tmp_directories"):
                    result = pipeline.run()
                return result, pipeline.dry_run_commands

            sequential_result, sequential_commands = run_with_workers(1)
            parallel_result, parallel_commands = run_with_workers(3)

            self.assertEqual(sorted(sequential_result.subjects_processed), subjects)
            self.assertEqual(sorted(parallel_result.subjects_processed), subjects)
            self.assertEqual(len(sequential_commands), len(subjects))
            self.assertEqual(sorted(sequential_commands), sorted(parallel_commands))

    def test_execute_matlab_script_prefixes_streamed_output_with_subject(self):
        config = _make_config(Path(tempfile.mkdtemp()))
        logged_lines = []
        pipeline = core.Pipeline(core.PipelineOptions(actions=["smooth"], on_progress=logged_lines.append))
        pipeline.config = config
        pipeline.matlab_caps = core.MatlabCapabilities(environment=core.MatlabEnvironment.OCTAVE, path="/usr/bin/octave")

        fake_proc = SimpleNamespace(
            stdout=["line one\n", "line two\n"],
            wait=lambda timeout=None: 0,
            returncode=0,
        )
        with patch("lib.core.subprocess.Popen", return_value=fake_proc):
            self.assertTrue(pipeline._execute_matlab_script("disp('x')", "smooth", "01", "motor"))

        # Concurrent subjects interleave their streamed output, so every raw
        # output line must be tagged with the subject it came from.
        self.assertIn("[01] line one", logged_lines)
        self.assertIn("[01] line two", logged_lines)

    def test_pipeline_generates_local_scripts_and_handles_dry_run_timeout(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config = _make_config(root)
            model_path = root / "model.json"
            model_path.write_text("{}", encoding="utf-8")

            pipeline = core.Pipeline(core.PipelineOptions(actions=["stats"], node_name="subject_level", dry_run=True))
            pipeline.config = config
            pipeline.model_file_path = model_path
            pipeline.matlab_caps = core.MatlabCapabilities(environment=core.MatlabEnvironment.OCTAVE, path="/usr/bin/octave")

            script = pipeline._generate_matlab_script("stats", "01", "motor")
            self.assertIn("'node_name', 'subject_level'", script)
            self.assertIn(str(model_path.absolute()), script)
            self.assertTrue(pipeline._execute_matlab_script(script, "stats", "01", "motor"))
            self.assertTrue(any("/usr/bin/octave" in command for command in pipeline.dry_run_commands))

            timeout_pipeline = core.Pipeline(core.PipelineOptions(actions=["smooth"]))
            timeout_pipeline.config = config
            timeout_pipeline.matlab_caps = core.MatlabCapabilities(environment=core.MatlabEnvironment.OCTAVE, path="/usr/bin/octave")
            with patch("lib.core.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["octave"], timeout=10, output="partial", stderr="oops")):
                self.assertFalse(timeout_pipeline._execute_matlab_script("disp('x')", "smooth", "01", "motor"))
            self.assertTrue(any("timed out" in error for error in timeout_pipeline.errors))

    def test_pipeline_get_local_env_adds_project_and_octave_paths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "external" / "octave" / "bin").mkdir(parents=True, exist_ok=True)
            (root / "external" / "octave" / "lib" / "octave" / "9.1.0").mkdir(parents=True, exist_ok=True)
            pipeline = core.Pipeline(core.PipelineOptions(actions=["smooth"]))

            original_cwd = os.getcwd()
            os.chdir(root)
            try:
                env = pipeline._get_local_env()
            finally:
                os.chdir(original_cwd)

            self.assertEqual(env["BIDSPM_PROJECT_ROOT"], str(root.resolve()))
            self.assertTrue(env["PATH"].startswith(str(root / "external" / "octave" / "bin")))
            self.assertIn(str(root / "external" / "octave" / "lib" / "octave" / "9.1.0"), env["LD_LIBRARY_PATH"])