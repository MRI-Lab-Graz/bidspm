"""smooth+stats must not smooth twice, and the smooth CLI never gets --skip_validation (it rejects it)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.config import ContainerConfig
from lib.core import Pipeline, PipelineOptions
from tests.test_core_helpers import _make_config


def _pipeline(tmp, **opts):
    p = Pipeline(PipelineOptions(actions=["smooth", "stats"], **opts))
    p.config = _make_config(Path(tmp))
    p.container_config = ContainerConfig(container_type="docker", docker_image="x:latest")
    p.model_file_path = None
    p.stats_node_name = None
    return p


def _fake_smoothed(p, subject="01"):
    d = p.config.DERIVATIVES_DIR / "bidspm-preproc" / f"sub-{subject}" / "func"
    d.mkdir(parents=True)
    (d / f"sub-{subject}_task-motor_space-{p.config.SPACE}_desc-smth6.0_bold.nii").write_text("x")


class TestSmoothOnce(unittest.TestCase):
    def test_no_container_smooth_when_fast_output_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _pipeline(tmp)
            _fake_smoothed(p)
            calls = []
            with patch.object(p, "_run_container_action", side_effect=lambda a, *r, **k: calls.append(a) or True), \
                    patch.object(p, "_copy_brain_mask"), patch.object(p, "_run_stats_standalone", return_value=True):
                p._process_subject("01", "motor")
        self.assertNotIn("smooth", calls)

    def test_force_with_fast_backend_still_does_not_resmooth(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _pipeline(tmp, force=True)
            _fake_smoothed(p)
            calls = []
            with patch.object(p, "_run_container_action", side_effect=lambda a, *r, **k: calls.append(a) or True), \
                    patch.object(p, "_copy_brain_mask"):
                p._process_subject("01", "motor")
        self.assertNotIn("smooth", calls)

    def test_container_backend_still_smooths(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _pipeline(tmp, smooth_backend="container")
            _fake_smoothed(p)
            calls = []
            with patch.object(p, "_run_container_action", side_effect=lambda a, *r, **k: calls.append(a) or True), \
                    patch.object(p, "_copy_brain_mask"):
                p._process_subject("01", "motor")
        self.assertIn("smooth", calls)


class TestFlagsPerAction(unittest.TestCase):
    def _args(self, action, n_before=0):
        with tempfile.TemporaryDirectory() as tmp:
            p = _pipeline(tmp, dry_run=True)
            p._validated = n_before > 0
            seen = []

            def build(cc, cfg, args, *a, **k):
                seen.append(list(args))
                return ["docker"], None
            with patch("lib.core.build_container_command", side_effect=build):
                p._run_container_action(action, "01", "motor")
        return seen[0]

    def test_smooth_never_gets_skip_validation(self):
        self.assertNotIn("--skip_validation", self._args("smooth", n_before=1))
        self.assertNotIn("--skip_validation", self._args("smooth", n_before=0))

    def test_smooth_does_not_use_up_the_validation_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = _pipeline(tmp, dry_run=True)
            seen = []
            with patch("lib.core.build_container_command",
                       side_effect=lambda cc, cfg, args, *a, **k: seen.append(list(args)) or (["d"], None)):
                p._run_container_action("smooth", "01", "motor")
                p._run_container_action("stats", "01", "motor")
                p._run_container_action("stats", "02", "motor")
        self.assertNotIn("--skip_validation", seen[1])
        self.assertIn("--skip_validation", seen[2])

    def test_later_stats_get_skip_validation(self):
        self.assertIn("--skip_validation", self._args("stats", n_before=1))
