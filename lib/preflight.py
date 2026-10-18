"""Preflight readiness check: can this BIDS + fMRIPrep + model combination run?

Pure functions, no Flask. Every check returns a list of items
{"id", "severity": "error"|"warn", "subject", "message", "fix"}; run_preflight() returns {"verdict", "checks"}.
"""
import concurrent.futures
import copy
import csv
import fnmatch
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
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


def _func_listing(root, sub):
    """Every file under sub-<sub> whose parent folder is named func: one directory walk."""
    return [Path(d) / f for d, _, files in os.walk(Path(root) / f"sub-{sub}") if Path(d).name == "func" for f in files]


def _match(listing, pattern):
    return sorted(p for p in listing if fnmatch.fnmatchcase(p.name, pattern))


def _read_header(path):
    """Column names only: confounds files are huge and only their header is checked."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return next(csv.reader(fh, delimiter="\t"), [])


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
    early = []
    for n, row in enumerate(rows, start=2):
        try:
            onset, duration = float(row["onset"]), float(row["duration"])
            ok = duration >= 0
        except (TypeError, ValueError):
            ok = False
        if not ok:
            return [_item("events_values", ERROR,
                          f"{name} line {n}: onset must be a number and duration a non-negative number (got {row['onset']!r}, {row['duration']!r})",
                          "Fix or remove that row (n/a is not allowed in onset or duration).", sub)]
        if onset < 0 and not early:
            early = [_item("events_values", WARN, f"{name} line {n}: negative onset ({onset:g})",
                           "BIDS allows this, but check that the events are aligned to the scan.", sub)]
    return early


def _model_needs(model_file):
    """(trial_type conditions, nuisance regressor names, uses Transformations, names the Transformations produce)."""
    conditions, nuisance, transformed, produced = set(), [], False, set()
    try:  # malformed models: return empty needs, never partial state (check_model reports them)
        model = json.loads(Path(model_file).read_text()) if model_file else {}
        for node in model.get("Nodes") or []:
            if node.get("Level") != "Run":
                continue
            instructions = (node.get("Transformations") or {}).get("Instructions")
            if instructions:  # bidspm drops Transformations without Instructions
                transformed = True
                for ins in instructions:
                    out = ins.get("Output")
                    produced |= {str(o) for o in (out if isinstance(out, list) else [out]) if o is not None}
            xs = (node.get("Model") or {}).get("X")
            for x in xs if isinstance(xs, list) else []:  # a bare string would iterate as characters
                if not isinstance(x, str) or x in ("0", "1"):
                    continue
                if x.startswith("trial_type."):
                    conditions.add(x.split(".", 1)[1])
                elif "." not in x:
                    nuisance.append(x)
    except (OSError, ValueError, AttributeError, TypeError):
        return set(), [], False, set()
    return conditions, nuisance, transformed, produced


def _model_tasks(model_file):
    """The model's Input.task as a list of strings; [] when absent or malformed."""
    try:
        task = (json.loads(Path(model_file).read_text()).get("Input") or {}).get("task")
    except (OSError, ValueError, AttributeError, TypeError):
        return []
    return [task] if isinstance(task, str) and task else [t for t in task if isinstance(t, str) and t] if isinstance(task, list) else []


VALIDATOR_MODES = ("auto", "prism", "bids", "skip")  # "off" is internal (wizard) and only the readiness routes accept it


def validator_error(value, internal=False):
    """Error text for a validator value from a request, else None (empty means auto)."""
    allowed = VALIDATOR_MODES + (("off",) if internal else ())
    if not value or (isinstance(value, str) and value in allowed):
        return None
    return f"validator must be one of: {', '.join(allowed)}"


def resolve_tasks(tasks, model_file, bids_dir):
    """The tasks to check/run: explicit TASKS, else the model's Input.task, else every task of the BIDS folder."""
    from lib.core import discover_tasks  # lazy: keeps module import light
    return list(tasks or []) or (_model_tasks(model_file) if model_file else []) or discover_tasks(Path(bids_dir))


def _scan_length_warning(sub, preproc, events_rows):
    import nibabel as nib
    sidecar = preproc.with_name(preproc.name.replace(".nii.gz", ".json"))
    try:
        tr = json.loads(sidecar.read_text())["RepetitionTime"]
        scan = nib.load(preproc).shape[3] * tr
        end = max(float(r["onset"]) + float(r["duration"]) for r in events_rows)
    except Exception:  # advisory only: corrupt images, null TR, odd events must never block or crash
        return []
    if end > scan + tr:
        return [_item("scan_length", WARN, f"sub-{sub}: events run to {end:.0f}s but the scan is only {scan:.0f}s long",
                      "Check that the events file belongs to this run.", sub)]
    return []


