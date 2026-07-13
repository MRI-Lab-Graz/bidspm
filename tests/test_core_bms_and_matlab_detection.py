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


class TestDetectMatlabEnvironmentOrchestration(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = Path.cwd()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        import os
        os.chdir(self._tmp.name)
        self.addCleanup(os.chdir, str(self._orig_cwd))

    def test_prefers_licensed_matlab_when_available(self):
        sentinel = core.MatlabCapabilities(environment=core.MatlabEnvironment.MATLAB_LICENSED, path="/usr/bin/matlab")
        with patch("lib.core.shutil.which", side_effect=lambda name: "/usr/bin/matlab" if name == "matlab" else None), \
             patch("lib.core._detect_matlab_licensed", return_value=sentinel):
            caps = core.detect_matlab_environment()
        self.assertEqual(caps, sentinel)

    def test_falls_back_to_octave_when_matlab_licensed_detection_fails(self):
        with patch("lib.core.shutil.which", side_effect=lambda name: "/usr/bin/matlab" if name == "matlab" else None), \
             patch("lib.core._detect_matlab_licensed", return_value=None), \
             patch("lib.core._detect_octave") as mock_detect_octave:
            mock_detect_octave.return_value = core.MatlabCapabilities(environment=core.MatlabEnvironment.OCTAVE)
            core.detect_matlab_environment()
        mock_detect_octave.assert_not_called()  # no system/local octave in an empty tmp cwd either

    def test_uses_local_octave_directory_when_present(self):
        local_octave = Path("external/octave/bin/octave-cli")
        local_octave.parent.mkdir(parents=True)
        local_octave.write_text("", encoding="utf-8")
        sentinel = core.MatlabCapabilities(environment=core.MatlabEnvironment.OCTAVE, path=str(local_octave.absolute()))

        with patch("lib.core.shutil.which", return_value=None), \
             patch("lib.core._detect_octave", return_value=sentinel) as mock_detect_octave:
            caps = core.detect_matlab_environment()

        mock_detect_octave.assert_called_once_with(str(local_octave.absolute()))
        self.assertEqual(caps, sentinel)

    def test_uses_system_octave_when_no_local_install(self):
        sentinel = core.MatlabCapabilities(environment=core.MatlabEnvironment.OCTAVE, path="/usr/bin/octave")

        with patch("lib.core.shutil.which", side_effect=lambda name: "/usr/bin/octave" if name == "octave" else None), \
             patch("lib.core._detect_octave", return_value=sentinel) as mock_detect_octave:
            caps = core.detect_matlab_environment()

        mock_detect_octave.assert_called_once_with("/usr/bin/octave")
        self.assertEqual(caps, sentinel)

    def test_uses_spm_standalone_when_present(self):
        standalone = Path("external/spm12_standalone/run_spm12.sh")
        standalone.parent.mkdir(parents=True)
        standalone.write_text("", encoding="utf-8")
        sentinel = core.MatlabCapabilities(environment=core.MatlabEnvironment.MATLAB_STANDALONE, path=str(standalone))

        with patch("lib.core.shutil.which", return_value=None), \
             patch("lib.core._detect_spm_standalone", return_value=sentinel) as mock_detect_standalone:
            caps = core.detect_matlab_environment()

        mock_detect_standalone.assert_called_once_with(str(standalone))
        self.assertEqual(caps, sentinel)

    def test_returns_none_environment_when_nothing_found(self):
        with patch("lib.core.shutil.which", return_value=None):
            caps = core.detect_matlab_environment()
        self.assertEqual(caps.environment, core.MatlabEnvironment.NONE)
        self.assertIn("No MATLAB, Octave, or MCR found", caps.limitations)


if __name__ == "__main__":
    unittest.main()
