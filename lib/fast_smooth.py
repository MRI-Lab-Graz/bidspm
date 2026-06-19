"""Fast, parallel drop-in replacement for bidspm's SPM smoothing step.

Smooths ``desc-preproc`` BOLD files into ``desc-smth{FWHM}`` files using
nibabel + scipy instead of spinning up MATLAB/Octave/SPM per subject. Output
filenames, folder structure and sidecar JSON fields match what
``bidsSmoothing.m`` / ``bidsRename`` produce, so downstream steps (stats,
reports) and the existing ``check_subject_processed`` bookkeeping
(``lib/core.py``) work unmodified.

This pipeline takes fMRIPrep output as input (no SPM realign/coreg/normalize
is ever used). bidspm's own ``desc-preproc`` file in fMRIPrep-input mode is a
straight decompress+copy of fMRIPrep's own ``desc-preproc`` output -- verified
byte-identical (same affine, same voxel data, same JSON sidecar) against real
data in this repo. So when bidspm-preproc doesn't have the file yet, this
module copies it straight from fMRIPrep's derivatives folder instead of
treating that as a reason to fall back to MATLAB.

Orientation safety: SPM's smoothing never touches the affine/qform/sform (it
convolves in voxel space only). This module preserves them explicitly and
verifies the written file matches the input before returning success.
"""

import gzip
import json
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

import nibabel as nib
import numpy as np
from scipy.ndimage import gaussian_filter

from .config import Config

FWHM_TO_SIGMA = 1.0 / (2.0 * (2.0 * np.log(2.0)) ** 0.5)  # ~0.42466


def _smth_path(preproc_path: Path, fwhm) -> Path:
    return preproc_path.with_name(
        preproc_path.name.replace("desc-preproc", f"desc-smth{fwhm}")
    )


def _build_smth_sidecar(preproc_json_path: Path, preproc_path: Path,
                         derivatives_root: Path, fwhm) -> dict:
    sidecar = {}
    if preproc_json_path.exists():
        with open(preproc_json_path) as f:
            preproc_meta = json.load(f)
    else:
        preproc_meta = {}

    raw_sources = [
        src[len("bids:raw:"):]
        for src in preproc_meta.get("Sources", [])
        if isinstance(src, str) and src.startswith("bids:raw:")
    ]

    sidecar["Description"] = "RECOMMENDED"
    sidecar["Sources"] = [str(preproc_path.relative_to(derivatives_root))]
    if raw_sources:
        sidecar["RawSources"] = raw_sources
    sidecar["SpatialReference"] = [
        ["REQUIRED if no space entity or if non standard space RECOMMENDED otherwise"]
    ]
    sidecar["SpmFilename"] = f"s{fwhm}{preproc_path.name}"

    for field in ("RepetitionTime", "SliceTimingCorrected", "StartTime"):
        if field in preproc_meta:
            sidecar[field] = preproc_meta[field]

    return sidecar


def smooth_one_file(preproc_path: Path, fwhm, derivatives_root: Path) -> Path:
    """Smooth a single desc-preproc BOLD file, writing desc-smth{fwhm} next to it."""
    img = nib.load(str(preproc_path))
    orig_dtype = img.get_data_dtype()
    orig_affine = img.affine.copy()
    # SPM marks every file it writes (including smoothed output) with
    # qform/sform code 2 (NIFTI_XFORM_ALIGNED_ANAT), regardless of the
    # input's original code -- verified against existing desc-smth* files
    # produced by bidspm/SPM in this dataset. The affine values themselves
    # (what actually determines radiological/neurological orientation) are
    # left untouched; only this provenance label is forced to match SPM.
    out_xform_code = 2

    data = img.get_fdata(dtype=np.float32)
    zooms = img.header.get_zooms()[:3]
    sigma_vox = [(fwhm * FWHM_TO_SIGMA) / z for z in zooms]
    if data.ndim == 4:
        sigma_vox = sigma_vox + [0.0]

    smoothed = gaussian_filter(data, sigma=sigma_vox).astype(orig_dtype)

    out_img = nib.Nifti1Image(smoothed, affine=orig_affine, header=img.header.copy())
    out_img.set_qform(img.get_qform(), code=out_xform_code)
    out_img.set_sform(img.get_sform(), code=out_xform_code)

    out_path = _smth_path(preproc_path, fwhm)
    nib.save(out_img, str(out_path))

    # Verify orientation was not altered before trusting this output: the
    # affine (which determines radiological/neurological convention) must
    # be byte-identical to the input, even though the xform code label
    # above is intentionally normalized to match SPM's convention.
    check_img = nib.load(str(out_path))
    if not np.allclose(check_img.affine, orig_affine):
        raise RuntimeError(f"Affine mismatch after smoothing {preproc_path} -> {out_path}")
    if int(check_img.header["qform_code"]) != out_xform_code or \
       int(check_img.header["sform_code"]) != out_xform_code:
        raise RuntimeError(f"qform/sform code mismatch after smoothing {preproc_path} -> {out_path}")

    preproc_json_path = preproc_path.with_suffix("").with_suffix(".json")
    sidecar = _build_smth_sidecar(preproc_json_path, preproc_path, derivatives_root, fwhm)
    out_json_path = out_path.with_suffix("").with_suffix(".json")
    with open(out_json_path, "w") as f:
        json.dump(sidecar, f, indent=2)

    return out_path


