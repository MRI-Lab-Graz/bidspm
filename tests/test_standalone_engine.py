"""estimation_engine='standalone': design (Octave) -> estimate (SPM standalone) -> contrasts (Octave)."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.config import ContainerConfig
from lib.core import Pipeline, PipelineOptions
from tests.test_core_helpers import _make_config

IMAGE = "spm@sha256:abc"


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def pipeline(self, engine="standalone", dry_run=False, image=IMAGE):
        p = Pipeline(PipelineOptions(actions=["stats"], estimation_engine=engine, dry_run=dry_run))
        p.config = _make_config(Path(self.tmp.name))
        p.container_config = ContainerConfig(container_type="docker", docker_image="bidspm:x", spm_standalone_image=image)
        p.model_file_path = None
        return p

    def run_subject(self, p, run_results=(True, True, True), mats=True):
        """Returns (success, [label per executed command])."""
        calls, results = [], iter(run_results)
        spm_mat = p.config.DERIVATIVES_DIR / "bidspm-stats" / "sub-01" / "task-motor_x" / "SPM.mat"

        def fake_build(cc, cfg, args, model, **kw):
            return (["octave"] + list(args), None)

        def fake_run(cmd, *a, **k):
            calls.append("octave:" + ("design" if "--design_only" in cmd else cmd[cmd.index("subject") + 1])
                         if cmd[0] == "octave" else "standalone")
            return next(results, True)

        with patch("lib.core.build_container_command", side_effect=fake_build), \
             patch("lib.core.run_command", side_effect=fake_run), \
             patch("lib.core.find_new_spm_mats", return_value=[spm_mat] if mats else []), \
             patch.object(Pipeline, "_copy_brain_mask"):
            ok = p._process_subject("01", "motor")
        return ok, calls


class TestStandaloneOrchestration(_Base):
    def test_octave_engine_is_a_single_container_call(self):
        ok, calls = self.run_subject(self.pipeline(engine="octave"))
        self.assertTrue(ok)
        self.assertEqual(calls, ["octave:stats"])

    def test_standalone_runs_design_estimate_contrasts_in_order(self):
        ok, calls = self.run_subject(self.pipeline())
        self.assertTrue(ok)
        self.assertEqual(calls, ["octave:design", "standalone", "octave:contrasts"])

    def test_design_failure_stops_the_chain(self):
        ok, calls = self.run_subject(self.pipeline(), run_results=(False,))
        self.assertFalse(ok)
        self.assertEqual(calls, ["octave:design"])

    def test_estimation_failure_skips_contrasts(self):
        ok, calls = self.run_subject(self.pipeline(), run_results=(True, False))
        self.assertFalse(ok)
        self.assertEqual(calls, ["octave:design", "standalone"])

    def test_missing_spm_mat_fails_before_estimation(self):
        ok, calls = self.run_subject(self.pipeline(), mats=False)
        self.assertFalse(ok)
        self.assertEqual(calls, ["octave:design"])

    def test_dry_run_records_all_three_commands_and_runs_nothing(self):
        p = self.pipeline(dry_run=True)
        with patch("lib.core.run_command") as run, patch.object(Pipeline, "_copy_brain_mask"):
            self.assertTrue(p._process_subject("01", "motor"))
        run.assert_not_called()
        self.assertEqual(len(p.dry_run_commands), 3)
        self.assertIn("--design_only", p.dry_run_commands[0])
        self.assertIn("batch /job/job.m", p.dry_run_commands[1])
        self.assertIn(" contrasts ", p.dry_run_commands[2])


class TestStandalonePreflight(_Base):
    def test_missing_image_is_an_error_before_any_subject(self):
        p = self.pipeline(image="")
        self.assertFalse(p._check_standalone_image())
        self.assertTrue(any("spm_standalone_image" in e for e in p.errors))

    def test_available_image_passes_and_octave_engine_never_checks(self):
        with patch("lib.core.check_spm_image", return_value=(True, IMAGE)) as chk:
            self.assertTrue(self.pipeline()._check_standalone_image())
            chk.assert_called_once()
        with patch("lib.core.check_spm_image") as chk:
            self.assertTrue(self.pipeline(engine="octave", image="")._check_standalone_image())
            chk.assert_not_called()