def _events_files(bids_dir, bids_listing, task):
    """The subject's events files, else the dataset-level task-<task>_events.tsv (BIDS inheritance)."""
    return _match(bids_listing, f"*task-{task}_*events.tsv") or sorted(Path(bids_dir).glob(f"task-{task}_events.tsv"))


def check_subject_task(bids_dir, fmriprep_dir, sub, task, space, needs, full=True, listings=None):
    """Returns (items, trial_type values seen in this subject's events files, events files).

    listings: optional (bids, fmriprep) _func_listing results, so callers walk each subject tree once."""
    bids_listing, fmriprep_listing = listings or (_func_listing(bids_dir, sub), _func_listing(fmriprep_dir, sub))
    conditions, nuisance, transformed, produced = needs
    out, seen, event_cols = [], set(), set()
    preproc = _match(fmriprep_listing, f"*task-{task}_*space-{space or '*'}_*desc-preproc_bold.nii.gz")
    if not preproc:
        out.append(_item("preproc_missing", ERROR,
                         f"sub-{sub} has no preprocessed BOLD for task-{task} in space {space or '(any)'}",
                         f"Re-run fMRIPrep with --output-spaces {space or '<space>'}, or change the Space setting.", sub))
    if not full:
        return out, seen, []
    events = _events_files(bids_dir, bids_listing, task)
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
        event_cols |= set(cols)
        problems = _events_problems(sub, path.name, cols, rows)
        out += problems
        events_ok = events_ok and all(p["severity"] != ERROR for p in problems)
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
    nuisance = [n for n in nuisance if n not in event_cols and n not in produced]
    if nuisance:
        files = _match(fmriprep_listing, f"*task-{task}_*desc-confounds_timeseries.tsv")
        if not files:
            out.append(_item("confounds_missing", ERROR,
                             f"sub-{sub} has no confounds file for task-{task}",
                             f"Re-run fMRIPrep; confounds are needed for {', '.join(nuisance)}.", sub))
        for f in files:
            try:
                cols = _read_header(f)
            except (OSError, UnicodeDecodeError, csv.Error) as e:
                out.append(_item("confound_columns", ERROR, f"{f.name} header cannot be read as UTF-8 text ({e})",
                                 "Re-run fMRIPrep to regenerate the confounds file.", sub))
                continue
            missing = [n for n in nuisance if not any(fnmatch.fnmatch(c, n) for c in cols)]
            if missing:
                out.append(_item("confound_columns", WARN if transformed else ERROR,
                                 f"{f.name} lacks the model's regressors: {', '.join(missing)}",
                                 "Fix the regressor names in the model, or re-run fMRIPrep so they are produced.", sub))
    return out, seen, events


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


MAX_VALIDATOR_ERRORS = 20  # groups, not raw errors


def _first_json_object(text):
    """First decodable JSON object in text (banner before, chatter after are fine), else None."""
    decoder, pos = json.JSONDecoder(), text.find("{")
    while pos != -1:
        try:
            return decoder.raw_decode(text, pos)[0]
        except ValueError:
            pos = text.find("{", pos + 1)
    return None


