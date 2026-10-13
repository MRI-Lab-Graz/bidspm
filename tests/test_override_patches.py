"""Overrides that change only a few lines are patches against upstream v4.0.0, not whole-file copies."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATCHES = ROOT / "containers" / "dockerfile" / "patches"
OVERRIDES = ROOT / "bidspm_overrides"
DOCKERFILE = (ROOT / "containers" / "dockerfile" / "dockerfile").read_text(encoding="utf-8")


def _patched_files(patch: Path):
    return re.findall(r"^\+\+\+ b/(\S+)", patch.read_text(encoding="utf-8"), re.M)


class TestOverridePatches(unittest.TestCase):
    def test_there_are_patches_and_each_is_a_unified_diff(self):
        patches = sorted(PATCHES.glob("*.patch"))
        self.assertGreaterEqual(len(patches), 9)
        for p in patches:
            self.assertEqual(len(_patched_files(p)), 1, p.name)
            self.assertIn("\n@@ ", p.read_text(encoding="utf-8"), p.name)

    def test_no_file_is_both_patched_and_fully_overridden(self):
        both = [f for p in PATCHES.glob("*.patch") for f in _patched_files(p) if (OVERRIDES / f).exists()]
        self.assertEqual(both, [])

    def test_dockerfile_applies_patches_before_copying_overrides(self):
        self.assertIn("COPY containers/dockerfile/patches/", DOCKERFILE)
        self.assertRegex(DOCKERFILE, r"patch -p1 .*\.patch")
        self.assertLess(DOCKERFILE.index("patch -p1"), DOCKERFILE.index("COPY bidspm_overrides/"))

    def test_overrides_readme_names_each_patched_file(self):
        readme = (OVERRIDES / "README.md").read_text(encoding="utf-8")
        for p in PATCHES.glob("*.patch"):
            for f in _patched_files(p):
                self.assertIn(Path(f).name, readme, f)
