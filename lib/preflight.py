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


def _func_files(root, sub, pattern):
    return sorted(p for p in (Path(root) / f"sub-{sub}").rglob(pattern) if p.parent.name == "func")


def _read_tsv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def _events_problems(sub, name, cols, rows):
    missing = [c for c in ("onset", "duration") if c not in cols]
    if missing:
        return [_item("events_columns", ERROR, f"{name} has no {' / '.join(missing)} column",
                      "Events files need onset and duration columns (tab-separated).", sub)]
    for n, row in enumerate(rows, start=2):
        try:
            ok = float(row["onset"]) >= 0 and float(row["duration"]) >= 0
        except (TypeError, ValueError):
            ok = False
        if not ok:
            return [_item("events_values", ERROR,
                          f"{name} line {n}: onset/duration must be non-negative numbers (got {row['onset']!r}, {row['duration']!r})",
                          "Fix or remove that row (n/a is not allowed in onset or duration).", sub)]
    return []


def check_subject_task(bids_dir, fmriprep_dir, sub, task, space):
    out = []
    if not _func_files(fmriprep_dir, sub, f"*task-{task}_*space-{space or '*'}_*desc-preproc_bold.nii.gz"):
        out.append(_item("preproc_missing", ERROR,
                         f"sub-{sub} has no preprocessed BOLD for task-{task} in space {space or '(any)'}",
                         f"Re-run fMRIPrep with --output-spaces {space or '<space>'}, or change the Space setting.", sub))
    events = _func_files(bids_dir, sub, f"*task-{task}_*events.tsv")
    if not events:
        out.append(_item("events_missing", ERROR, f"sub-{sub} has no events file for task-{task}",
                         "Add sub-*/func/*_task-*_events.tsv to the BIDS dataset.", sub))
    for path in events:
        cols, rows = _read_tsv(path)
        out += _events_problems(sub, path.name, cols, rows)
    return out


def run_preflight(bids_dir, fmriprep_dir, model_file="", tasks=(), space="", subjects=(),
                  validator="prism", container_type=""):
    checks = check_dirs(bids_dir, fmriprep_dir)
    if not checks:
        from lib.core import discover_tasks  # lazy: keeps module import light
        tasks = list(tasks) or discover_tasks(Path(bids_dir))
        selected, found = check_subjects(bids_dir, fmriprep_dir, subjects)
        checks += found
        present = set(_subjects_in(bids_dir)) & set(_subjects_in(fmriprep_dir))
        for task in tasks:
            for sub in selected:
                if sub in present:
                    checks += check_subject_task(bids_dir, fmriprep_dir, sub, task, space)
    return {"verdict": _verdict(checks), "checks": checks}