def _run_killable(cmd, cancelled, timeout=1800):
    """subprocess.run(capture_output, text) that polls `cancelled` and then kills the whole process group (deno children
    included); returns None when cancelled. Raises subprocess.TimeoutExpired after `timeout` seconds."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    deadline = time.monotonic() + timeout

    def kill(sig):
        try:
            os.killpg(proc.pid, sig)
        except OSError:
            pass
    while True:
        try:
            out, err = proc.communicate(timeout=0.2)
            return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
        except subprocess.TimeoutExpired:
            expired = time.monotonic() > deadline
            if not expired and not (cancelled and cancelled()):
                continue
        kill(signal.SIGTERM)
        try:
            proc.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            kill(signal.SIGKILL)
            proc.communicate()
        if expired:
            raise subprocess.TimeoutExpired(cmd, timeout)
        return None


def check_validator(bids_dir, mode="auto", run=None, cancelled=None):
    """Run prism-validator --json (BIDS validator + PRISM checks); never --fix, never --plugins.

    cancelled(): polled while it runs; on cancel the process group is killed and [] is returned.
    The injectable `run` (tests) replaces the process handling and is not cancellable."""
    if mode == "off":  # internal (wizard): the dataset is not what is being checked, so no item at all
        return []
    if mode == "skip":
        return [_item("validator", WARN, "Dataset validator skipped.", "Choose 'auto', 'PRISM' or 'plain BIDS' to validate the dataset.")]
    if mode not in ("auto", "prism", "bids"):
        return [_item("validator", ERROR, f"unknown validator mode: {mode!r}", "Choose 'auto', 'PRISM', 'plain BIDS' or 'skip'.")]
    detected = ""
    if mode == "auto":  # a PRISM dataset has project.json at its root
        found = (Path(bids_dir) / "project.json").is_file()
        mode = "prism" if found else "bids"
        detected = (f" Validator mode was auto-detected as {'PRISM' if found else 'plain BIDS'} "
                    f"(project.json {'found' if found else 'not found'}).")
    exe = Path(sys.executable).parent / "prism-validator"
    exe = str(exe) if exe.is_file() else shutil.which("prism-validator")
    if not exe:
        return [_item("validator", WARN, "prism-validator is not installed; the dataset was not validated.", "Run: uv sync")]
    cmd = [exe, str(Path(bids_dir).resolve()), "--json"] + (["--no-prism"] if mode == "bids" else [])
    hand = "Run prism-validator by hand to see why"
    try:
        # ponytail: no result cache; add one if validation proves slow
        proc = run(cmd, capture_output=True, text=True, timeout=1800) if run else _run_killable(cmd, cancelled)
        if proc is None:  # cancelled and killed
            return []
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [_item("validator", WARN, f"The dataset validator could not run ({exc}).", hand + ".")]
    report = _first_json_object(proc.stdout)
    if not isinstance(report, dict):
        if proc.returncode:
            return [_item("validator", ERROR, f"the dataset validator crashed and produced no report (exit {proc.returncode})",
                          hand + ", or choose 'skip' to continue without dataset validation.")]
        return [_item("validator", WARN, "The dataset validator produced no report.", hand + ".")]
    issues = [i for i in report.get("issues") if isinstance(i, dict)] if isinstance(report.get("issues"), list) else []
    errors = [i for i in issues if i.get("severity") == "ERROR"]
    groups = {}
    for i in errors:
        first = (str(i.get("message") or "").splitlines() or [""])[0]
        groups.setdefault((str(i.get("code", "?")), first), []).append(i)
    plain = " If this is not a PRISM dataset, choose 'plain BIDS' in the validator select (CLI: --validator bids);" if mode == "prism" else ""
    fix = f"Fix the dataset.{plain} To ignore unrelated problems choose 'skip'.{detected}"
    out = []
    for (code, first), items in list(groups.items())[:MAX_VALIDATOR_ERRORS]:
        count = f" x{len(items)}" if len(items) > 1 else ""
        eg = "e.g. " if len(items) > 1 else ""
        out.append(_item("validator", ERROR, f"{code}{count}: {first} ({eg}{items[0].get('file_path', '')})", fix))
    if len(groups) > MAX_VALIDATOR_ERRORS:
        out.append(_item("validator", ERROR, f"+{len(groups) - MAX_VALIDATOR_ERRORS} more validator error groups", hand + " for the full list."))
    if report.get("valid") is False and not errors:
        out.append(_item("validator", ERROR, "the validator reports the dataset invalid but listed no errors", hand + "."))
    warns = [i for i in issues if i.get("severity") == "WARNING"]
    if warns:
        out.append(_item("validator", WARN, f"{len(warns)} validator warning(s): " + ", ".join(sorted({str(w.get('code', '?')) for w in warns}))))
    return out


class _Progress:
    """Progress/cancel callbacks for a run. Callback exceptions are swallowed: they must never break the check.

    Items passed to add() ride on the next event, so every item is reported exactly once."""

    def __init__(self, progress=None, cancelled=None):
        for name, fn in (("progress", progress), ("cancelled", cancelled)):
            if fn is not None and not callable(fn):
                raise TypeError(f"{name} must be callable or None, got {type(fn).__name__}")
        self._progress, self._cancelled = progress, cancelled
        self.start, self.pending, self.is_cancelled = time.monotonic(), [], False
        self.future, self.validator_items = None, None  # set by run_preflight when a validator thread runs

    def add(self, items):
        self.pending += items

    def emit(self, phase, state="progress", message="", index=None, total=None, subject=None, **extra):
        event = {"phase": phase, "state": state, "message": message, "index": index, "total": total,
                 "subject": subject, "elapsed": time.monotonic() - self.start, "items": self.pending, **extra}
        self.pending = []
        if self._progress:
            try:
                self._progress(event)
            except Exception:
                pass

    def stop(self):
        if not self.is_cancelled and self._cancelled:
            try:
                self.is_cancelled = bool(self._cancelled())
            except Exception:
                pass
        return self.is_cancelled

    def poll_validator(self, wait=False):
        """Emit the validator's items once, as soon as it has finished (or after waiting for it)."""
        if self.future and self.validator_items is None and (wait or self.future.done()):
            self.validator_items = self.future.result()
            self.add(self.validator_items)
            self.emit("validator", "done", "dataset validator finished")


