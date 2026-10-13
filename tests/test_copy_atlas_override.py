"""With the atlases baked into the image, copyAtlasToSpmDir must be read-only when they are present.

Upstream resolves the source files first by *creating* them (unzip, and for 'wang' a merge that
spm_write_vol()s into the CPP_ROI tree) -- fatal when the container runs as an arbitrary host uid.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

OVERRIDE = (Path(__file__).resolve().parent.parent / "bidspm_overrides" / "lib" / "CPP_ROI"
            / "src" / "atlas" / "copyAtlasToSpmDir.m")


def _stub(path: Path, name: str, body: str):
    (path / f"{name}.m").write_text(body)


@unittest.skipUnless(shutil.which("octave"), "octave not installed")
class TestCopyAtlasReadOnlyWhenPresent(unittest.TestCase):
    def _side_effects(self, atlas: str, target_names: list) -> list:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stubs, spm_dir, src = root / "stubs", root / "spm", root / "src"
            for d in (stubs, spm_dir / "atlas", src):
                d.mkdir(parents=True)
            for name in target_names:
                (spm_dir / "atlas" / name).write_text("x")
            marks = root / "marks.txt"
            mark = f"f = fopen('{marks}', 'a'); fprintf(f, '%s\\n', mfilename); fclose(f);"
            _stub(stubs, "spm", f"function r = spm(varargin)\n  r = '{spm_dir}';\nend\n")
            _stub(stubs, "returnAtlasDir", f"function d = returnAtlasDir(varargin)\n  d = '{src}';\nend\n")
            _stub(stubs, "spm_file", "function r = spm_file(p, varargin)\n  [~, n, e] = fileparts(p); r = [n e];\nend\n")
            for fn in ("spm_write_vol", "unzipAtlas", "spm_mkdir"):
                _stub(stubs, fn, f"function varargout = {fn}(varargin)\n  {mark}\n  varargout = cell(1, nargout);\nend\n")
            _stub(stubs, "spm_select", f"function r = spm_select(varargin)\n  {mark}\n  r = '';\nend\n")
            _stub(stubs, "spm_vol", f"function r = spm_vol(varargin)\n  {mark}\n  r = struct('fname', 'x');\nend\n")
            _stub(stubs, "spm_read_vols", f"function r = spm_read_vols(varargin)\n  {mark}\n  r = ones(2, 2, 2, 2);\nend\n")
            shutil.copy(OVERRIDE, stubs / "copyAtlasToSpmDir.m")
            subprocess.run(["octave-cli" if shutil.which("octave-cli") else "octave", "--no-gui", "--eval",
                            f"addpath('{stubs}'); copyAtlasToSpmDir('{atlas}');"],
                           capture_output=True, text=True, timeout=60)
            return marks.read_text().split() if marks.exists() else []

    def test_wang_present_causes_no_merge_or_write(self):
        self.assertEqual(self._side_effects(
            "Wang", ["space-MNI_seg-wang_dseg.nii", "space-MNI_seg-wang_dseg.xml"]), [])

    def test_hcpex_present_causes_no_unzip(self):
        self.assertEqual(self._side_effects("HCPex", ["HCPex.nii", "HCPex.xml"]), [])
