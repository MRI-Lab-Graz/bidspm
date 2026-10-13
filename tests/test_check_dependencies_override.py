"""checkDependencies.m must accept SPM25+ (reports 'SPM26', revision '00.00') without warning."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

OVERRIDE = Path(__file__).resolve().parent.parent / "bidspm_overrides" / "src" / "infra" / "checkDependencies.m"


@unittest.skipUnless(shutil.which("octave"), "octave not installed")
class TestCheckDependenciesOverride(unittest.TestCase):
    def _warnings_for(self, spm_ver: str, spm_rev: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            stubs = Path(tmp)
            (stubs / "spm.m").write_text(
                "function varargout = spm(varargin)\n"
                f"  if strcmp(varargin{{1}}, 'ver'), varargout = {{'{spm_ver}', '{spm_rev}'}}; end\n"
                "end\n")
            (stubs / "spm_jobman.m").write_text("function spm_jobman(varargin)\nend\n")
            (stubs / "logger.m").write_text("function logger(varargin)\nend\n")
            shutil.copy(OVERRIDE, stubs / "checkDependencies.m")
            out = subprocess.run(
                ["octave", "--no-gui", "--eval", f"addpath('{stubs}'); checkDependencies(struct());"],
                capture_output=True, text=True, timeout=60)
        return out.stderr

    def test_spm26_does_not_warn(self):
        self.assertNotIn("less than", self._warnings_for("SPM26", "00.00"))

    def test_spm25_does_not_warn(self):
        self.assertNotIn("less than", self._warnings_for("SPM25", "00.00"))

    def test_spm12_new_enough_does_not_warn(self):
        self.assertNotIn("less than", self._warnings_for("SPM12", "7771"))

    def test_old_spm12_revision_still_warns(self):
        self.assertIn("less than", self._warnings_for("SPM12", "6000"))

    def test_spm8_still_warns(self):
        self.assertIn("less than", self._warnings_for("SPM8", "4667"))