def _subject_checks(bids_dir, fmriprep_dir, model_file, tasks, space, subjects, container_type, skip_model_validation, full, prog):
    checks = []
    tasks = resolve_tasks(tasks, model_file, bids_dir)
    if not tasks:
        checks.append(_item("no_tasks", ERROR, "no task found in the BIDS dataset",
                            "check the BIDS folder or set the task in the project settings"))
        prog.add(checks)  # no_tasks rides on the next event (model or subjects start)
    if full and not skip_model_validation and not prog.stop():
        prog.emit("model", "start", "checking the model")
        found = check_model(model_file)
        checks += found
        prog.add(found)
        prog.emit("model", "done", "model checked")
    found = check_container(container_type)
    selected, missing = check_subjects(bids_dir, fmriprep_dir, subjects)
    checks += found + missing
    prog.add(found + missing)  # these ride on the subjects start event
    present = set(_subjects_in(bids_dir)) & set(_subjects_in(fmriprep_dir))
    total = len(tasks) * sum(1 for sub in selected if sub in present)  # only subjects that are really checked
    prog.emit("subjects", "start", f"checking {total} subject/task pairs", index=0, total=total)
    needs = _model_needs(model_file)
    conditions, _, transformed, _ = needs
    listings = {}  # one directory walk per subject and root, shared by all tasks
    # ponytail: all subjects' func listings are held for the run; fine up to a few thousand subjects
    index = 0
    for task in tasks:
        seen_by_sub = {}
        for sub in selected:
            if sub in present:
                if prog.stop():
                    return checks
                if sub not in listings:
                    listings[sub] = (_func_listing(bids_dir, sub), _func_listing(fmriprep_dir, sub))
                items, seen, events = check_subject_task(bids_dir, fmriprep_dir, sub, task, space, needs, full, listings[sub])
                checks += items
                prog.add(items)
                index += 1
                prog.emit("subjects", "progress", f"sub-{sub} task-{task}", index=index, total=total, subject=sub)
                prog.poll_validator()
                if full and events:
                    seen_by_sub[sub] = seen
        before = len(checks)
        if full and conditions and not transformed:
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
        prog.add(checks[before:])
    prog.emit("subjects", "done", "subject checks finished")  # the bar leaves 100 % while a slow validator is still running
    return checks


def _run_preflight(bids_dir, fmriprep_dir, model_file, tasks, space, subjects, validator, container_type,
                   skip_model_validation, actions, prog):
    full = not actions or any(str(a).lower() in ("stats", "dataset") for a in actions)
    prog.emit("folders", "start", "checking the folders")
    checks = check_dirs(bids_dir, fmriprep_dir)
    prog.add(checks)
    prog.emit("folders", "done", "folders checked")
    if checks:
        return {"verdict": _verdict(checks), "checks": checks}
    if prog.stop():
        return {"verdict": "cancelled", "checks": []}
    if validator in ("skip", "off"):  # nothing slow to overlap: no thread
        pool, front = None, check_validator(bids_dir, validator)
        prog.add(front)
    else:  # blocking subprocess: overlap it with the per-subject checks
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        prog.future = pool.submit(check_validator, bids_dir, validator, cancelled=prog.stop)
        prog.emit("validator", "start", "running the dataset validator")
    try:
        checks += _subject_checks(bids_dir, fmriprep_dir, model_file, tasks, space, subjects,
                                  container_type, skip_model_validation, full, prog)
        while pool and not prog.future.done() and not prog.stop():  # cancel stays responsive while waiting
            concurrent.futures.wait([prog.future], timeout=0.2)
    finally:
        if pool:  # on cancel do not wait: the validator thread kills its process group and exits within ~1 s
            pool.shutdown(wait=not prog.is_cancelled, cancel_futures=prog.is_cancelled)
    if prog.is_cancelled:
        prog.poll_validator()  # only if it already finished
        return {"verdict": "cancelled", "checks": (prog.validator_items or []) + checks}
    prog.poll_validator(wait=True)
    checks[:0] = prog.validator_items if pool else front  # validator items stay first
    return {"verdict": _verdict(checks), "checks": checks}


