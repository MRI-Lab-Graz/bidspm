"""SPM lives at /opt/spm (not /opt/spm12) so the image can ship any SPM release."""
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import lib.core as core
from lib.config import ContainerConfig
from tests.test_core_helpers import _make_config

DOCKERFILE = Path(__file__).resolve().parent.parent / "containers" / "dockerfile" / "dockerfile"


class TestSpmInstallPath(unittest.TestCase):
    def test_docker_command_uses_generic_spm_path(self):
        with tempfile.TemporaryDirectory() as tmp, patch("lib.core._seed_cpp_roi_atlas_cache"):
            cmd = core.build_docker_command(
                ContainerConfig(container_type="docker", docker_image="x:latest"),
                _make_config(Path(tmp)), ["/raw", "/derivatives", "subject", "stats"], None,
            )[0]
        joined = " ".join(cmd)
        self.assertIn(":/opt/spm/atlas", joined)
        self.assertNotIn("spm12", joined)

    def test_apptainer_wrapper_uses_generic_spm_path(self):
        with tempfile.TemporaryDirectory() as tmp, patch("lib.core._seed_cpp_roi_atlas_cache"):
            root = Path(tmp)
            image = root / "i.sif"
            image.write_text("x")
            cmd = core.build_apptainer_command(
                ContainerConfig(container_type="apptainer", apptainer_image=str(image)),
                _make_config(root), ["/raw", "/derivatives", "subject", "stats"], None,
            )[0]
            wrapper = "\n".join(p.read_text() for p in (root / "wd" / "tmp").glob("run_*/*") if p.is_file())
        text = " ".join(cmd) + wrapper
        self.assertIn("/opt/spm/atlas", text)
        self.assertNotIn("spm12", text)


class TestDockerfileSpm(unittest.TestCase):
    def setUp(self):
        self.text = DOCKERFILE.read_text(encoding="utf-8")

    def test_builds_released_spm_for_octave_at_opt_spm(self):
        self.assertRegex(self.text, r"github\.com/spm/spm/archive/refs/tags/\$\{?SPM_TAG\}?")
        self.assertRegex(self.text, r"ARG SPM_TAG=2[56]\.")
        self.assertIn("make -C /opt/spm/src PLATFORM=octave", self.text)

    def test_no_spm12_left(self):
        self.assertIsNone(re.search(r"/opt/spm12|SPM ?12", self.text))

    def test_marsbar_knows_new_spm_versions(self):
        # MarsBaR only maps spm99/2/5/8/12 to a compat dir; SPM25+ must reuse spm5's.
        self.assertIn("spm25", self.text)
        self.assertIn("marsbar.m", self.text)
