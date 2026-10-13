"""Atlases are unpacked into /opt/spm/atlas at image build time, not per run via host cache dirs."""
import re
import tempfile
import unittest
from pathlib import Path

import lib.core as core
from lib.config import ContainerConfig
from tests.test_core_helpers import _make_config

DOCKERFILE = Path(__file__).resolve().parent.parent / "containers" / "dockerfile" / "dockerfile"
ARGS = ["/raw", "/derivatives", "subject", "stats"]


class TestNoHostAtlasCache(unittest.TestCase):
    @staticmethod
    def _mounts(cmd, flag):
        return [cmd[i + 1] for i, part in enumerate(cmd[:-1]) if part == flag]

    def test_docker_command_has_no_atlas_mounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmd = core.build_docker_command(
                ContainerConfig(container_type="docker", docker_image="x:latest"),
                _make_config(Path(tmp)), ARGS, None)[0]
        self.assertEqual([m for m in self._mounts(cmd, "-v") if "atlas" in m], [])

    def test_apptainer_command_has_no_atlas_binds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "i.sif"
            image.write_text("x")
            cmd = core.build_apptainer_command(
                ContainerConfig(container_type="apptainer", apptainer_image=str(image)),
                _make_config(root), ARGS, None)[0]
        self.assertEqual([m for m in self._mounts(cmd, "--bind") if "atlas" in m], [])

    def test_seeding_and_warmup_code_is_gone(self):
        for name in ("_seed_cpp_roi_atlas_cache", "_get_cpp_roi_atlas_cache_dir",
                     "_atlas_cache_is_warm", "_ATLAS_CACHE_FILES"):
            self.assertFalse(hasattr(core, name), name)


class TestDockerfileBakesAtlases(unittest.TestCase):
    def setUp(self):
        self.text = DOCKERFILE.read_text(encoding="utf-8")

    def test_atlases_unpacked_at_build_by_bidspm_init(self):
        # initCppRoi.m (run by bidspm('init')) copies all five atlases into spm('dir')/atlas
        self.assertRegex(self.text, r"RUN octave-cli --eval .*bidspm\('init'\)")

    def test_build_fails_if_atlas_files_missing(self):
        for f in ("AAL3v1_1mm.nii", "HCPex.nii", "space-MNI_seg-wang_dseg.nii",
                  "space-MNI_seg-visfAtlas_dseg.nii", "glasser_dseg.nii"):
            self.assertIn(f, self.text)

    def test_atlas_dir_readable_by_any_host_uid(self):
        self.assertIn("chmod -R a+rX /opt/spm/atlas", self.text)
