"""--design_only must stop after specifying the model (v4.0.0 lost the flag via rmfield(opt,'model'))."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

OVERRIDE = Path(__file__).resolve().parent.parent / "bidspm_overrides" / "src" / "cli" / "cliStats.m"


@unittest.skipUnless(shutil.which("octave"), "octave not installed")
class TestCliStatsDesignOnly(unittest.TestCase):
    def _calls(self, design_only: bool, action: str = "stats") -> list:
        with tempfile.TemporaryDirectory() as tmp:
            s = Path(tmp)
            marks = s / "marks.txt"

            def rec(label: str) -> str:
                return f"f = fopen('{marks}', 'a'); fprintf(f, '%s\\n', {label}); fclose(f);"

            def stub(name: str, body: str, sig: str = "varargin"):
                (s / f"{name}.m").write_text(f"function varargout = {name}({sig})\n{body}\nend\n")

            stub("inputParserForStats", "varargout{1} = struct();", sig="")
            stub("parse", "", sig="varargin")
            stub("validate", "", sig="varargin")
            # args.Results comes from this stub via a global-free trick: parse() is a no-op, so
            # inputParserForStats returns the finished struct.
            (s / "inputParserForStats.m").write_text(
                "function a = inputParserForStats()\n"
                f"  a.Results = struct('action', '{action}', 'analysis_level', 'subject', 'node_name', '', "
                f"'concatenate', false, 'design_only', {str(design_only).lower()});\nend\n")
            stub("getOptionsFromCliArgument",
                 "args = varargin{1}; opt.model.file = 'm.json'; "
                 "opt.model.designOnly = args.Results.design_only; opt.glm.roibased.do = false; "
                 "opt.glm.concatenateRuns = false; opt.boilerplateOnly = false; opt.dir.output = 'o'; "
                 "opt.dir.stats = 's'; opt.fwhm.contrast = 0; varargout{1} = opt;")
            # real checkOptions refills defaults, which is how designOnly got lost
            stub("checkOptions", "opt = varargin{1}; opt.model.designOnly = false; varargout{1} = opt;")
            for name in ("saveOptions", "boilerplate"):
                stub(name, "")
            stub("compileScrubbingStats", rec("'scrub'"))
            stub("bidsFFX", rec("['ffx:' varargin{1}]"))
            stub("bidsResults", rec("'results'"))
            shutil.copy(OVERRIDE, s / "cliStats.m")
            subprocess.run(["octave-cli" if shutil.which("octave-cli") else "octave", "--no-gui", "--eval",
                            f"setenv('BIDSPM_SKIP_RESULTS', ''); addpath('{s}'); cliStats();"],
                           capture_output=True, text=True, timeout=60)
            return marks.read_text().split() if marks.exists() else []

    def test_design_only_specifies_and_nothing_else(self):
        self.assertEqual(self._calls(design_only=True), ["ffx:specify", "scrub"])

    def test_normal_stats_still_estimates_and_runs_contrasts(self):
        calls = self._calls(design_only=False)
        self.assertEqual(calls[:3], ["ffx:specifyAndEstimate", "scrub", "ffx:contrasts"])
        self.assertNotIn("ffx:specify", calls)
