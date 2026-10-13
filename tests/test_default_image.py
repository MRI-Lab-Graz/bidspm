"""Defaults must point at the image the README tells users to build, not at the published SPM12-era one
(this code mounts and patches things differently, so the old image would silently misbehave)."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLISHED = "ghcr.io/mri-lab-graz/bidspm"
FILES = ["containers/container.json", "lib/project_manager.py", "webapp/web_config_fs_api.py",
         "templates/analysis.html", "templates/projects.html"]


class TestDefaultImage(unittest.TestCase):
    def test_no_default_points_at_the_published_image(self):
        offenders = [f for f in FILES if PUBLISHED in (ROOT / f).read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])

    def test_container_json_uses_the_locally_built_tag(self):
        self.assertIn('"bidspm/bidspm:latest"', (ROOT / "containers/container.json").read_text())
