"""Opt-in model estimation in SPM's compiled standalone (MATLAB Runtime, no MATLAB licence).

bidspm itself stays on Octave (design and contrasts); only SPM's own ``fmri_est`` runs here.
The image is supplied by the user (see the README); we never pull or ship one.
"""
import os
import re
import subprocess
from pathlib import Path
from typing import List, Tuple

from .config import Config, ContainerConfig

_HOW_TO_GET_AN_IMAGE = (
    "Set 'spm_standalone_image' in your container config to an SPM standalone image you built "
    "(Docker: name@sha256:... or a local tag; Apptainer: path to a .sif). "
    "Build one from SPM's recipe: git clone https://github.com/spm/spm-docker, then in spm-docker/matlab run "
    "docker build -t spm-standalone:26.10.01 --build-arg MATLAB_VERSION=R2026a "
    "--build-arg SPM_RELEASE=26.10 --build-arg SPM_REVISION=01 ."
)
_ENV = {"MCR_INHIBIT_CTF_LOCK": "1", "SPM_HTML_BROWSER": "0", "HOME": "/tmp"}


def write_estimation_job(spm_mats: List[str], job_dir: Path) -> Path:
    """Write a batch job estimating each SPM.mat (container paths); ends with exit or the runtime hangs."""
    lines = ["spm('defaults', 'fmri');", "matlabbatch = {};"]
    for i, mat in enumerate(spm_mats, 1):
        lines += [f"matlabbatch{{{i}}}.spm.stats.fmri_est.spmmat = {{'{mat}'}};",
                  f"matlabbatch{{{i}}}.spm.stats.fmri_est.write_residuals = 0;",
                  f"matlabbatch{{{i}}}.spm.stats.fmri_est.method.Classical = 1;"]
    lines += ["spm_jobman('run', matlabbatch);", "clear all; close all force; exit;", ""]
    job_dir.mkdir(parents=True, exist_ok=True)
    job = job_dir / "job.m"
    job.write_text("\n".join(lines))
    return job


def build_spm_standalone_command(container_config: ContainerConfig, config: Config, job_dir: Path) -> List[str]:
    """Command running ``batch /job/job.m`` in the standalone, with /derivatives mounted as bidspm sees it."""
    image = container_config.spm_standalone_image
    mounts = [f"{config.DERIVATIVES_DIR}:/derivatives", f"{job_dir}:/job"]
    if container_config.container_type == "docker":
        cmd = ["docker", "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}"]
        for k, v in _ENV.items():
            cmd += ["-e", f"{k}={v}"]
        for m in mounts:
            cmd += ["-v", m]
    else:
        cmd = ["apptainer", "run", "--containall", "--writable-tmpfs"]
        for k, v in _ENV.items():
            cmd += ["--env", f"{k}={v}"]
        for m in mounts:
            cmd += ["--bind", m]
    return cmd + [image, "batch", "/job/job.m"]


def find_new_spm_mats(config: Config, subject: str, task: str, since: float) -> List[Path]:
    """SPM.mat files this run's design step wrote for the subject, task, space and FWHM."""
    stats = Path(config.DERIVATIVES_DIR) / "bidspm-stats" / f"sub-{subject}"
    pattern = re.compile(rf"task-{re.escape(task)}_space-{re.escape(config.SPACE)}_FWHM-([0-9.]+)")
    found = []
    for mat in sorted(stats.glob("*/SPM.mat")):
        m = pattern.match(mat.parent.name)
        if m and float(m.group(1)) == float(config.FWHM) and mat.stat().st_mtime >= since:
            found.append(mat)
    return found


def is_estimated(spm_mat: Path) -> bool:
    """Estimation wrote its first beta image next to this SPM.mat (the runtime can exit 0 without estimating)."""
    return any((spm_mat.parent / f"beta_0001{ext}").exists() for ext in (".nii", ".img"))


def check_image(container_config: ContainerConfig) -> Tuple[bool, str]:
    """Is the user-supplied image there? Run once before any subject; no pulling, no fallback."""
    image = container_config.spm_standalone_image
    if not image:
        return False, "No SPM standalone image configured. " + _HOW_TO_GET_AN_IMAGE
    if container_config.container_type == "docker":
        r = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", image],
                           capture_output=True, text=True)
        ok = r.returncode == 0
    else:
        ok = Path(image).is_file()
    return (True, image) if ok else (False, f"SPM standalone image not found: {image}. " + _HOW_TO_GET_AN_IMAGE)
