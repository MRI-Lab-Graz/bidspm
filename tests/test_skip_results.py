"""--skip-results: the SPM Results export is ~1/3 of per-subject time on short runs; make it optional."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bidspm
import lib.core as core
from lib.config import ContainerConfig
from lib.core import Pipeline, PipelineOptions
from tests.test_core_helpers import _make_config

ARGS = ["/raw", "/derivatives", "subject", "stats"]
ENV = {"BIDSPM_SKIP_RESULTS": "1"}


class TestSkipResultsCli(unittest.TestCase):
    def test_flag_parsed(self):
        with patch("sys.argv", ["bidspm.py", "--action", "stats", "--skip-results"]):
            self.assertTrue(bidspm.parse_arguments().skip_results)

    def test_defaults_false(self):
        with patch("sys.argv", ["bidspm.py", "--action", "stats"]):
            self.assertFalse(bidspm.parse_arguments().skip_results)

    def test_pipeline_option_defaults_false(self):
        self.assertFalse(PipelineOptions(actions=["stats"]).skip_results)


class TestSkipResultsEnv(unittest.TestCase):
    def test_docker_gets_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmd = core.build_docker_command(
                ContainerConfig(container_type="docker", docker_image="x:latest"),
                _make_config(Path(tmp)), ARGS, None, extra_env=ENV)[0]
        self.assertIn("BIDSPM_SKIP_RESULTS=1", cmd)

    def test_apptainer_gets_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "i.sif"
            image.write_text("x")
            cmd = core.build_apptainer_command(
                ContainerConfig(container_type="apptainer", apptainer_image=str(image)),
                _make_config(root), ARGS, None, extra_env=ENV)[0]
        self.assertIn("BIDSPM_SKIP_RESULTS=1", cmd)

    def test_no_env_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmd = core.build_docker_command(
                ContainerConfig(container_type="docker", docker_image="x:latest"),
                _make_config(Path(tmp)), ARGS, None)[0]
        self.assertNotIn("BIDSPM_SKIP_RESULTS=1", cmd)


class TestPipelinePassesSkipResults(unittest.TestCase):
    def _extra_env(self, skip: bool):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = Pipeline(PipelineOptions(actions=["stats"], skip_results=skip, dry_run=True))
            pipeline.config = _make_config(Path(tmp))
            pipeline.container_config = ContainerConfig(container_type="docker", docker_image="x:latest")
            pipeline.model_file_path = None
            with patch("lib.core.build_container_command", return_value=(["docker"], None)) as build:
                pipeline._run_container_action("stats", "01", "motor")
        return build.call_args.kwargs.get("extra_env")

    def test_env_passed_when_enabled(self):
        self.assertEqual(self._extra_env(True), ENV)

    def test_no_env_when_disabled(self):
        self.assertFalse(self._extra_env(False))
