"""--results: the SPM Results export is ~1/3 of per-subject time on short runs, so it is opt-in
(except for the report action, which reads its tables/figures)."""
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


class TestRunResultsCli(unittest.TestCase):
    def test_flag_parsed(self):
        with patch("sys.argv", ["bidspm.py", "--action", "stats", "--results"]):
            self.assertTrue(bidspm.parse_arguments().run_results)

    def test_off_by_default(self):
        with patch("sys.argv", ["bidspm.py", "--action", "stats"]):
            self.assertFalse(bidspm.parse_arguments().run_results)

    def test_pipeline_option_off_by_default(self):
        self.assertFalse(PipelineOptions(actions=["stats"]).run_results)


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
    def _extra_env(self, **opts):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = Pipeline(PipelineOptions(dry_run=True, **opts))
            pipeline.config = _make_config(Path(tmp))
            pipeline.container_config = ContainerConfig(container_type="docker", docker_image="x:latest")
            pipeline.model_file_path = None
            with patch("lib.core.build_container_command", return_value=(["docker"], None)) as build:
                pipeline._run_container_action("stats", "01", "motor")
        return build.call_args.kwargs.get("extra_env")

    def test_results_skipped_by_default(self):
        self.assertEqual(self._extra_env(actions=["stats"])["BIDSPM_SKIP_RESULTS"], "1")

    def test_results_kept_when_requested(self):
        self.assertNotIn("BIDSPM_SKIP_RESULTS", self._extra_env(actions=["stats"], run_results=True))

    def test_report_action_needs_results_so_they_are_kept(self):
        self.assertNotIn("BIDSPM_SKIP_RESULTS", self._extra_env(actions=["stats", "report"]))
