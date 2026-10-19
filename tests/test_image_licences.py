"""The image ships only clearly free/open-source content, credits upstream and carries its licence texts.

Dockerfile text checks (docker is not available in unit tests); the built image is checked by
tests/test_image_smoke.py. Evidence for every decision: docs/third-party-licenses.md.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (ROOT / "containers" / "dockerfile" / "dockerfile").read_text(encoding="utf-8")
LOGICAL = DOCKERFILE.replace("\\\n", " ")  # continuation lines joined
LICENSES = ROOT / "containers" / "dockerfile" / "licenses"
DOC = ROOT / "docs" / "third-party-licenses.md"

# restrictive (non-commercial / EULA / custom) or unclear/no licence -> must be deleted at build time
REMOVED = [
    "/opt/spm/tpm/labels_Neuromorphometrics.*",              # CC BY-NC
    "/opt/spm/toolbox/TSSS",                                 # non-commercial use only
    "/opt/spm/external/ctf",                                 # custom CTF/MISL permission
    "/opt/spm/external/ricoh_meg_reader",                    # RICOH EULA
    "/opt/spm/external/yokogawa_meg_reader",                 # RICOH/YOKOGAWA EULA
    "/opt/spm/external/mne/mne_block_diag.m",                # Brainstorm "for research purposes only"
    "/opt/spm/toolbox/MEEGtools/private/process_fooof.m",
    "/opt/spm/toolbox/MEEGtools/private/bst_prctile.m",
    "/opt/spm/toolbox/MEEGtools/private/macro_method.m",
    "/home/neuro/bidspm/lib/CPP_ROI/atlas/AAL3",             # no licence
    "/home/neuro/bidspm/lib/CPP_ROI/atlas/Glasser",          # HCP data use terms
    "/home/neuro/bidspm/lib/CPP_ROI/atlas/HCPex",            # derived from HCP-MMP1.0
    "/home/neuro/bidspm/lib/CPP_ROI/atlas/visfAtlas",        # no licence
    "/home/neuro/bidspm/lib/CPP_ROI/atlas/visual_topography_probability_atlas",  # Wang: no licence
    "/home/neuro/bidspm/lib/CPP_ROI/atlas/yeo_7networks",    # provenance unclear
    "/home/neuro/bidspm/lib/utils/cprintf.m",                # use/modify only, no redistribution grant
    "/home/neuro/bidspm/lib/utils/resize_img.m",             # no licence
    "/home/neuro/bidspm/lib/utils/plot_power_spectra_of_GLM_residuals.m",  # no licence
]


class TestRestrictedContentIsRemoved(unittest.TestCase):
    def test_each_restricted_path_is_deleted(self):
        removals = " ".join(re.findall(r"rm -rf ([^\n&]+)", LOGICAL))
        self.assertEqual([p for p in REMOVED if p not in removals], [])

    def test_build_fails_if_a_restricted_file_survives(self):
        # one guard over the whole image, so a later upstream bump cannot silently bring one back
        guard = re.search(r"RUN find / -xdev .*-iname '\*neuromorphometrics\*'.*\| grep -q \. && exit 1", LOGICAL)
        self.assertIsNotNone(guard)
        for name in ("TSSS", "AAL3*", "*glasser*", "HCPex*", "*visfAtlas*", "*wang_dseg*"):
            self.assertIn(f"-iname '{name}'", guard.group(0), name)
        self.assertIn("-name 'EULA*'", guard.group(0))  # case-sensitive: -iname '*eula*' matches zoneinfo/Beulah

    def test_git_history_is_not_shipped(self):
        # the submodule clones carry CPP_ROI's full history (every removed atlas, HCPex as a nested module)
        self.assertIn("rm -rf /home/neuro/bidspm/.git", LOGICAL)
        self.assertRegex(LOGICAL, r"find /home/neuro/bidspm -name \.git -prune -exec rm -rf")
        self.assertLess(LOGICAL.index("git clone /home/neuro/bidspm/lib/MACS"), LOGICAL.index("rm -rf /home/neuro/bidspm/.git"))

    def test_test_and_demo_data_is_not_shipped(self):
        self.assertRegex(LOGICAL, r"find /home/neuro/bidspm .*-name tests -o -name demos.* -exec rm -rf")

    def test_mathworks_helper_is_replaced_by_our_own(self):
        own = ROOT / "bidspm_overrides" / "lib" / "utils" / "renameStructField.m"
        self.assertNotIn("MathWorks", own.read_text(encoding="utf-8"))


class TestNoticeAndLabels(unittest.TestCase):
    def test_notice_and_licence_texts_are_copied_into_the_image(self):
        self.assertIn("COPY containers/dockerfile/licenses/ /usr/share/doc/spm-bids-runner/", DOCKERFILE)
        for src in ("/opt/spm/LICENCE", "/home/neuro/bidspm/LICENSE", "/home/neuro/bidspm/lib/bids-matlab/LICENSE"):
            self.assertIn(src, DOCKERFILE)

    def test_notice_credits_upstream_and_offers_source(self):
        notice = (LICENSES / "NOTICE").read_text(encoding="utf-8")
        for needle in ("bidspm", "Remi Gau", "Wellcome Centre for Human Neuroimaging", "GNU Octave",
                       "MRI-Lab Graz", "University of Graz", "https://github.com/spm/spm", "26.10.01",
                       "https://github.com/cpp-lln-lab/bidspm", "v4.0.0", "https://github.com/MRI-Lab-Graz/bidspm",
                       "corresponding source", "GPL-3.0"):
            self.assertIn(needle, notice, needle)

    def test_oci_labels(self):
        labels = dict(re.findall(r'(org\.opencontainers\.image\.\w+)="([^"]*)"', DOCKERFILE))
        self.assertEqual(labels.get("org.opencontainers.image.title"), "spm-bids-runner")
        self.assertEqual(labels.get("org.opencontainers.image.source"), "https://github.com/MRI-Lab-Graz/bidspm")
        self.assertEqual(labels.get("org.opencontainers.image.licenses"), "GPL-3.0-only")
        self.assertEqual(labels.get("org.opencontainers.image.version"), "${IMAGE_VERSION}")
        for key in ("description", "vendor", "documentation"):
            self.assertTrue(labels.get(f"org.opencontainers.image.{key}"), key)
        self.assertRegex(DOCKERFILE, r"ARG IMAGE_VERSION=")
        for upstream in ("at.mri-lab-graz.upstream.spm", "at.mri-lab-graz.upstream.bidspm",
                         "at.mri-lab-graz.upstream.octave"):
            self.assertIn(upstream, DOCKERFILE)

    def test_inventory_documents_every_removed_component(self):
        doc = DOC.read_text(encoding="utf-8")
        for name in ("Neuromorphometrics", "TSSS", "CTF", "RICOH", "YOKOGAWA", "Brainstorm", "AAL3", "Glasser",
                     "HCPex", "visfAtlas", "Wang", "Yeo", "cprintf", "resize_img", "renameStructField"):
            self.assertIn(name, doc, name)
