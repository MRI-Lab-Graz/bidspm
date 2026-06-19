import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from lib.config import auto_select_container_config
from lib.config import detect_platform_and_suggest_container
from lib.config import load_config
from lib.config import load_container_config
from lib.utils import StreamCommandResult
from lib.utils import check_command
from lib.utils import check_docker_availability
from lib.utils import cleanup_tmp_directories
from lib.utils import ensure_derivatives_dataset_description
from lib.utils import generate_log_filename
from lib.utils import get_container_model_path
from lib.utils import log
from lib.utils import run_command
from lib.utils import run_streaming_command
from lib.utils import validate_space_availability


class TestConfigHelpers(unittest.TestCase):
    def test_load_config_reads_session_and_timeout_fields(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "WD": str(root / "work"),
                        "BIDS_DIR": str(root / "bids"),
                        "DERIVATIVES_DIR": str(root / "derivatives"),
                        "FMRIPREP_DIR": str(root / "fmriprep"),
                        "SPACE": "MNI152NLin2009cAsym",
                        "FWHM": 6,
                        "MODELS_FILE": "studies/model.json",
                        "TASKS": ["motor"],
                        "VERBOSITY": 2,
                        "SUBJECTS": ["01"],
                        "ROI": True,
                        "ROI_CONFIG": {"atlas": "aal"},
                        "skip_validation": True,
                        "container_type": "Apptainer",
                        "LOCAL_ACTION_TIMEOUT_SECONDS": 0,
                        "SMOOTH_TIMEOUT_SECONDS": 0,
                        "STATS_TIMEOUT_SECONDS": 0,
                        "DATASET_TIMEOUT_SECONDS": 0,
                        "SESSION": "01",
                        "RUNS": ["1", "2"],
                    }
                ),
                encoding="utf-8",
            )

            old_cwd = os.getcwd()
            os.chdir(root)
            try:
                config = load_config(str(config_path))
            finally:
                os.chdir(old_cwd)

            selection = json.loads((root / "selection.json").read_text(encoding="utf-8"))
            self.assertEqual(selection["bold"]["ses"], "01")
            self.assertEqual(selection["bold"]["run"], ["1", "2"])
            self.assertEqual(config.WD, root / "work")
            self.assertEqual(config.BIDS_DIR, root / "bids")
            self.assertEqual(config.CONTAINER_TYPE, "apptainer")
            self.assertEqual(config.LOCAL_ACTION_TIMEOUT_SECONDS, 1)
            self.assertEqual(config.SMOOTH_TIMEOUT_SECONDS, 1)
            self.assertEqual(config.STATS_TIMEOUT_SECONDS, 1)
            self.assertEqual(config.DATASET_TIMEOUT_SECONDS, 1)
            self.assertTrue(config.SKIP_VALIDATION)
            self.assertEqual(config.SUBJECTS, ["01"])

    def test_load_container_config_supports_valid_payload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "container.json"
            config_path.write_text(
                json.dumps(
                    {
                        "container_type": "apptainer",
                        "docker_image": "bidspm/test:latest",
                        "apptainer_image": "/tmp/test.sif",
                    }
                ),
                encoding="utf-8",
            )

            config = load_container_config(str(config_path))

            self.assertEqual(config.container_type, "apptainer")
            self.assertEqual(config.docker_image, "bidspm/test:latest")
            self.assertEqual(config.apptainer_image, "/tmp/test.sif")

    def test_load_container_config_rejects_invalid_type(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "container.json"
            config_path.write_text(json.dumps({"container_type": "podman"}), encoding="utf-8")

            with patch("lib.utils.log_error", side_effect=RuntimeError("invalid")) as mock_log_error:
                with self.assertRaisesRegex(RuntimeError, "invalid"):
                    load_container_config(str(config_path))

            mock_log_error.assert_called_once()

    def test_detect_platform_and_suggest_container_handles_linux_variants(self):
        with patch("lib.config.platform.system", return_value="Linux"), \
             patch("lib.config.subprocess.run") as mock_run:
            mock_run.side_effect = [FileNotFoundError(), FileNotFoundError()]
            detected, message = detect_platform_and_suggest_container()

        self.assertIsNone(detected)
        self.assertIn("Neither Docker nor Apptainer found", message)

        with patch("lib.config.platform.system", return_value="Linux"), \
             patch("lib.config.subprocess.run") as mock_run:
            mock_run.side_effect = [FileNotFoundError(), MagicMock()]
            detected, message = detect_platform_and_suggest_container()

        self.assertEqual(detected, "apptainer")
        self.assertIn("HPC environment", message)

        with patch("lib.config.platform.system", return_value="Darwin"):
            detected, message = detect_platform_and_suggest_container()

        self.assertEqual(detected, "docker")
        self.assertIn("macOS", message)

    def test_auto_select_container_config_uses_matching_candidate(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            containers_dir = root / "containers"
            containers_dir.mkdir()
            (containers_dir / "container_apptainer.json").write_text(
                json.dumps({"container_type": "apptainer"}),
                encoding="utf-8",
            )
            (containers_dir / "container.json").write_text(
                json.dumps({"container_type": "docker"}),
                encoding="utf-8",
            )

            old_cwd = os.getcwd()
            os.chdir(root)
            try:
                with patch("lib.config.detect_platform_and_suggest_container", return_value=("apptainer", "test")):
                    selected = auto_select_container_config()
            finally:
                os.chdir(old_cwd)

        self.assertEqual(selected, "containers/container_apptainer.json")


class TestUtilsHelpers(unittest.TestCase):
    def test_run_streaming_command_captures_output(self):
        seen = []

        result = run_streaming_command(
            [sys.executable, "-c", "print('hello from bidspm')"],
            capture_output=True,
            on_output=seen.append,
        )

        self.assertTrue(result.success)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(result.timed_out)
        self.assertIn("hello from bidspm", result.output)
        self.assertEqual(seen, ["hello from bidspm"])

    def test_run_streaming_command_times_out(self):
        result = run_streaming_command(
            [sys.executable, "-c", "import time; time.sleep(1.0)"],
            capture_output=True,
            timeout=0.1,
        )

        self.assertFalse(result.success)
        self.assertTrue(result.timed_out)
        self.assertNotEqual(result.returncode, 0)

    def test_generate_log_filename_uses_model_stem(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            old_cwd = os.getcwd()
            os.chdir(tmp_dir)
            try:
                log_name = generate_log_filename("studies/model.json")
            finally:
                os.chdir(old_cwd)

        self.assertIn("logs/model_", log_name)
        self.assertTrue(log_name.endswith(".log"))

    def test_check_command_delegates_missing_binary_to_log_error(self):
        with patch("lib.utils.shutil.which", return_value=None), \
             patch("lib.utils.log_error", side_effect=RuntimeError("missing")) as mock_log_error:
            with self.assertRaisesRegex(RuntimeError, "missing"):
                check_command("octave")

        mock_log_error.assert_called_once_with("'octave' is required but not installed or in PATH.")

    def test_check_docker_availability_handles_missing_and_not_running(self):
        with patch("lib.utils.shutil.which", return_value=None), \
             patch("lib.utils.log_error", side_effect=SystemExit("missing")) as mock_log_error:
            with self.assertRaisesRegex(SystemExit, "missing"):
                check_docker_availability()
        mock_log_error.assert_called_once()

        with patch("lib.utils.shutil.which", return_value="/usr/bin/docker"), \
             patch("lib.utils.subprocess.run", return_value=SimpleNamespace(returncode=1)), \
             patch("lib.utils.log_error", side_effect=SystemExit("stopped")) as mock_log_error:
            with self.assertRaisesRegex(SystemExit, "stopped"):
                check_docker_availability()
        mock_log_error.assert_called_once()

    def test_run_command_handles_success_and_failure_paths(self):
        with patch(
            "lib.utils.run_streaming_command",
            return_value=StreamCommandResult(success=True, returncode=0, output="all good"),
        ), patch("lib.utils.log") as mock_log:
            self.assertTrue(run_command(["fake"], capture_output=True))
        mock_log.assert_called_with("all good")

        with patch(
            "lib.utils.run_streaming_command",
            return_value=StreamCommandResult(success=False, returncode=3, output="failed output"),
        ), patch("lib.utils.log_error_non_fatal") as mock_non_fatal, \
             patch("lib.utils.log") as mock_log:
            self.assertFalse(run_command(["fake"], capture_output=False))

        mock_non_fatal.assert_called_once()
        mock_log.assert_called_once()

    def test_log_is_safe_under_concurrent_writes(self):
        # --stats-workers runs Pipeline._process_subject for several subjects on
        # separate threads at once; each of those can call into lib.utils.log()
        # (e.g. via run_command). Every line written must stay intact -- no
        # interleaved/corrupted lines from concurrent file appends.
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "concurrent.log"
            with patch("lib.utils.LOG_FILE", str(log_path)):
                threads = [
                    threading.Thread(target=log, args=(f"message-{i}",))
                    for i in range(40)
                ]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 40)
            seen = {f"message-{i}" for i in range(40)}
            for line in lines:
                # Each line is "<timestamp> message-N" with nothing else mixed in.
                message = line.split(" ", 2)[-1]
                self.assertIn(message, seen)
                seen.discard(message)
            self.assertEqual(seen, set())

    def test_validate_space_availability_checks_subjects_and_spaces(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            fmriprep_dir = root / "fmriprep"
            good_file = fmriprep_dir / "sub-01" / "func" / "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
            bad_file = fmriprep_dir / "sub-02" / "func" / "sub-02_task-motor_space-T1w_desc-preproc_bold.nii.gz"
            good_file.parent.mkdir(parents=True, exist_ok=True)
            good_file.write_text("", encoding="utf-8")
            bad_file.parent.mkdir(parents=True, exist_ok=True)
            bad_file.write_text("", encoding="utf-8")

            config = SimpleNamespace(FMRIPREP_DIR=fmriprep_dir, SPACE="MNI152NLin2009cAsym")

            self.assertTrue(validate_space_availability(config, ["01"], "motor"))
            self.assertFalse(validate_space_availability(config, ["01", "02"], "motor"))

    def test_ensure_derivatives_dataset_description_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            derivatives_dir = Path(tmp_dir) / "derivatives"
            derivatives_dir.mkdir()

            ensure_derivatives_dataset_description(derivatives_dir)

            dataset_description = json.loads(
                (derivatives_dir / "dataset_description.json").read_text(encoding="utf-8")
            )
            self.assertEqual(dataset_description["DatasetType"], "derivative")
            self.assertEqual(dataset_description["GeneratedBy"][0]["Name"], "bidspm-runner")

    def test_cleanup_tmp_directories_removes_old_entries(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            tmp_parent = root / "tmp"
            old_dir = tmp_parent / "old"
            new_dir = tmp_parent / "new"
            old_dir.mkdir(parents=True)
            new_dir.mkdir(parents=True)

            stale_time = time.time() - (48 * 3600)
            os.utime(old_dir, (stale_time, stale_time))

            config = SimpleNamespace(WD=root)
            cleanup_tmp_directories(config, max_age_hours=24)

            self.assertFalse(old_dir.exists())
            self.assertTrue(new_dir.exists())

    def test_get_container_model_path_prefers_derivatives_relative_path(self):
        derivatives_dir = Path("/tmp/derivatives")
        inside_model = derivatives_dir / "models" / "example.json"
        outside_model = Path("/tmp/studies/model.json")

        self.assertEqual(
            get_container_model_path(inside_model, derivatives_dir),
            "/derivatives/models/example.json",
        )
        self.assertEqual(get_container_model_path(outside_model, derivatives_dir), "/models/smdl.json")


if __name__ == "__main__":
    unittest.main()