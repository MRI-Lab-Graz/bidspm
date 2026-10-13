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
