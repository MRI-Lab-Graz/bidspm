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
    with open(path, newline="", encoding="utf-8-sig") as fh:
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


def _model_needs(model_file):
    """(trial_type conditions, nuisance regressor names, uses Transformations) from the Run-level nodes."""
    conditions, nuisance, transformed = set(), [], False
    try:
        model = json.loads(Path(model_file).read_text()) if model_file else {}
    except (OSError, ValueError):
        return conditions, nuisance, transformed  # check_model reports unreadable models
    for node in model.get("Nodes", []):
        if node.get("Level") != "Run":
            continue
        transformed = transformed or bool(node.get("Transformations"))
        for x in node.get("Model", {}).get("X", []):
            if not isinstance(x, str):
                continue
            if x.startswith("trial_type."):
                conditions.add(x.split(".", 1)[1])
            elif "." not in x:
                nuisance.append(x)
    return conditions, nuisance, transformed


def _scan_length_warning(sub, preproc, events_rows):
    import nibabel as nib
    sidecar = preproc.with_name(preproc.name.replace(".nii.gz", ".json"))
    try:
        tr = json.loads(sidecar.read_text())["RepetitionTime"]
        scan = nib.load(preproc).shape[3] * tr
        end = max(float(r["onset"]) + float(r["duration"]) for r in events_rows)
    except (OSError, ValueError, KeyError, IndexError):
        return []
    if end > scan + tr:
        return [_item("scan_length", WARN, f"sub-{sub}: events run to {end:.0f}s but the scan is only {scan:.0f}s long",
                      "Check that the events file belongs to this run.", sub)]
    return []


def check_subject_task(bids_dir, fmriprep_dir, sub, task, space, needs=(set(), [], False)):
    """Returns (items, trial_type values seen in this subject's events files)."""
    conditions, nuisance, transformed = needs
    out, seen = [], set()
    preproc = _func_files(fmriprep_dir, sub, f"*task-{task}_*space-{space or '*'}_*desc-preproc_bold.nii.gz")
    if not preproc:
        out.append(_item("preproc_missing", ERROR,
                         f"sub-{sub} has no preprocessed BOLD for task-{task} in space {space or '(any)'}",
                         f"Re-run fMRIPrep with --output-spaces {space or '<space>'}, or change the Space setting.", sub))
    events = _func_files(bids_dir, sub, f"*task-{task}_*events.tsv")
    if not events:
        out.append(_item("events_missing", ERROR, f"sub-{sub} has no events file for task-{task}",
                         "Add sub-*/func/*_task-*_events.tsv to the BIDS dataset.", sub))
    events_ok = True
    for path in events:
        try:
            cols, rows = _read_tsv(path)
        except (OSError, UnicodeDecodeError, csv.Error) as e:
            out.append(_item("events_columns", ERROR, f"{path.name} cannot be read as UTF-8 text ({e})",
                             "Save the events file as a tab-separated UTF-8 text file.", sub))
            events_ok = False
            continue
        problems = _events_problems(sub, path.name, cols, rows)
        out += problems
        events_ok = events_ok and not problems
        if conditions and not transformed:
            if "trial_type" not in cols:
                out.append(_item("events_trial_type", ERROR,
                                 f"{path.name} has no trial_type column but the model uses trial_type.* conditions",
                                 "Add a trial_type column or change the model's regressors.", sub))
                events_ok = False
            else:
                seen |= {r["trial_type"] for r in rows}
    if len(preproc) == 1 and len(events) == 1 and events_ok:
        out += _scan_length_warning(sub, preproc[0], rows)
    if nuisance:
        files = _func_files(fmriprep_dir, sub, f"*task-{task}_*desc-confounds_timeseries.tsv")
        if not files:
            out.append(_item("confounds_missing", ERROR,
                             f"sub-{sub} has no confounds file for task-{task}",
                             f"Re-run fMRIPrep; confounds are needed for {', '.join(nuisance)}.", sub))
        for f in files:
            try:
                cols = _read_tsv(f)[0]
            except (OSError, UnicodeDecodeError, csv.Error) as e:
                out.append(_item("confound_columns", ERROR, f"{f.name} cannot be read as UTF-8 text ({e})",
                                 "Re-run fMRIPrep to regenerate the confounds file.", sub))
                continue
            missing = [n for n in nuisance if not any(fnmatch.fnmatch(c, n) for c in cols)]
            if missing:
                out.append(_item("confound_columns", ERROR,
                                 f"{f.name} lacks the model's regressors: {', '.join(missing)}",
                                 "Fix the regressor names in the model, or re-run fMRIPrep so they are produced.", sub))
    return out, seen


