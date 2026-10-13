"""Building blocks for the opt-in SPM-standalone estimation step."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from lib import spm_standalone as sa
from lib.config import ContainerConfig, load_container_config
from tests.test_core_helpers import _make_config

IMAGE = "spm-standalone@sha256:abc123"


class TestContainerConfigField(unittest.TestCase):
    def test_default_is_empty_and_loaded_from_json(self):
        self.assertEqual(ContainerConfig(container_type="docker").spm_standalone_image, "")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "c.json"
            p.write_text(json.dumps({"container_type": "docker", "spm_standalone_image": IMAGE}))
            self.assertEqual(load_container_config(str(p)).spm_standalone_image, IMAGE)


class TestJobFile(unittest.TestCase):
    def test_job_estimates_every_spm_mat_and_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = sa.write_estimation_job(["/derivatives/a/SPM.mat", "/derivatives/b/SPM.mat"], Path(tmp))
            text = job.read_text()
        self.assertEqual(job.name, "job.m")
        self.assertIn("spm('defaults', 'fmri')", text)
        self.assertEqual(text.count("fmri_est.spmmat"), 2)
        self.assertIn("{'/derivatives/a/SPM.mat'}", text)
        self.assertIn("{'/derivatives/b/SPM.mat'}", text)
        self.assertTrue(text.rstrip().endswith("exit;"))  # without it the runtime hangs at exit


class TestCommand(unittest.TestCase):
    def _config(self, tmp):
        return _make_config(Path(tmp))

    def test_docker_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._config(tmp)
            cmd = sa.build_spm_standalone_command(
                ContainerConfig(container_type="docker", spm_standalone_image=IMAGE), cfg, Path(tmp) / "job")
        self.assertEqual(cmd[:3], ["docker", "run", "--rm"])
        self.assertIn(f"{os.getuid()}:{os.getgid()}", cmd)
        for env in ("MCR_INHIBIT_CTF_LOCK=1", "SPM_HTML_BROWSER=0", "HOME=/tmp"):
            self.assertIn(env, cmd)
        self.assertIn(f"{cfg.DERIVATIVES_DIR}:/derivatives", cmd)
        self.assertEqual(cmd[-3:], [IMAGE, "batch", "/job/job.m"])

    def test_apptainer_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = self._config(tmp)
            cmd = sa.build_spm_standalone_command(
                ContainerConfig(container_type="apptainer", spm_standalone_image="/imgs/spm.sif"), cfg, Path(tmp) / "job")
        self.assertEqual(cmd[:2], ["apptainer", "run"])
        self.assertIn("MCR_INHIBIT_CTF_LOCK=1", cmd)
        self.assertIn(f"{cfg.DERIVATIVES_DIR}:/derivatives", cmd)
        self.assertEqual(cmd[-3:], ["/imgs/spm.sif", "batch", "/job/job.m"])


class TestFindNewSpmMats(unittest.TestCase):
    def _make(self, root: Path, name: str, mtime: float):
        d = root / "bidspm-stats" / "sub-01" / name
        d.mkdir(parents=True)
        f = d / "SPM.mat"
        f.write_text("x")
        os.utime(f, (mtime, mtime))
        return f

    def test_only_this_task_space_fwhm_and_fresh_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = _make_config(Path(tmp))  # SPACE MNI152NLin2009cAsym, FWHM 6.0
            root, now = cfg.DERIVATIVES_DIR, time.time()
            want = self._make(root, "task-motor_space-MNI152NLin2009cAsym_FWHM-6_node-run", now)
            self._make(root, "task-motor_space-MNI152NLin2009cAsym_FWHM-9_node-run", now)   # other fwhm
            self._make(root, "task-other_space-MNI152NLin2009cAsym_FWHM-6_node-run", now)   # other task
            self._make(root, "task-motor_space-MNI152NLin2009cAsym_FWHM-6_node-old", now - 3600)  # stale
            self.assertEqual(sa.find_new_spm_mats(cfg, "01", "motor", since=now - 60), [want])


class TestPreflight(unittest.TestCase):
    def test_empty_setting_explains_how_to_get_an_image(self):
        ok, msg = sa.check_image(ContainerConfig(container_type="docker"))
        self.assertFalse(ok)
        self.assertIn("spm_standalone_image", msg)
        self.assertIn("spm-docker", msg)

    def test_docker_image_must_exist_locally(self):
        cc = ContainerConfig(container_type="docker", spm_standalone_image=IMAGE)
        with patch("lib.spm_standalone.subprocess.run", return_value=MagicMock(returncode=0, stdout="sha256:1\n")):
            self.assertTrue(sa.check_image(cc)[0])
        with patch("lib.spm_standalone.subprocess.run", return_value=MagicMock(returncode=1, stdout="")):
            ok, msg = sa.check_image(cc)
        self.assertFalse(ok)
        self.assertIn(IMAGE, msg)

    def test_apptainer_image_must_be_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            sif = Path(tmp) / "spm.sif"
            cc = ContainerConfig(container_type="apptainer", spm_standalone_image=str(sif))
            self.assertFalse(sa.check_image(cc)[0])
            sif.write_text("x")
            self.assertTrue(sa.check_image(cc)[0])
