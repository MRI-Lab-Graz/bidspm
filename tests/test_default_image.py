"""The image name is ONE setting: lib.config.DEFAULT_DOCKER_IMAGE. Python reads the constant; files that cannot
import it (JSON, HTML, JS, shell, README, CI) must spell exactly that value. Old names must be gone everywhere."""
import re
import subprocess
import unittest
from pathlib import Path

from lib.config import DEFAULT_DOCKER_IMAGE
from lib.project_manager import ProjectConfig

ROOT = Path(__file__).resolve().parent.parent
OLD_NAMES = ("bidspm/bidspm:latest", "bidspm:spm26-atlas", "ghcr.io/mri-lab-graz/bidspm")
SPELLED = ["containers/container.json", "templates/analysis.html", "templates/projects.html",
           "static/js/analysis_project_form.js", "containers/dockerfile/build_mri_lab_container.sh",
           "scripts/setup_apple_silicon.sh", "README.md"]


class TestDefaultImage(unittest.TestCase):
    def test_the_setting(self):
        self.assertEqual(DEFAULT_DOCKER_IMAGE, "ghcr.io/mri-lab-graz/spm-bids-runner:latest")

    def test_python_defaults_use_the_constant(self):
        self.assertEqual(ProjectConfig().docker_image, DEFAULT_DOCKER_IMAGE)
        from webapp.web_config_fs_api import _default_config_payload, _default_container_payload
        self.assertEqual(_default_config_payload()["docker_image"], DEFAULT_DOCKER_IMAGE)
        self.assertEqual(_default_container_payload()["docker_image"], DEFAULT_DOCKER_IMAGE)

    def test_non_python_files_spell_the_setting(self):
        missing = [f for f in SPELLED if DEFAULT_DOCKER_IMAGE not in (ROOT / f).read_text(encoding="utf-8")]
        self.assertEqual(missing, [])

    def test_no_old_image_name_left_in_the_repo(self):
        files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
        skip = {"tests/test_default_image.py"}
        hits = [f for f in files if f not in skip and (ROOT / f).is_file()
                and any(n in (ROOT / f).read_text(encoding="utf-8", errors="ignore") for n in OLD_NAMES)]
        self.assertEqual(hits, [])

    def test_publish_workflow_uses_the_setting(self):
        wf = (ROOT / ".github/workflows/docker-publish.yml").read_text(encoding="utf-8")
        self.assertIn("IMAGE: " + DEFAULT_DOCKER_IMAGE.rsplit(":", 1)[0], wf)
        self.assertRegex(wf, r"permissions:\s+contents: read\s+packages: write")
        self.assertRegex(wf, r"version:\n\s+description: .*\n\s+required: true")
        self.assertRegex(wf, r"latest:\n\s+description: .*\n\s+type: boolean")
        self.assertIn("IMAGE_VERSION=${{ inputs.version }}", wf)
        self.assertIn("GIT_REVISION=${{ github.sha }}", wf)
        self.assertNotRegex(wf, r"IMAGE_NAME: \$\{\{ github.repository \}\}")
