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


    def test_run_bms_fails_early_when_node_collision_detected(self):
        """run_bms must reject models_dir with duplicate node names before running."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            # Both models share the same node name — collision
            model = {
                "Name": "test", "BIDSVersion": "1.9.0",
                "Nodes": [{"Level": "Run", "Name": "DuplicateName",
                            "Model": {"X": ["trial_type"]}}]
            }
            import json as _json
            (d / "a_smdl.json").write_text(_json.dumps(model), encoding="utf-8")
            (d / "b_smdl.json").write_text(_json.dumps(model), encoding="utf-8")

            result = core.run_bms(
                config_file="ignored.json",
                container_config_file=None,
                models_dir=str(d),
            )

        self.assertFalse(result["success"])
        self.assertTrue(
            any("DuplicateName" in e for e in result["errors"]),
            f"Expected collision error in {result['errors']}",
        )


class TestCheckModelsDirNodeCollision(unittest.TestCase):
    def _write_model(self, path: Path, node_name: str) -> None:
        """Write a minimal valid BIDS Stats Model with the given root-node Name."""
        model = {
            "Name": "test",
            "BIDSVersion": "1.9.0",
            "Nodes": [{"Level": "Run", "Name": node_name, "Model": {"X": ["trial_type"]}}]
        }
        path.write_text(__import__("json").dumps(model), encoding="utf-8")

    def test_returns_empty_when_all_node_names_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self._write_model(d / "a_smdl.json", "ModelA")
            self._write_model(d / "b_smdl.json", "ModelB")
            self.assertEqual(core.check_models_dir_node_collision(d), [])

    def test_reports_error_when_two_models_share_node_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self._write_model(d / "a_smdl.json", "MyModel")
            self._write_model(d / "b_smdl.json", "MyModel")
            errors = core.check_models_dir_node_collision(d)
            self.assertEqual(len(errors), 1)
            self.assertIn("MyModel", errors[0])

    def test_normalization_catches_case_only_duplicates(self):
        """'mymodel' and 'MyModel' normalize to the same label — still a collision."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self._write_model(d / "a_smdl.json", "mymodel")
            self._write_model(d / "b_smdl.json", "MyModel")
            errors = core.check_models_dir_node_collision(d)
            self.assertEqual(len(errors), 1)

    def test_reports_error_for_run_level_node_name(self):
        """'run' maps to an unsuffixed folder — guaranteed future collision risk."""
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self._write_model(d / "a_smdl.json", "run")
            self._write_model(d / "b_smdl.json", "ModelB")
            errors = core.check_models_dir_node_collision(d)
            self.assertEqual(len(errors), 1)
            self.assertIn("unsuffixed", errors[0])

    def test_reports_error_for_runlevel_node_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            self._write_model(d / "a_smdl.json", "run_level")  # normalizes to 'runlevel'
            self._write_model(d / "b_smdl.json", "ModelB")
            errors = core.check_models_dir_node_collision(d)
            self.assertEqual(len(errors), 1)
            self.assertIn("unsuffixed", errors[0])

    def test_skips_unreadable_model_files_gracefully(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "bad_smdl.json").write_text("not json", encoding="utf-8")
            (d / "good_smdl.json")  # not written, just checking no crash
            self._write_model(d / "good_smdl.json", "ModelA")
            # Should not raise; bad file is skipped
            result = core.check_models_dir_node_collision(d)
            self.assertIsInstance(result, list)


if __name__ == "__main__":
    unittest.main()
