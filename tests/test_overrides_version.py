"""The image's override version is printed at the start of every stats run, so a log shows whether the image has the
run-averaging fix (contrasts 1/n per run) or predates it (summed runs)."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "bidspm_overrides"


def test_version_file_names_the_run_averaging():
    text = (ROOT / "OVERRIDES_VERSION").read_text()
    assert "runs-averaged" in text


@unittest.skipUnless(shutil.which("octave"), "octave not installed")
class TestCliStatsPrintsTheVersion(unittest.TestCase):
    def test_stats_log_starts_with_the_override_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            cli = Path(tmp) / "src" / "cli"
            cli.mkdir(parents=True)
            shutil.copy(ROOT / "src" / "cli" / "cliStats.m", cli / "cliStats.m")
            shutil.copy(ROOT / "OVERRIDES_VERSION", Path(tmp) / "OVERRIDES_VERSION")
            out = subprocess.run(["octave-cli" if shutil.which("octave-cli") else "octave", "--no-gui", "--eval",
                                  f"addpath('{cli}'); try; cliStats(); catch; end"],
                                 capture_output=True, text=True, timeout=60)
        self.assertIn("bidspm runner overrides: " + (ROOT / "OVERRIDES_VERSION").read_text().splitlines()[0], out.stdout)
