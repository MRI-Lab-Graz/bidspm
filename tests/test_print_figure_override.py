"""The image has no graphics toolkit, so 'Print figure' SPM jobs only produce 'Figure not found'."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

OVERRIDE = Path(__file__).resolve().parent.parent / "bidspm_overrides" / "src" / "batches" / "setBatchPrintFigure.m"


@unittest.skipUnless(shutil.which("octave"), "octave not installed")
class TestPrintFigureOverride(unittest.TestCase):
    def test_adds_no_print_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Path(tmp)
            (s / "spm.m").write_text("function r = spm(varargin)\n  r = true;\nend\n")
            (s / "printBatchName.m").write_text("function printBatchName(varargin)\nend\n")
            shutil.copy(OVERRIDE, s / "setBatchPrintFigure.m")
            out = subprocess.run(
                ["octave", "--no-gui", "--eval",
                 f"addpath('{s}'); mb = setBatchPrintFigure({{}}, struct(), 'x'); printf('N=%d', numel(mb));"],
                capture_output=True, text=True, timeout=60)
        self.assertIn("N=0", out.stdout)