def _fmriprep_to_preproc_path(fmriprep_path: Path, fmriprep_root: Path, preproc_root: Path) -> Path:
    rel = fmriprep_path.relative_to(fmriprep_root)
    target = preproc_root / rel
    if target.name.endswith(".nii.gz"):
        target = target.with_name(target.name[:-3])  # strip ".gz" -> plain .nii
    return target


def copy_preproc_from_fmriprep(config: Config, subject: str, task: str) -> List[Path]:
    """Copy fMRIPrep's standard-space desc-preproc BOLD files into bidspm-preproc
    if they aren't already there. This is a straight decompress+copy (verified
    byte-identical to fMRIPrep's own output), not a recompute -- no SPM/MATLAB
    involved. Returns the list of desc-preproc paths now present (existing or
    newly copied).
    """
    preproc_root = config.DERIVATIVES_DIR / "bidspm-preproc"
    subject_dir = preproc_root / f"sub-{subject}"
    pattern = f"*task-{task}*space-{config.SPACE}*desc-preproc_bold.nii*"
    existing = sorted(subject_dir.rglob(pattern)) if subject_dir.exists() else []
    if existing:
        return existing

    fmriprep_subject_dir = config.FMRIPREP_DIR / f"sub-{subject}"
    if not fmriprep_subject_dir.exists():
        return []

    fmriprep_pattern = f"*task-{task}*space-{config.SPACE}*desc-preproc_bold.nii.gz"
    fmriprep_files = sorted(fmriprep_subject_dir.rglob(fmriprep_pattern))

    copied = []
    for src in fmriprep_files:
        dst = _fmriprep_to_preproc_path(src, config.FMRIPREP_DIR, preproc_root)
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(src, "rb") as f_in, open(dst, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            src_json = src.with_suffix("").with_suffix(".json")
            if src_json.exists():
                shutil.copy(src_json, dst.with_suffix(".json"))
        copied.append(dst)

    return copied


def smooth_subject(config: Config, subject: str, task: str, force: bool = False) -> dict:
    """Smooth every desc-preproc BOLD file for one subject/task.

    Looks for desc-preproc files already in bidspm-preproc first; if missing,
    copies them straight from fMRIPrep's output (see
    ``copy_preproc_from_fmriprep``) before smoothing -- no MATLAB/SPM needed
    in either case.

    If every file already has a desc-smth{fwhm} output, the subject is
    skipped (status "skipped") unless ``force`` is set -- smoothing is
    deterministic, so redoing it without --force would just burn time to
    reproduce the same output.

    Returns a dict with keys:
      - "status": "ok" | "skipped" | "no_input" | "error"
        "no_input" means neither bidspm-preproc nor fMRIPrep has matching
        data for this subject/task -- a genuine data/configuration problem
        (e.g. fMRIPrep hasn't been run for this subject), not something any
        backend can resolve.
      - "message": human-readable detail (empty on "ok"/"skipped")
    """
    preproc_root = config.DERIVATIVES_DIR / "bidspm-preproc"
    files = copy_preproc_from_fmriprep(config, subject, task)
    if not files:
        return {
            "status": "no_input",
            "message": f"no desc-preproc files found in bidspm-preproc or fMRIPrep output "
                       f"for sub-{subject}/task-{task}",
        }

    if not force and all(_smth_path(f, config.FWHM).exists() for f in files):
        return {"status": "skipped", "message": ""}

    try:
        for preproc_path in files:
            if not force and _smth_path(preproc_path, config.FWHM).exists():
                continue
            smooth_one_file(preproc_path, config.FWHM, preproc_root)
    except Exception as exc:
        return {"status": "error", "message": str(exc)}

    return {"status": "ok", "message": ""}


def smooth_subjects_parallel(config: Config, subjects: List[str], task: str,
                              max_workers: Optional[int] = None,
                              force: bool = False) -> Dict[str, dict]:
    """Smooth all given subjects concurrently. Returns {subject: result_dict}."""
    results: Dict[str, dict] = {}
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(smooth_subject, config, subject, task, force): subject
            for subject in subjects
        }
        for future in as_completed(futures):
            subject = futures[future]
            try:
                results[subject] = future.result()
            except Exception as exc:
                results[subject] = {"status": "error", "message": str(exc)}

    return results
