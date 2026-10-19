"""The image ships no atlas (licences): asking for one is a clear error, and results labelling degrades to a warning.

returnAtlasDir is where every CPP_ROI atlas lookup goes through (getAtlasFilename, getLookUpTable,
copyAtlasToSpmDir), so the 'not in this image' error lives there once.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERRIDE = ROOT / "bidspm_overrides" / "lib" / "CPP_ROI" / "atlas" / "returnAtlasDir.m"
PATCH = ROOT / "containers" / "dockerfile" / "patches" / "labelActivations.patch"
UPSTREAM = Path("/data/local/container/bidspm/bidspm")  # bidspm v4.0.0 checkout on the dev server
OCTAVE = shutil.which("octave-cli")


def _octave(code, *dirs):
    paths = "".join(f"addpath('{d}');" for d in dirs)
    out = subprocess.run([OCTAVE, "--no-gui", "--eval", paths + code], capture_output=True, text=True, timeout=60)
    return (out.stdout + out.stderr).strip()


@unittest.skipUnless(OCTAVE, "octave not installed")
class TestReturnAtlasDir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.atlas = self.tmp / "atlas"
        self.stubs = self.tmp / "stubs"
        self.spm = self.tmp / "spm"
        for d in (self.atlas, self.stubs, self.spm / "tpm"):
            d.mkdir(parents=True)
        shutil.copy(OVERRIDE, self.atlas)
        (self.stubs / "spm.m").write_text(f"function r = spm(varargin)\n  r = '{self.spm}';\nend\n")
        (self.stubs / "spm_file.m").write_text("function r = spm_file(p, varargin)\n  r = p;\nend\n")

    def _call(self, atlas):
        return _octave(f"try; disp(returnAtlasDir('{atlas}')); catch e; disp(e.identifier); disp(e.message); end",
                       self.stubs, self.atlas)

    def test_missing_atlas_is_a_clear_error(self):
        out = self._call("wang")
        self.assertIn("returnAtlasDir:atlasMissing", out)
        self.assertIn("licence", out)
        self.assertIn(str(self.atlas / "visual_topography_probability_atlas"), out)
        self.assertIn("README", out)

    def test_present_atlas_returns_its_dir(self):
        (self.atlas / "Glasser").mkdir()
        self.assertEqual(self._call("glasser"), str(self.atlas / "Glasser"))

    def test_aal_is_known(self):  # copyAtlasToSpmDir asks for it by name now
        (self.atlas / "AAL3").mkdir()
        self.assertEqual(self._call("aal"), str(self.atlas / "AAL3"))

    def test_neuromorphometrics_needs_the_spm_labels(self):
        out = self._call("neuromorphometrics")
        self.assertIn("returnAtlasDir:atlasMissing", out)
        self.assertIn("labels_Neuromorphometrics.nii", out)
        (self.spm / "tpm" / "labels_Neuromorphometrics.nii").write_text("x")
        self.assertEqual(self._call("neuromorphometrics"), str(self.atlas))

    def test_no_argument_is_the_atlas_root(self):
        self.assertEqual(_octave("disp(returnAtlasDir())", self.stubs, self.atlas), str(self.atlas))


@unittest.skipUnless(OCTAVE and shutil.which("patch") and (UPSTREAM / "src").is_dir(), "needs octave + upstream bidspm")
class TestLabelActivationsWithoutAtlas(unittest.TestCase):
    def test_missing_atlas_leaves_the_table_unlabelled_with_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            src = tmp / "src" / "stats" / "utils"
            src.mkdir(parents=True)
            shutil.copy(UPSTREAM / "src" / "stats" / "utils" / "labelActivations.m", src)
            subprocess.run(["patch", "-p1", "-s", "-d", str(tmp), "-i", str(PATCH)], check=True)
            stubs = tmp / "stubs"
            stubs.mkdir()
            err = "error('returnAtlasDir:atlasMissing', 'Atlas \"%s\" is not included in this image', varargin{1});"
            for fn in ("returnAtlasDir", "copyAtlasToSpmDir"):
                (stubs / f"{fn}.m").write_text(f"function {fn}(varargin)\n  {err}\nend\n")
            (stubs / "logger.m").write_text("function logger(level, msg, varargin)\n  printf('LOG %s %s\\n', level, msg);\nend\n")
            for atlas in ("Neuromorphometrics", "wang"):
                out = _octave(f"t = labelActivations('x.csv', 'atlas', '{atlas}'); printf('RET[%s]\\n', t);", src, stubs)
                self.assertIn("LOG WARNING", out, atlas)
                self.assertIn("not included in this image", out, atlas)
                self.assertIn("without region labels", out, atlas)
                self.assertIn("RET[]", out, atlas)
