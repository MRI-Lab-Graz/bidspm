"""CLI / GUI / project-config wiring for estimation_engine and spm_standalone_image."""
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bidspm
from lib.config import ContainerConfig
from lib.core import Pipeline, PipelineOptions
from lib.project_manager import ProjectConfig
from tests.test_core_helpers import _make_config


class TestCliFlag(unittest.TestCase):
    def test_default_octave_and_choices(self):
        with patch("sys.argv", ["bidspm.py", "--action", "stats"]):
            self.assertEqual(bidspm.parse_arguments().estimation_engine, "octave")
        with patch("sys.argv", ["bidspm.py", "--action", "stats", "--estimation-engine", "standalone"]):
            self.assertEqual(bidspm.parse_arguments().estimation_engine, "standalone")
        with patch("sys.argv", ["bidspm.py", "--estimation-engine", "matlab"]), self.assertRaises(SystemExit):
            bidspm.parse_arguments()


class TestProjectConfig(unittest.TestCase):
    def test_has_standalone_image_field(self):
        self.assertEqual(ProjectConfig().spm_standalone_image, "")
        self.assertIn("spm_standalone_image", ProjectConfig().to_dict())


class TestRunPreflight(unittest.TestCase):
    def test_run_stops_before_any_subject_when_image_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Pipeline(PipelineOptions(actions=["stats"], estimation_engine="standalone"))
            p.config = _make_config(Path(tmp))
            p.container_config = ContainerConfig(container_type="docker", docker_image="x")
            p.setup = lambda: True
            p.get_subjects_to_process = lambda: ["01"]
            with patch.object(Pipeline, "_process_subject") as proc:
                result = p.run()
        self.assertFalse(result.success)
        proc.assert_not_called()
        self.assertTrue(any("spm_standalone_image" in e for e in result.errors))
