"""The image has no graphics toolkit: any batch module that draws a figure fails the whole job.

SPM's 'Model review' (spm_DesRep) did exactly that at the dataset level, after the estimation, so the
group contrasts were never written while bidspm still exited 0.
"""
import unittest
from pathlib import Path

OVERRIDES = Path(__file__).resolve().parent.parent / "bidspm_overrides"


class TestNoGraphicalModules(unittest.TestCase):
    def test_no_override_adds_a_review_module(self):
        offenders = [str(p.relative_to(OVERRIDES)) for p in OVERRIDES.rglob("*.m")
                     if "spm.stats.review" in p.read_text(errors="ignore")]
        self.assertEqual(offenders, [])