def run_preflight(bids_dir, fmriprep_dir, model_file="", tasks=(), space="", subjects=(),
                  validator="auto", container_type="", skip_model_validation=False, actions=None,
                  progress=None, cancelled=None):
    """actions=None checks everything; without 'stats'/'dataset' only folders, subjects, preproc and validator are checked.

    progress(event) gets {"phase", "state", "message", "index", "total", "subject", "elapsed", "items"} per step and a
    final {"phase": "done", "verdict"}; cancelled() is polled between subjects. Both must be callables (TypeError
    otherwise); exceptions they raise are swallowed. A cancelled run returns {"verdict": "cancelled", "checks": [found so far]}."""
    prog = _Progress(progress, cancelled)
    report = _run_preflight(bids_dir, fmriprep_dir, model_file, tasks, space, subjects, validator, container_type,
                            skip_model_validation, actions, prog)
    prog.emit("done", "done", report["verdict"], verdict=report["verdict"])
    return report


def _as_list(value):
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    return [] if value is None or isinstance(value, dict) else [str(value)]


def _path(value):
    """A path setting as typed in a form: surrounding blanks stripped, `~` expanded (once, here, for every entry point)."""
    return os.path.expanduser(value.strip()) if isinstance(value, str) else value


def run_preflight_from_config(cfg, model="", validator="auto", skip_model_validation=False, actions=None,
                              progress=None, cancelled=None):
    return run_preflight(
        bids_dir=_path(cfg.get("BIDS_DIR", "")), fmriprep_dir=_path(cfg.get("FMRIPREP_DIR", "")),
        model_file=_path(model or cfg.get("MODELS_FILE", "")), tasks=_as_list(cfg.get("TASKS")),
        space=cfg.get("SPACE", ""), subjects=_as_list(cfg.get("SUBJECTS")),
        validator=validator, container_type=cfg.get("container_type", ""),
        skip_model_validation=skip_model_validation, actions=actions,
        progress=progress, cancelled=cancelled)


# --- recent passing results, reused by the /run gate ---
RECENT_TTL, RECENT_MAX = 600, 20
_RECENT = {}  # signature -> (monotonic timestamp, report); insertion order = age
_RECENT_LOCK = threading.Lock()


def signature(cfg, model, validator, actions, skip_model_validation):
    """Hash of exactly what run_preflight_from_config reads, normalised; the model by file content, not path."""
    path = _path(model or cfg.get("MODELS_FILE") or "")
    try:
        raw = Path(path).read_bytes()
    except (OSError, TypeError, ValueError):
        raw = None  # sentinel: missing/unreadable model file
    try:  # canonical JSON: key order/whitespace differ between the browser's model_json and the saved file
        raw = json.dumps(json.loads(raw), sort_keys=True).encode()
    except (TypeError, ValueError):
        pass
    content = None if raw is None else hashlib.sha256(raw).hexdigest()
    payload = [
        str(_path(cfg.get("BIDS_DIR") or "")), str(_path(cfg.get("FMRIPREP_DIR") or "")), content,
        _as_list(cfg.get("TASKS")), str(cfg.get("SPACE") or ""),
        sorted(s[4:] if s.startswith("sub-") else s for s in _as_list(cfg.get("SUBJECTS"))),
        str(cfg.get("container_type") or ""), validator, sorted(str(a) for a in actions or []),
        bool(skip_model_validation),
    ]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def remember(sig, report):
    # ponytail: dataset edits made within the TTL (10 min) are not noticed; fine for a local single-user tool
    if report.get("verdict") not in ("ready", "warnings"):
        return
    with _RECENT_LOCK:
        _RECENT.pop(sig, None)
        _RECENT[sig] = (time.monotonic(), copy.deepcopy(report))
        while len(_RECENT) > RECENT_MAX:
            del _RECENT[next(iter(_RECENT))]


def recent(sig, ttl=RECENT_TTL):
    # ponytail: dataset edits made within the TTL (10 min) are not noticed; fine for a local single-user tool
    with _RECENT_LOCK:
        entry = _RECENT.get(sig)
        if entry is None:
            return None
        if time.monotonic() - entry[0] > ttl:
            del _RECENT[sig]
            return None
        return copy.deepcopy(entry[1])
