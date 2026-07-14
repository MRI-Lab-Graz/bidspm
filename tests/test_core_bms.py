import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lib.core as core
from lib.config import Config, ContainerConfig


def _make_config(root: Path) -> Config:
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
        MODELS_FILE="",
        TASKS=["motor"],
        FMRIPREP_DIR=fmriprep_dir,
        VERBOSITY=2,
        SUBJECTS=["01"],
        CONTAINER_TYPE="apptainer",
    )


class TestResolveModelsDir(unittest.TestCase):
    def test_raises_when_not_a_directory(self):
        with self.assertRaises(ValueError):
            core.resolve_models_dir("/no/such/directory")

    def test_raises_when_fewer_than_two_smdl_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "model1_smdl.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                core.resolve_models_dir(tmp)
            self.assertIn("at least 2", str(ctx.exception))

    def test_resolves_when_two_or_more_smdl_files_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "model1_smdl.json").write_text("{}", encoding="utf-8")
            (Path(tmp) / "model2_smdl.json").write_text("{}", encoding="utf-8")
            (Path(tmp) / "unrelated.json").write_text("{}", encoding="utf-8")
            resolved = core.resolve_models_dir(tmp)
            self.assertEqual(resolved, Path(tmp).expanduser().resolve())


class TestRunBms(unittest.TestCase):
    def _models_dir(self, tmp: str) -> str:
        (Path(tmp) / "model1_smdl.json").write_text("{}", encoding="utf-8")
        (Path(tmp) / "model2_smdl.json").write_text("{}", encoding="utf-8")
        return tmp

    def test_returns_error_when_models_dir_invalid(self):
        result = core.run_bms(
            config_file="ignored.json", container_config_file=None, models_dir="/no/such/dir",
        )
        self.assertFalse(result["success"])
        self.assertIn("Models directory not found", result["errors"][0])

    def test_returns_error_when_no_container_config_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            models_dir = self._models_dir(tmp)
            config = _make_config(Path(tmp))
            with patch("lib.core.load_config", return_value=config), \
                 patch("lib.config.auto_select_container_config", return_value=None):
                result = core.run_bms(
                    config_file="ignored.json", container_config_file=None, models_dir=models_dir,
                )
            self.assertFalse(result["success"])
            self.assertIn("requires container execution", result["errors"][0])

    def test_dry_run_returns_command_without_executing(self):
        with tempfile.TemporaryDirectory() as tmp:
            models_dir = self._models_dir(tmp)
            config = _make_config(Path(tmp))
            container_config = ContainerConfig(container_type="apptainer", apptainer_image="bidspm.sif")
            container_file = Path(tmp) / "container.json"
            container_file.write_text("{}", encoding="utf-8")

            with patch("lib.core.load_config", return_value=config), \
                 patch("lib.core.load_container_config", return_value=container_config), \
                 patch("lib.core.check_command"), \
                 patch("lib.core.build_container_command", return_value=(["apptainer", "run"], "/mnt/models")), \
                 patch("lib.core.run_command") as mock_run_command:
                result = core.run_bms(
                    config_file="ignored.json",
                    container_config_file=str(container_file),
                    models_dir=models_dir,
                    dry_run=True,
                )

            self.assertTrue(result["success"])
            self.assertEqual(result["dry_run_commands"], ["apptainer run"])
            mock_run_command.assert_not_called()

    def test_real_run_reports_failure_from_run_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            models_dir = self._models_dir(tmp)
            config = _make_config(Path(tmp))
            container_config = ContainerConfig(container_type="docker", docker_image="bidspm:latest")
            container_file = Path(tmp) / "container.json"
            container_file.write_text("{}", encoding="utf-8")

            with patch("lib.core.load_config", return_value=config), \
                 patch("lib.core.load_container_config", return_value=container_config), \
                 patch("lib.core.check_docker_availability"), \
                 patch("lib.core.build_container_command", return_value=(["docker", "run"], "/mnt/models")), \
                 patch("lib.core.run_command", return_value=False) as mock_run_command:
                result = core.run_bms(
                    config_file="ignored.json",
                    container_config_file=str(container_file),
                    models_dir=models_dir,
                    participant_label=["01", "02"],
                )

            self.assertFalse(result["success"])
            self.assertIn("BMS run failed", result["errors"][0])
            mock_run_command.assert_called_once()


if __name__ == "__main__":
    unittest.main()
