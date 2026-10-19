"""The container for a run comes from: --container file > container keys in the run settings > platform auto-detect."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.config import resolve_container_config
from lib.core import Pipeline, PipelineOptions, build_container_command
from lib.preflight import run_preflight_from_config
from tests.test_core_helpers import _make_config

SETTINGS = {"container_type": "docker", "docker_image": "my/img:1", "spm_standalone_image": "sha256:Y"}


def _file(tmp, **data):
    p = Path(tmp) / "c.json"
    p.write_text(json.dumps(data))
    return str(p)


class TestResolve(unittest.TestCase):
    def test_settings_used_without_touching_auto_detect(self):
        with patch("lib.config.auto_select_container_config", side_effect=AssertionError("auto-detect read")):
            cc = resolve_container_config(None, SETTINGS)
        self.assertEqual((cc.container_type, cc.docker_image, cc.spm_standalone_image), ("docker", "my/img:1", "sha256:Y"))

    def test_explicit_file_beats_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _file(tmp, container_type="docker", docker_image="file/img")
            self.assertEqual(resolve_container_config(f, SETTINGS).docker_image, "file/img")

    def test_no_container_keys_falls_back_to_auto_detect(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _file(tmp, container_type="apptainer", apptainer_image="/x.sif")
            with patch("lib.config.auto_select_container_config", return_value=f):
                cc = resolve_container_config(None, {"WD": "/w"})
        self.assertEqual(cc.container_type, "apptainer")

    def test_type_without_its_image_falls_back(self):
        with patch("lib.config.auto_select_container_config", return_value=None):
            self.assertIsNone(resolve_container_config(None, {"container_type": "docker", "docker_image": ""}))

    def test_apptainer_settings(self):
        cc = resolve_container_config(None, {"container_type": "apptainer", "apptainer_image": "/a.sif"})
        self.assertEqual((cc.container_type, cc.apptainer_image), ("apptainer", "/a.sif"))


class TestPipelineUsesSettings(unittest.TestCase):
    def _setup(self, tmp, container=None):
        cfg = {"WD": str(Path(tmp) / "wd"), "BIDS_DIR": tmp, "FMRIPREP_DIR": tmp, "SPACE": "s", "FWHM": 6,
               "TASKS": ["t"], **SETTINGS}
        cfg_path = Path(tmp) / "cfg.json"
        cfg_path.write_text(json.dumps(cfg))
        p = Pipeline(PipelineOptions(actions=["smooth"], config_file=str(cfg_path), container_config_file=container))
        p.validate_config = lambda: True
        with patch("lib.config.auto_select_container_config", side_effect=AssertionError("auto-detect read")) \
                if not container else contextlib.nullcontext(), \
                patch("lib.core.check_docker_availability"):
            self.assertTrue(p.setup())
        return p

    def test_setup_takes_container_from_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._setup(tmp)
        self.assertEqual(p.container_config.docker_image, "my/img:1")
        self.assertEqual(p.container_config.spm_standalone_image, "sha256:Y")

    def test_setup_explicit_container_file_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._setup(tmp, container=_file(tmp, container_type="docker", docker_image="file/img"))
        self.assertEqual(p.container_config.docker_image, "file/img")

    def test_standalone_command_contains_project_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._setup(tmp)
            p.config = _make_config(Path(tmp))
            p.options.estimation_engine = "standalone"
            p.model_file_path = None
            cc = p.container_config
            cmd, _ = build_container_command(cc, p.config, ["x"], None)
        self.assertIn("my/img:1", cmd)
        self.assertEqual(cc.spm_standalone_image, "sha256:Y")


class TestPreflightSameResolution(unittest.TestCase):
    def _types(self, cfg, auto=None):
        seen = []
        with tempfile.TemporaryDirectory() as tmp, \
                patch("lib.preflight.check_dirs", return_value=[]), \
                patch("lib.preflight._subject_checks", side_effect=lambda *a: seen.append(a[6]) or []), \
                patch("lib.config.auto_select_container_config", **auto), \
                contextlib.redirect_stdout(io.StringIO()):
            run_preflight_from_config({"BIDS_DIR": tmp, "FMRIPREP_DIR": tmp, "TASKS": ["t"], **cfg}, validator="skip")
        return seen

    def test_readiness_checks_the_settings_type_not_auto_detect(self):
        seen = self._types({"container_type": "docker", "docker_image": "x"},
                           {"side_effect": AssertionError("auto-detect read")})
        self.assertEqual(seen, ["docker"])

    def test_no_keys_uses_the_auto_detected_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = _file(tmp, container_type="apptainer", apptainer_image="/x.sif")
            self.assertEqual(self._types({}, {"return_value": f}), ["apptainer"])
