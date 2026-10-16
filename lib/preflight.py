"""Preflight readiness check: can this BIDS + fMRIPrep + model combination run?

Pure functions, no Flask. Every check returns a list of items
{"id", "severity": "error"|"warn", "subject", "message", "fix"}; run_preflight() returns {"verdict", "checks"}.
"""
import csv
import fnmatch
import json
import shutil
import subprocess
import sys
from pathlib import Path

ERROR, WARN = "error", "warn"


def _item(id, severity, message, fix="", subject=None):
    return {"id": id, "severity": severity, "subject": subject, "message": message, "fix": fix}


def _subjects_in(root):
    return sorted(p.name[4:] for p in Path(root).glob("sub-*") if p.is_dir())


def _verdict(checks):
    severities = {c["severity"] for c in checks}
    return "blocked" if ERROR in severities else "warnings" if WARN in severities else "ready"


def check_dirs(bids_dir, fmriprep_dir):
    out = []
    for id, label, path in (("bids_dir", "BIDS", bids_dir), ("fmriprep_dir", "fMRIPrep", fmriprep_dir)):
        p = Path(path) if path else None
        if not p or not p.is_dir():
            out.append(_item(id, ERROR, f"{label} folder not found: {path or '(not set)'}",
                             f"Set the {label} folder to the dataset root."))
        elif not (p / "dataset_description.json").is_file():
            out.append(_item(id, ERROR, f"{label} folder has no dataset_description.json: {p}",
                             "Select the dataset root (the folder that contains dataset_description.json)."))
        elif not _subjects_in(p):
            out.append(_item(id, ERROR, f"{label} folder contains no sub-* folders: {p}",
                             "Check that you selected the right folder."))
    return out


def check_subjects(bids_dir, fmriprep_dir, subjects):
    """Resolve the selected subjects (default: all in fMRIPrep) and check they exist in both trees."""
    selected = [str(s).removeprefix("sub-") for s in subjects] or _subjects_in(fmriprep_dir)
    out = []
    for label, root in (("BIDS", bids_dir), ("fMRIPrep", fmriprep_dir)):
        have = set(_subjects_in(root))
        out += [_item("subject_missing", ERROR, f"sub-{s} not found in the {label} folder",
                      f"Remove sub-{s} from the subject selection or add its data.", s)
                for s in selected if s not in have]
    return selected, out


def run_preflight(bids_dir, fmriprep_dir, model_file="", tasks=(), space="", subjects=(),
                  validator="prism", container_type=""):
    checks = check_dirs(bids_dir, fmriprep_dir)
    if not checks:
        _, found = check_subjects(bids_dir, fmriprep_dir, subjects)
        checks += found
    return {"verdict": _verdict(checks), "checks": checks}