def check_model(model_file):
    if not model_file:
        return []
    from lib import core  # lazy so tests can patch lib.core.validate_bids_model
    result = core.validate_bids_model(Path(model_file))
    if not result["valid"]:
        return [_item("model", ERROR, result.get("error", "The model is invalid."),
                      "Fix the model in the editor ('Validate JSON' shows the same message).")]
    if result.get("warning"):
        return [_item("model", WARN, result["warning"])]
    return []


def check_container(container_type):
    if container_type in ("docker", "apptainer") and not shutil.which(container_type):
        return [_item("container", WARN, f"{container_type} was not found on this machine",
                      f"Install {container_type}, or pick the other container type.")]
    return []


def check_validator(bids_dir, mode="prism", run=subprocess.run):
    """Run prism-validator --json (BIDS validator + PRISM checks); never --fix, never --plugins."""
    if mode == "skip":
        return [_item("validator", WARN, "Dataset validator skipped.", "Choose 'PRISM' or 'plain BIDS' to validate the dataset.")]
    exe = Path(sys.executable).parent / "prism-validator"
    exe = str(exe) if exe.is_file() else shutil.which("prism-validator")
    if not exe:
        return [_item("validator", WARN, "prism-validator is not installed; the dataset was not validated.", "Run: uv sync")]
    cmd = [exe, str(bids_dir), "--json"] + (["--no-prism"] if mode == "bids" else [])
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=1800)  # ponytail: no result cache; add one if validation proves slow
        issues = json.loads(proc.stdout[proc.stdout.index("{"):]).get("issues", [])
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return [_item("validator", WARN, f"The dataset validator produced no report ({exc}).", "Run prism-validator by hand to see why.")]
    out = [_item("validator", ERROR, f"{i['code']}: {i['message'].splitlines()[0]} ({i.get('file_path', '')})",
                 "Fix the dataset, or choose 'skip' if the problem is unrelated to this analysis (e.g. DWI).")
           for i in issues if i.get("severity") == "ERROR"]
    warns = [i for i in issues if i.get("severity") == "WARNING"]
    if warns:
        out.append(_item("validator", WARN, f"{len(warns)} validator warning(s): " + ", ".join(sorted({w['code'] for w in warns}))))
    return out


def run_preflight(bids_dir, fmriprep_dir, model_file="", tasks=(), space="", subjects=(),
                  validator="prism", container_type=""):
    checks = check_dirs(bids_dir, fmriprep_dir)
    if not checks:
        checks += check_validator(bids_dir, validator)
        from lib.core import discover_tasks  # lazy: keeps module import light
        tasks = list(tasks) or discover_tasks(Path(bids_dir))
        if not tasks:
            checks.append(_item("no_tasks", ERROR, "no task found in the BIDS dataset",
                                "check the BIDS folder or set the task in the project settings"))
        checks += check_model(model_file) + check_container(container_type)
        selected, found = check_subjects(bids_dir, fmriprep_dir, subjects)
        checks += found
        present = set(_subjects_in(bids_dir)) & set(_subjects_in(fmriprep_dir))
        needs = _model_needs(model_file)
        conditions, _, transformed = needs
        for task in tasks:
            seen_by_sub = {}
            for sub in selected:
                if sub in present:
                    items, seen = check_subject_task(bids_dir, fmriprep_dir, sub, task, space, needs)
                    checks += items
                    if _func_files(bids_dir, sub, f"*task-{task}_*events.tsv"):
                        seen_by_sub[sub] = seen
            if conditions and not transformed:
                union = set().union(*seen_by_sub.values()) if seen_by_sub else set()
                for c in sorted(conditions - union):
                    checks.append(_item("condition_missing", ERROR,
                                        f"condition '{c}' is in the model but in none of the task-{task} events files",
                                        "Fix the condition name in the model, or the trial_type values in the events."))
                for sub, seen in seen_by_sub.items():
                    absent = sorted((conditions & union) - seen)
                    if absent:
                        checks.append(_item("condition_missing", WARN, f"sub-{sub} has no events for: {', '.join(absent)}",
                                            "Expected if the subject never produced that condition; bidspm will warn and skip it.", sub))
    return {"verdict": _verdict(checks), "checks": checks}
