"""Opt-in smoke test of a *built* image, run as an arbitrary host uid (the way the pipeline runs it).

    BIDSPM_TEST_IMAGE=bidspm:spm26-atlas python -m pytest tests/test_image_smoke.py

Catches what Dockerfile text checks cannot: files the image tries to write at run time.
"""
import os
import shutil
import subprocess
import unittest

IMAGE = os.environ.get("BIDSPM_TEST_IMAGE")


@unittest.skipUnless(IMAGE and shutil.which("docker"), "set BIDSPM_TEST_IMAGE to a built image")
class TestImageRunsAsForeignUid(unittest.TestCase):
    def test_init_as_arbitrary_uid_has_no_errors(self):
        out = subprocess.run(
            ["docker", "run", "--rm", "--user", "12345:12345", "-e", "HOME=/tmp", "-w", "/tmp",
             "--entrypoint", "octave-cli", IMAGE, "--eval",
             "cd('/home/neuro/bidspm'); bidspm('init'); disp('INIT_DONE');"],
            capture_output=True, text=True, timeout=300)
        text = out.stdout + out.stderr
        self.assertIn("INIT_DONE", text)
        for bad in ("Permission denied", "Error occurred", "error:"):
            self.assertNotIn(bad, text.replace("error: ignoring const", ""), bad)


@unittest.skipUnless(IMAGE and shutil.which("docker"), "set BIDSPM_TEST_IMAGE to a built image")
class TestImageAveragesRuns(unittest.TestCase):
    """The BUILT image (no mounted overrides) must average a condition over runs: 2 runs -> 0.5 each."""

    def test_two_run_dummy_contrast_is_half_per_run(self):
        from tests.test_run_averaging_override import SUBJECT, _contrasts
        con = _contrasts({**SUBJECT, "DummyContrasts": {"Test": "t", "Contrasts": ["a"]}},
                         names=["Sn(1) a*bf(1)", "Sn(2) a*bf(1)", "Sn(1) constant"], image=IMAGE, mount=False)
        self.assertEqual(con["a"], [0.5, 0.5, 0])

    def test_image_has_the_override_version(self):
        out = subprocess.run(["docker", "run", "--rm", "--entrypoint", "cat", IMAGE, "/home/neuro/bidspm/OVERRIDES_VERSION"],
                             capture_output=True, text=True, timeout=60)
        self.assertIn("runs-averaged", out.stdout)
