"""The BIDS dataset validator walks the whole dataset; run it in the first container only."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.config import ContainerConfig
from lib.core import Pipeline, PipelineOptions
from tests.test_core_helpers import _make_config


class TestValidateOnce(unittest.TestCase):
    def _pipeline(self, tmp):
        pipeline = Pipeline(PipelineOptions(actions=["stats", "dataset"], dry_run=True))
        pipeline.config = _make_config(Path(tmp))
        pipeline.container_config = ContainerConfig(container_type="docker", docker_image="x:latest")
        pipeline.model_file_path = None
        return pipeline

    def _args_of_calls(self, run):
        with tempfile.TemporaryDirectory() as tmp, \
             patch("lib.core.build_container_command", return_value=(["docker"], None)) as build:
            run(self._pipeline(tmp))
        return [call.args[2] for call in build.call_args_list]

    def test_only_first_subject_container_validates(self):
        calls = self._args_of_calls(lambda p: [p._run_container_action("stats", s, "motor") for s in ("01", "02", "03")])
        self.assertEqual(["--skip_validation" in a for a in calls], [False, True, True])

    def test_dataset_step_after_stats_skips_validation(self):
        def run(p):
            p._run_container_action("stats", "01", "motor")
            p._run_container_dataset_action("motor")
        calls = self._args_of_calls(run)
        self.assertEqual(["--skip_validation" in a for a in calls], [False, True])

    def test_dataset_step_alone_still_validates(self):
        calls = self._args_of_calls(lambda p: p._run_container_dataset_action("motor"))
        self.assertNotIn("--skip_validation", calls[0])
