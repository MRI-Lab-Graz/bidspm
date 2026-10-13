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
        with tempfile.TemporaryDirectory() as tmp:
            cmd = core.build_docker_command(
                ContainerConfig(container_type="docker", docker_image="x:latest"),
                _make_config(Path(tmp)), ["/raw", "/derivatives", "subject", "stats"], None,
            )[0]
        joined = " ".join(cmd)
        self.assertNotIn("spm12", joined)

    def test_apptainer_wrapper_uses_generic_spm_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "i.sif"
            image.write_text("x")
            cmd = core.build_apptainer_command(
                ContainerConfig(container_type="apptainer", apptainer_image=str(image)),
                _make_config(root), ["/raw", "/derivatives", "subject", "stats"], None,
            )[0]
            wrapper = "\n".join(p.read_text() for p in (root / "wd" / "tmp").glob("run_*/*") if p.is_file())
        text = " ".join(cmd) + wrapper
        self.assertIn("/opt/spm", text)
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


class TestDockerfileCleanLogs(unittest.TestCase):
    """Each line below removes a message that used to pollute every run's terminal output."""

    def setUp(self):
        self.text = DOCKERFILE.read_text(encoding="utf-8")

    def test_macs_toolbox_is_writable_for_any_host_uid(self):
        self.assertRegex(self.text, r"chmod -R a\+rwX /opt/spm/toolbox/MACS")

    def test_marsbar_splash_removed(self):
        self.assertIn("marsbar('splash')", self.text)  # the sed pattern
        self.assertRegex(self.text, r"initCppRoi\.m")

    def test_octave_noise_warnings_silenced(self):
        self.assertIn("Octave:shadowed-function", self.text)
        self.assertIn("Octave:deprecated-function", self.text)

    def test_real_bids_validator_installed(self):
        self.assertRegex(self.text, r"npm install -g bids-validator@1\.14\.")


class TestDockerfileRemainingNoise(unittest.TestCase):
    def setUp(self):
        self.text = DOCKERFILE.read_text(encoding="utf-8")

    def test_base_image_has_octave_9(self):
        # Octave 6/7 print "ignoring const execution_exception" on every headless exit
        self.assertRegex(self.text, r"(?m)^FROM python:3\.12-slim-trixie")

    def test_git_trusts_all_dirs_for_arbitrary_host_uid(self):
        self.assertIn("safe.directory '*'", self.text)

    def test_node_deprecation_warnings_off(self):
        self.assertIn("NODE_NO_WARNINGS=1", self.text)

    def test_legacy_function_warnings_silenced(self):
        self.assertIn("Octave:legacy-function", self.text)

    def test_boilerplate_missing_key_warnings_off(self):
        # report template data lacks designType / OS.version; the text is cosmetic
        self.assertIn("boilerplate.m", self.text)
        self.assertIn("'warn', false", self.text)


class TestDockerfileHomeAccess(unittest.TestCase):
    def test_home_traversable_by_arbitrary_host_uid(self):
        # containers run with --user <host uid>; trixie's useradd makes $HOME 0700
        text = DOCKERFILE.read_text(encoding="utf-8")
        self.assertRegex(text, r"chmod -R a\+rX /home/neuro|chmod 755 /home/neuro")


class TestDockerfileWhichAll(unittest.TestCase):
    def setUp(self):
        self.text = DOCKERFILE.read_text(encoding="utf-8")

    def test_which_all_dropped_case_insensitively_from_spm_and_bidspm(self):
        # Octave 9 warns "which: '-all' not yet implemented" on each call; SPM and bidspm
        # spell it '-all' and '-ALL' (spm_defaults.m, returnRootDir.m, ...)
        m = re.search(r"RUN grep -rliE .*-all.*/opt/spm.*/home/neuro/bidspm.*\n.*! grep -rqiE .*-all.*", self.text)
        self.assertIsNotNone(m, "no case-insensitive which -all patch with a build-time guard")

    def test_patch_runs_after_overrides_are_copied(self):
        # the override files (bidspm.m, ...) would otherwise overwrite the patched copies
        self.assertGreater(self.text.index("grep -rliE"), self.text.index("COPY bidspm_overrides/"))
