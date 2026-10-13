"""validate.m must still run the BIDS dataset validator, but never shell out to validate_model."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

OVERRIDE = Path(__file__).resolve().parent.parent / "bidspm_overrides" / "src" / "bids" / "validate.m"


@unittest.skipUnless(shutil.which("octave"), "octave not installed")
class TestValidateOverride(unittest.TestCase):
    def _run(self, action: str, skip: bool):
        with tempfile.TemporaryDirectory() as tmp:
            s = Path(tmp)
            marks = s / "marks.txt"
            (s / "+bids" / "+internal").mkdir(parents=True)
            (s / "+bids" / "validate.m").write_text(
                f"function [s, m] = validate(d)\n  f = fopen('{marks}', 'a'); fprintf(f, 'dataset\\n'); fclose(f);\n  s = 0; m = 'ok';\nend\n")
            (s / "+bids" / "+internal" / "format_path.m").write_text("function p = format_path(p)\nend\n")
            (s / "+bids" / "+internal" / "starts_with.m").write_text("function r = starts_with(a, b)\n  r = false;\nend\n")
            (s / "logger.m").write_text("function logger(varargin)\nend\n")
            (s / "system.m").write_text(
                f"function [s, o] = system(cmd)\n  f = fopen('{marks}', 'a'); fprintf(f, 'system\\n'); fclose(f);\n  s = 0; o = '';\nend\n")
            shutil.copy(OVERRIDE, s / "validate.m")
            r = "struct('skip_validation', %s, 'bids_dir', '/x', 'verbosity', 0, 'action', '%s', 'model_file', '/m.json')" % (
                "true" if skip else "false", action)
            subprocess.run(["octave", "--no-gui", "--eval", f"addpath('{s}'); validate(struct('Results', {r}));"],
                           capture_output=True, text=True, timeout=60)
            return marks.read_text().split() if marks.exists() else []

    def test_dataset_is_validated_for_stats(self):
        self.assertEqual(self._run("stats", False), ["dataset"])

    def test_model_validator_is_never_invoked(self):
        self.assertNotIn("system", self._run("stats", False))

    def test_skip_validation_skips_everything(self):
        self.assertEqual(self._run("stats", True), [])
