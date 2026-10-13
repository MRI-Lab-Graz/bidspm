"""fMRIPrep drops SliceTiming after correcting and records SliceTimingCorrected + StartTime instead.

bidspm v4.0.0 then assumes the middle bin (24 ms off for TR 1.2 / 80 bins / StartTime 0.561 s, and wrong
for a non-default --slice-time-ref). SPM places regressors at (fmri_t0 - 1) * TR / fmri_t.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HELPER = (Path(__file__).resolve().parent.parent / "bidspm_overrides" / "src" / "stats"
          / "subject_level" / "getReferenceBinFromStartTime.m")


@unittest.skipUnless(shutil.which("octave"), "octave not installed")
class TestReferenceBinFromStartTime(unittest.TestCase):
    def _bin(self, fixture: str, tr: float = 1.2, bins: int = 80) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            s = Path(tmp)
            (s / "+bids").mkdir()
            (s / "+bids" / "query.m").write_text(
                "function r = query(BIDS, ~, filter)\n"
                "  if isfield(BIDS, filter.target), r = BIDS.(filter.target); else r = []; end\nend\n")
            shutil.copy(HELPER, s / HELPER.name)
            out = subprocess.run(
                ["octave-cli" if shutil.which("octave-cli") else "octave", "--no-gui", "--eval",
                 f"addpath('{s}'); BIDS = struct(); {fixture}; "
                 f"b = getReferenceBinFromStartTime(BIDS, struct(), {tr}, {bins}); "
                 f"if isempty(b), disp('EMPTY'); else printf('BIN=%d\\n', b); end"],
                capture_output=True, text=True, timeout=60)
        return out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr[-200:]

    def test_corrected_runs_with_same_start_time_give_the_reference_bin(self):
        self.assertEqual(self._bin("BIDS.SliceTimingCorrected = {true, true}; BIDS.StartTime = {0.561, 0.561}"),
                         "BIN=38")

    def test_single_file_non_cell_metadata(self):
        self.assertEqual(self._bin("BIDS.SliceTimingCorrected = true; BIDS.StartTime = 0.561"), "BIN=38")

    def test_start_time_zero_is_the_first_bin(self):
        self.assertEqual(self._bin("BIDS.SliceTimingCorrected = {true}; BIDS.StartTime = {0}"), "BIN=1")

    def test_not_corrected_gives_nothing(self):
        self.assertEqual(self._bin("BIDS.SliceTimingCorrected = {true, false}; BIDS.StartTime = {0.561, 0.561}"), "EMPTY")

    def test_missing_start_time_gives_nothing(self):
        self.assertEqual(self._bin("BIDS.SliceTimingCorrected = {true, true}; BIDS.StartTime = {0.561, []}"), "EMPTY")
        self.assertEqual(self._bin("BIDS.SliceTimingCorrected = {true}"), "EMPTY")

    def test_different_start_times_give_nothing(self):
        self.assertEqual(self._bin("BIDS.SliceTimingCorrected = {true, true}; BIDS.StartTime = {0.561, 0.3}"), "EMPTY")

    def test_no_metadata_at_all_gives_nothing(self):
        self.assertEqual(self._bin(""), "EMPTY")
