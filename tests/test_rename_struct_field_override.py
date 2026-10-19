"""Own renameStructField (the upstream copy is a MathWorks file without a licence): renames, keeps field order."""
import shutil
import subprocess
import unittest
from pathlib import Path

OVERRIDE_DIR = Path(__file__).resolve().parent.parent / "bidspm_overrides" / "lib" / "utils"


@unittest.skipUnless(shutil.which("octave-cli"), "octave not installed")
class TestRenameStructField(unittest.TestCase):
    def _eval(self, code):
        out = subprocess.run(["octave-cli", "--no-gui", "--eval", f"addpath('{OVERRIDE_DIR}'); {code}"],
                             capture_output=True, text=True, timeout=60)
        return (out.stdout + out.stderr).strip()

    def test_renames_in_place(self):
        self.assertEqual(self._eval(
            "s = renameStructField(struct('a', 1, 'b', 2, 'c', 3), 'b', 'x'); "
            "printf('%s ', fieldnames(s){:}); printf('%d', s.x);"), "a x c 2")

    def test_rename_onto_an_existing_field_overwrites_it(self):
        self.assertEqual(self._eval(
            "s = renameStructField(struct('a', 1, 'b', 2), 'a', 'b'); printf('%s ', fieldnames(s){:}); printf('%d', s.b);"),
            "b 1")

    def test_missing_or_same_name_is_a_no_op(self):
        self.assertEqual(self._eval(
            "s = renameStructField(struct('a', 1), 'z', 'y'); t = renameStructField(s, 'a', 'a'); "
            "printf('%s ', fieldnames(s){:}, fieldnames(t){:});"), "a a")

    def test_struct_arrays(self):
        self.assertEqual(self._eval(
            "s = renameStructField(struct('a', {1, 2}), 'a', 'b'); printf('%d', s.b);"), "12")
