# Preflight Readiness Check + Version 2.0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before a run, tell the scientist in plain language whether BIDS + fMRIPrep + model can succeed; errors block Run. Also give the repo a single visible version, 2.0.1.

**Architecture:** `lib/preflight.py` holds pure check functions and `run_preflight_from_config(cfg, model, validator)`; `bidspm.py --preflight` prints the JSON report; a thin Flask route `/api/preflight` serves the GUI panel; `/run` calls the same function and refuses to start when the verdict is `blocked`. The dataset validator is `prism-validator --json` run as a subprocess.

**Tech Stack:** Python 3.12 (uv), Flask, pytest, nibabel (already a dependency, header reads only), `prism-validator` 1.20.0 (new dependency, ships `bids-validator-deno`), vanilla JS + Playwright browser test.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-16-preflight-design.md` (amended in Task 1).
- TDD always: failing test first, see it fail, then the code (CLAUDE.md).
- Pipeline logic belongs in `lib/`/CLI, not in `webapp/` (CLAUDE.md). The route is a thin wrapper.
- Version single source: `pyproject.toml` `version = "2.0.1"`. No git tag is created.
- Errors block Run with no override. The only escape is the validator mode `skip` (CLI `--skip-validator`, GUI select), which skips ONLY the dataset-validator check and shows as a `warn`.
- Never run `prism-validator` with `--fix` or `--plugins`.
- Check item shape: `{"id", "severity": "error"|"warn", "subject": str|None, "message", "fix"}`; report: `{"verdict": "blocked"|"warnings"|"ready", "checks": [...]}`.
- Tests: `python -m pytest -q tests` (use `.bidspm/bin/python -m pytest` if the venv python is not on PATH). Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Before merging to main: `/ponytail:ponytail-review` on the branch diff (Task 10).

## File Structure

- Create `lib/preflight.py` — all checks + `run_preflight`, `run_preflight_from_config`.
- Create `tests/preflight_support.py` — synthetic BIDS/fMRIPrep tree builder (not a test module).
- Create `tests/test_preflight.py` — unit tests for every check.
- Create `tests/test_preflight_cli.py`, `tests/test_preflight_route.py`, `tests/test_preflight_browser.py`, `tests/test_version.py`.
- Create `webapp/web_preflight_api.py` — `register_preflight_routes(app)`.
- Create `static/js/analysis_preflight.js` — panel rendering + validator select.
- Modify `pyproject.toml`, `uv.lock`, `bidspm_gui.py`, `templates/base.html`, `templates/analysis.html`, `bidspm.py`, `webapp/web_execution_api.py`, `static/js/analysis_run.js`, `README.md`, the spec.

---

### Task 1: Spec amendments + version 2.0.1

**Files:**
- Modify: `docs/superpowers/specs/2026-10-16-preflight-design.md`, `pyproject.toml`, `bidspm_gui.py:72-74`, `templates/base.html` (footer)
- Create: `tests/test_version.py`

**Interfaces:**
- Produces: `bidspm_gui.__version__ == "2.0.1"`, `app.config['APP_VERSION']`, footer text `v2.0.1`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_version.py
import tomllib
from pathlib import Path

import bidspm_gui

ROOT = Path(__file__).resolve().parent.parent


def test_version_is_single_sourced_from_pyproject():
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert declared == "2.0.1"
    assert bidspm_gui.__version__ == declared
    assert bidspm_gui.app.config["APP_VERSION"] == declared


def test_footer_shows_the_version():
    html = bidspm_gui.app.test_client().get("/projects").get_data(as_text=True)
    assert "v2.0.1" in html
```

- [ ] **Step 2: Run, verify it fails** — `python -m pytest -q tests/test_version.py` → FAIL (`2.0.0 != 2.0.1`).

- [ ] **Step 3: Implement**

`pyproject.toml`: `version = "2.0.1"`. In `bidspm_gui.py` replace the hardcoded version (lines 72-74) with:

```python
# Version info: single source is pyproject.toml
import tomllib
__version__ = tomllib.loads((Path(__file__).parent / "pyproject.toml").read_text())["project"]["version"]
app.config['APP_VERSION'] = __version__
```
(add `from pathlib import Path` only if not already imported). In `templates/base.html`, change `<p class="text-muted mb-0 small">University of Graz</p>` neighbour line: add after `<p class="text-muted mb-0 small">Built with ❤️ for the community</p>`:

```html
                    <p class="text-muted mb-0 small">BIDSPM Runner v{{ config.APP_VERSION }}</p>
```
Spec amendments (edit the spec file): in "Dataset validator" replace the PRISM-marker sentence with "Mode is a user choice, default `prism`: GUI select (PRISM / plain BIDS / skip), CLI `--validator {prism,bids,skip}` + alias `--skip-validator`; remembered per project in localStorage. No marker detection." Replace "Result cached…" with "No result cache in v1 (add if validation proves slow)." In check 6 write "error if a condition is absent from every events file of the task; warn per subject if absent only for some." Add "Check 7 runs only when the model lists nuisance regressors." Add "Check 5 scan-length compares only when a subject/task has exactly one events file and one preproc file." Add under Architecture: "`/run` gates only smooth/stats/dataset; the CLI run path is not gated (only `--preflight` reports)." Remove the "Open: exact PRISM marker" line.

- [ ] **Step 4: Run** — `python -m pytest -q tests/test_version.py tests/test_web_routes.py` → PASS.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: version 2.0.1 from pyproject, shown in footer; spec amendments"` (+ trailer).

---

### Task 2: Fixtures + folder and subject checks

**Files:**
- Create: `tests/preflight_support.py`, `tests/test_preflight.py`, `lib/preflight.py`

**Interfaces:**
- Produces: `make_trees(tmp, subjects=("01",), task="x", space="MNI", events=EVENTS, confounds=CONFOUNDS, tr=2.0, nvols=100) -> (bids, fmriprep)`; `write_model(tmp, x=(...), transformations=False) -> Path`; `_item(id, severity, message, fix="", subject=None)`; `check_dirs(bids_dir, fmriprep_dir) -> list`; `check_subjects(bids_dir, fmriprep_dir, subjects) -> (selected, list)`; `run_preflight(bids_dir, fmriprep_dir, model_file="", tasks=(), space="", subjects=(), validator="prism", container_type="") -> {"verdict","checks"}`; `_verdict(checks) -> str`.

- [ ] **Step 1: Write the fixtures and failing tests**

```python
# tests/preflight_support.py
"""Synthetic BIDS + fMRIPrep trees for the preflight tests (not a test module)."""
import json
from pathlib import Path

import nibabel as nib
import numpy as np

EVENTS = "onset\tduration\ttrial_type\n1\t1\ta\n5\t1\tb\n"
CONFOUNDS = "trans_x\ttrans_y\ttrans_z\nn/a\t0\t0\n"


def make_trees(tmp, subjects=("01",), task="x", space="MNI", events=EVENTS, confounds=CONFOUNDS, tr=2.0, nvols=100):
    bids, fmriprep = Path(tmp) / "bids", Path(tmp) / "fmriprep"
    for root in (bids, fmriprep):
        root.mkdir(parents=True, exist_ok=True)
        (root / "dataset_description.json").write_text(json.dumps({"Name": "t", "BIDSVersion": "1.9.0"}))
    for s in subjects:
        b, f = bids / f"sub-{s}" / "func", fmriprep / f"sub-{s}" / "func"
        b.mkdir(parents=True)
        f.mkdir(parents=True)
        (b / f"sub-{s}_task-{task}_events.tsv").write_text(events)
        stem = f"sub-{s}_task-{task}_space-{space}_desc"
        nib.save(nib.Nifti1Image(np.zeros((2, 2, 2, nvols), "f4"), np.eye(4)), f / f"{stem}-preproc_bold.nii.gz")
        (f / f"{stem}-preproc_bold.json").write_text(json.dumps({"RepetitionTime": tr}))
        (f / f"sub-{s}_task-{task}_desc-confounds_timeseries.tsv").write_text(confounds)
    return bids, fmriprep


def write_model(tmp, x=("trial_type.a", "trial_type.b", 1), transformations=False):
    node = {"Level": "Run", "Name": "run", "GroupBy": ["run", "subject"], "Model": {"X": list(x), "Type": "glm"}}
    if transformations:
        node["Transformations"] = {"Transformer": "bidspm", "Instructions": [
            {"Name": "Filter", "Input": ["trial_type"], "Query": "trial_type=='a'"}]}
    path = Path(tmp) / "model.json"
    path.write_text(json.dumps({"Name": "m", "BIDSModelVersion": "1.0.0", "Input": {"task": ["x"]}, "Nodes": [node]}))
    return path
```

```python
# tests/test_preflight.py
from lib.preflight import run_preflight, _verdict
from tests.preflight_support import make_trees


def ids(result, severity):
    return {c["id"] for c in result["checks"] if c["severity"] == severity}


def run(tmp_path, **kw):
    bids, fmriprep = make_trees(tmp_path)
    args = dict(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    args.update(kw)
    return run_preflight(**args)


def test_healthy_trees_have_no_errors(tmp_path):
    result = run(tmp_path)
    assert ids(result, "error") == set()
    assert result["verdict"] == "warnings"  # the skipped validator is a warn


def test_verdict_levels():
    assert _verdict([]) == "ready"
    assert _verdict([{"severity": "warn"}]) == "warnings"
    assert _verdict([{"severity": "warn"}, {"severity": "error"}]) == "blocked"


def test_missing_folders_block_and_stop_early(tmp_path):
    result = run_preflight(bids_dir=tmp_path / "nope", fmriprep_dir=tmp_path / "nada", validator="skip")
    assert ids(result, "error") == {"bids_dir", "fmriprep_dir"}
    assert result["verdict"] == "blocked"


def test_folder_without_dataset_description_blocks(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    (fmriprep / "dataset_description.json").unlink()
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, validator="skip")
    assert "fmriprep_dir" in ids(result, "error")


def test_selected_subject_missing_from_fmriprep_blocks(tmp_path):
    result = run(tmp_path, subjects=["01", "99"])
    errors = [c for c in result["checks"] if c["id"] == "subject_missing"]
    assert {c["subject"] for c in errors} == {"99"}
    assert len(errors) == 2  # absent from both BIDS and fMRIPrep


def test_subject_labels_may_carry_the_sub_prefix(tmp_path):
    assert "subject_missing" not in ids(run(tmp_path, subjects=["sub-01"]), "error")
```

- [ ] **Step 2: Run, verify fail** — `python -m pytest -q tests/test_preflight.py` → FAIL (`ModuleNotFoundError: lib.preflight`).

- [ ] **Step 3: Implement `lib/preflight.py`**

```python
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
```
The `validator` check is not wired in yet, so `test_healthy_trees_have_no_errors` expects a `warnings` verdict only from Task 6; for now relax that single assertion to `assert result["verdict"] in ("ready", "warnings")` and restore the strict `== "warnings"` in Task 6 Step 3.

- [ ] **Step 4: Run** — `python -m pytest -q tests/test_preflight.py` → PASS.
- [ ] **Step 5: Commit** — `feat(preflight): folder and subject checks`.

---

### Task 3: Per-subject files and events checks

**Files:** Modify `lib/preflight.py`, `tests/test_preflight.py`.

**Interfaces:**
- Consumes: Task 2 helpers.
- Produces: `_func_files(root, sub, pattern) -> list[Path]`; `_read_tsv(path) -> (columns, rows)`; `check_subject_task(bids_dir, fmriprep_dir, sub, task, space) -> list` (this task: preproc + events existence, columns, values). Task 4 extends the signature (see there).

- [ ] **Step 1: Failing tests** (append)

```python
import pytest


def _only(result, id):
    return [c for c in result["checks"] if c["id"] == id]


def test_missing_preproc_blocks_with_a_fix_hint(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    next(fmriprep.rglob("*desc-preproc_bold.nii.gz")).unlink()
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    (item,) = _only(result, "preproc_missing")
    assert item["subject"] == "01" and "MNI" in item["message"] and item["fix"]


def test_wrong_space_counts_as_missing_preproc(tmp_path):
    assert "preproc_missing" in ids(run(tmp_path, space="T1w"), "error")


def test_missing_events_block(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    next(bids.rglob("*_events.tsv")).unlink()
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    assert "events_missing" in ids(result, "error")


@pytest.mark.parametrize("events,expected", [
    ("onset\ttrial_type\n1\ta\n", "events_columns"),                          # no duration column
    ("onset\tduration\ttrial_type\nsoon\t1\ta\n", "events_values"),           # non-numeric onset
    ("onset\tduration\ttrial_type\n1\t-2\ta\n", "events_values"),             # negative duration
])
def test_bad_events_block(tmp_path, events, expected):
    bids, fmriprep = make_trees(tmp_path, events=events)
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    assert expected in ids(result, "error")


def test_tasks_default_to_those_found_in_bids(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    next(fmriprep.rglob("*desc-preproc_bold.nii.gz")).unlink()
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, space="MNI", validator="skip")
    assert "preproc_missing" in ids(result, "error")
```

- [ ] **Step 2: Run, verify fail** (the new tests FAIL; no checks yet).
- [ ] **Step 3: Implement** — add to `lib/preflight.py`:

```python
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
```
and extend `run_preflight` (after the subjects check, only when no errors so far from `check_dirs`):

```python
from lib.core import discover_tasks  # at top of run_preflight's body to avoid import cost at module load
...
        tasks = list(tasks) or discover_tasks(Path(bids_dir))
        selected, found = check_subjects(bids_dir, fmriprep_dir, subjects)
        checks += found
        for task in tasks:
            for sub in selected:
                checks += check_subject_task(bids_dir, fmriprep_dir, sub, task, space)
```
(Subjects missing from a tree produce `subject_missing`; skip them in the loop: iterate `[s for s in selected if s in set(_subjects_in(bids_dir)) & set(_subjects_in(fmriprep_dir))]`.)

- [ ] **Step 4: Run** — `python -m pytest -q tests/test_preflight.py` → PASS.
- [ ] **Step 5: Commit** — `feat(preflight): per-subject preproc and events checks`.

---

### Task 4: Model-aware checks (conditions, trial_type, confounds, scan length)

**Files:** Modify `lib/preflight.py`, `tests/test_preflight.py`.

**Interfaces:**
- Produces: `_model_needs(model_file) -> (conditions: set[str], nuisance: list[str], transformed: bool)`. `check_subject_task(...)` gains keyword-only `needs=(set(), [], False)` and now returns `(items, seen_conditions: set[str])`. `run_preflight` aggregates `condition_missing`.
- Update Task 3's call sites accordingly.

- [ ] **Step 1: Failing tests** (append; `from tests.preflight_support import write_model`)

```python
from tests.preflight_support import write_model


def test_condition_absent_everywhere_blocks(tmp_path):
    model = write_model(tmp_path, x=("trial_type.a", "trial_type.zzz", 1))
    result = run(tmp_path, model_file=model)
    (item,) = _only(result, "condition_missing")
    assert item["severity"] == "error" and "zzz" in item["message"]


def test_condition_absent_for_one_subject_only_warns(tmp_path):
    bids, fmriprep = make_trees(tmp_path, subjects=("01", "02"))
    (bids / "sub-02" / "func" / "sub-02_task-x_events.tsv").write_text("onset\tduration\ttrial_type\n1\t1\ta\n")
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip",
                           model_file=write_model(tmp_path))
    (item,) = _only(result, "condition_missing")
    assert item["severity"] == "warn" and item["subject"] == "02" and "b" in item["message"]


def test_condition_check_is_skipped_when_the_model_transforms_events(tmp_path):
    model = write_model(tmp_path, x=("trial_type.zzz", 1), transformations=True)
    assert "condition_missing" not in ids(run(tmp_path, model_file=model), "error")


def test_trial_type_column_required_when_model_uses_conditions(tmp_path):
    bids, fmriprep = make_trees(tmp_path, events="onset\tduration\n1\t1\n")
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip",
                           model_file=write_model(tmp_path))
    assert "events_trial_type" in ids(result, "error")


def test_model_nuisance_regressor_must_exist_in_confounds(tmp_path):
    model = write_model(tmp_path, x=("trial_type.a", "trans_x", "framewise_displacement", 1))
    result = run(tmp_path, model_file=model)
    (item,) = _only(result, "confound_columns")
    assert "framewise_displacement" in item["message"] and "trans_x" not in item["message"]


def test_missing_confounds_file_blocks_only_when_model_needs_it(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    next(fmriprep.rglob("*confounds_timeseries.tsv")).unlink()
    base = dict(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    assert "confounds_missing" not in ids(run_preflight(**base, model_file=write_model(tmp_path)), "error")
    needs = write_model(tmp_path, x=("trial_type.a", "trans_x", 1))
    assert "confounds_missing" in ids(run_preflight(**base, model_file=needs), "error")


def test_events_beyond_the_scan_warn(tmp_path):
    bids, fmriprep = make_trees(tmp_path, tr=2.0, nvols=10, events="onset\tduration\ttrial_type\n100\t1\ta\n")
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    assert "scan_length" in ids(result, "warn")
```

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement.** Add:

```python
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
```
Change `check_subject_task(bids_dir, fmriprep_dir, sub, task, space, needs=(set(), [], False))` to return `(out, seen)`:
- after the existing events loop, inside it: `if conditions and not transformed:` if `"trial_type" not in cols` → `_item("events_trial_type", ERROR, f"{path.name} has no trial_type column but the model uses trial_type.* conditions", "Add a trial_type column or change the model's regressors.", sub)` else `seen |= {r["trial_type"] for r in rows}`.
- if exactly one preproc and one events file and no events error so far: `out += _scan_length_warning(sub, preproc[0], rows)`.
- confounds: when `nuisance`: `files = _func_files(fmriprep_dir, sub, f"*task-{task}_*desc-confounds_timeseries.tsv")`; none → `confounds_missing` error ("Re-run fMRIPrep; confounds are needed for <names>"); else for each file read header with `_read_tsv(f)[0]`, `missing = [n for n in nuisance if not any(fnmatch.fnmatch(c, n) for c in cols)]` → one `confound_columns` error naming only the missing ones.
In `run_preflight`: collect `seen_by_sub[sub]` per task; after the subject loop, with `conditions, nuisance, transformed = _model_needs(model_file)` (call once, pass `needs`):
```python
            if conditions and not transformed:
                union = set().union(*seen_by_sub.values()) if seen_by_sub else set()
                for c in sorted(conditions - union):
                    checks.append(_item("condition_missing", ERROR, f"condition '{c}' is in the model but in none of the task-{task} events files", "Fix the condition name in the model, or the trial_type values in the events.")))
                for sub, seen in seen_by_sub.items():
                    absent = sorted((conditions & union) - seen)
                    if absent:
                        checks.append(_item("condition_missing", WARN, f"sub-{sub} has no events for: {', '.join(absent)}", "Expected if the subject never produced that condition; bidspm will warn and skip it.", sub))
```
(Only count subjects that had events files; an `events_missing` subject has `seen == set()` and must be excluded from the warn loop — only add to `seen_by_sub` when events files exist.)

- [ ] **Step 4: Run** — `python -m pytest -q tests/test_preflight.py` → PASS (all of Tasks 2-4).
- [ ] **Step 5: Commit** — `feat(preflight): model-aware checks (conditions, trial_type, confounds, scan length)`.

---

### Task 5: Model validation + container check

**Files:** Modify `lib/preflight.py`, `tests/test_preflight.py`.

**Interfaces:** Produces `check_model(model_file) -> list` (wraps `lib.core.validate_bids_model`), `check_container(container_type) -> list`.

- [ ] **Step 1: Failing tests**

```python
from unittest.mock import patch


def test_invalid_model_blocks_with_the_validators_message(tmp_path):
    with patch("lib.core.validate_bids_model", return_value={"valid": False, "error": "Empty contrast issues: x"}):
        result = run(tmp_path, model_file=write_model(tmp_path))
    (item,) = _only(result, "model")
    assert item["severity"] == "error" and "Empty contrast" in item["message"]


def test_model_warning_is_a_warn_and_valid_model_adds_nothing(tmp_path):
    model = write_model(tmp_path)
    with patch("lib.core.validate_bids_model", return_value={"valid": True, "warning": "Normalized model"}):
        assert [c["severity"] for c in _only(run(tmp_path, model_file=model), "model")] == ["warn"]
    with patch("lib.core.validate_bids_model", return_value={"valid": True}):
        assert _only(run(tmp_path, model_file=model), "model") == []


def test_missing_container_runtime_warns(tmp_path):
    with patch("shutil.which", return_value=None):
        assert "container" in ids(run(tmp_path, container_type="docker"), "warn")
    assert "container" not in ids(run(tmp_path, container_type=""), "warn")
```
Note: other tests pass no `model_file`, so they do not hit the network schema fetch.

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement**

```python
def check_model(model_file):
    if not model_file:
        return []
    from lib import core
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
```
(`from lib import core` inside the function so `patch("lib.core.validate_bids_model")` takes effect.) In `run_preflight` append `check_model(model_file)` and `check_container(container_type)` to `checks` when the folder checks passed.
- [ ] **Step 4: Run** — PASS. **Step 5: Commit** — `feat(preflight): model validation and container availability`.

---

### Task 6: Dataset validator (prism-validator)

**Files:** Modify `pyproject.toml`, `uv.lock`, `lib/preflight.py`, `tests/test_preflight.py`.

**Interfaces:** Produces `check_validator(bids_dir, mode="prism", run=subprocess.run) -> list`; `run_preflight` calls it first (after folder checks) with its `validator` argument. Mode `skip` → one `warn`.

- [ ] **Step 1: Add the dependency** — `uv add prism-validator` (updates `pyproject.toml` and `uv.lock`); then `UV_PROJECT_ENVIRONMENT=.bidspm uv sync --managed-python`. Confirm `.bidspm/bin/prism-validator --version` works.

- [ ] **Step 2: Failing tests**

```python
import json
import subprocess

from lib.preflight import check_validator

REPORT = {"valid": False, "issues": [
    {"code": "PRISM301", "severity": "ERROR", "message": "schema error: 'Authors' is a required property\nmore", "file_path": "/d/dataset_description.json"},
    {"code": "BIDS_NO_AUTHORS", "severity": "WARNING", "message": "[BIDS] NO_AUTHORS", "file_path": "/d/x"},
    {"code": "BIDS_README_FILE_MISSING", "severity": "WARNING", "message": "[BIDS] README", "file_path": "/d/y"}]}


def fake_run(stdout, returncode=1, calls=None):
    def run(cmd, **kw):
        if calls is not None:
            calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")
    return run


def test_validator_errors_block_and_warnings_are_summarised(tmp_path):
    out = check_validator(tmp_path, "prism", run=fake_run("banner\n" + json.dumps(REPORT)))
    assert [(c["severity"], c["id"]) for c in out] == [("error", "validator"), ("warn", "validator")]
    assert "PRISM301" in out[0]["message"] and "more" not in out[0]["message"]
    assert "2 validator warning" in out[1]["message"]


def test_plain_bids_mode_passes_no_prism_and_never_fix_or_plugins(tmp_path):
    calls = []
    check_validator(tmp_path, "bids", run=fake_run(json.dumps({"issues": []}), 0, calls))
    cmd = calls[0]
    assert "--no-prism" in cmd and "--json" in cmd
    assert not {"--fix", "--plugins"} & set(cmd)


def test_skip_mode_warns_and_does_not_run(tmp_path):
    calls = []
    out = check_validator(tmp_path, "skip", run=fake_run("", 0, calls))
    assert [c["severity"] for c in out] == ["warn"] and calls == []


def test_unparseable_validator_output_degrades_to_a_warning(tmp_path):
    out = check_validator(tmp_path, "prism", run=fake_run("Traceback ..."))
    assert [c["severity"] for c in out] == ["warn"]


def test_validator_error_blocks_the_whole_preflight(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    with patch("lib.preflight.subprocess.run", fake_run(json.dumps(REPORT))):
        result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="prism")
    assert result["verdict"] == "blocked" and "validator" in ids(result, "error")
```
Also add one integration test that actually runs the tool (skips if absent):

```python
import shutil, sys
from pathlib import Path


@pytest.mark.skipif(not (Path(sys.executable).parent / "prism-validator").exists() and not shutil.which("prism-validator"),
                    reason="prism-validator not installed")
def test_real_prism_validator_flags_an_incomplete_dataset(tmp_path):
    bids, _ = make_trees(tmp_path)  # no Authors, no sidecars -> PRISM errors
    assert any(c["severity"] == "error" for c in check_validator(bids, "prism"))
    assert not any(c["severity"] == "error" for c in check_validator(bids, "bids"))
```
Also restore the strict assertion in `test_healthy_trees_have_no_errors` (`== "warnings"`).

- [ ] **Step 3: Run, verify fail**, then implement:

```python
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
```
In `run_preflight`, directly after the folder checks pass: `checks += check_validator(bids_dir, validator)`.
- [ ] **Step 4: Run** — `python -m pytest -q tests/test_preflight.py tests/test_uv_project.py` → PASS.
- [ ] **Step 5: Commit** — `feat(preflight): dataset validator via prism-validator (prism / plain BIDS / skip)`.

---

### Task 7: Config adapter + CLI

**Files:** Modify `lib/preflight.py`, `bidspm.py`; Create `tests/test_preflight_cli.py`.

**Interfaces:** Produces `run_preflight_from_config(cfg: dict, model="", validator="prism") -> dict` (reads `BIDS_DIR, FMRIPREP_DIR, MODELS_FILE, TASKS, SPACE, SUBJECTS, container_type`); CLI flags `--preflight`, `--validator {prism,bids,skip}`, `--skip-validator`; `handle_preflight(config_file, args)`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_preflight_cli.py
import json
import subprocess
import sys
from pathlib import Path

from lib.preflight import run_preflight_from_config
from tests.preflight_support import make_trees

ROOT = Path(__file__).resolve().parent.parent


def settings(tmp_path, **over):
    bids, fmriprep = make_trees(tmp_path)
    cfg = {"BIDS_DIR": str(bids), "FMRIPREP_DIR": str(fmriprep), "SPACE": "MNI", "TASKS": ["x"], "MODELS_FILE": ""}
    cfg.update(over)
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(cfg))
    return cfg, path


def test_from_config_matches_run_preflight(tmp_path):
    cfg, _ = settings(tmp_path)
    assert run_preflight_from_config(cfg, validator="skip")["verdict"] == "warnings"


def cli(*args):
    return subprocess.run([sys.executable, "bidspm.py", *args], cwd=ROOT, capture_output=True, text=True)


def test_cli_preflight_prints_json_and_exits_0_when_not_blocked(tmp_path):
    _, path = settings(tmp_path)
    proc = cli("--preflight", "--skip-validator", "-s", str(path))
    assert proc.returncode == 0 and json.loads(proc.stdout)["verdict"] == "warnings"


def test_cli_preflight_exits_1_when_blocked(tmp_path):
    _, path = settings(tmp_path, SPACE="T1w")
    proc = cli("--preflight", "--skip-validator", "-s", str(path))
    assert proc.returncode == 1 and json.loads(proc.stdout)["verdict"] == "blocked"
```
Check that `load_config`'s side effects/prints do not pollute stdout: `handle_preflight` reads the JSON directly, not `load_config`.

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** in `lib/preflight.py`:

```python
def run_preflight_from_config(cfg, model="", validator="prism"):
    return run_preflight(
        bids_dir=cfg.get("BIDS_DIR", ""), fmriprep_dir=cfg.get("FMRIPREP_DIR", ""),
        model_file=model or cfg.get("MODELS_FILE", ""), tasks=cfg.get("TASKS") or [],
        space=cfg.get("SPACE", ""), subjects=cfg.get("SUBJECTS") or [],
        validator=validator, container_type=cfg.get("container_type", ""))
```
`bidspm.py`: next to `--list-tasks` add

```python
    parser.add_argument('--preflight', action='store_true',
                        help='Check that BIDS, fMRIPrep and the model can run; print a JSON report, exit 1 if blocked')
    parser.add_argument('--validator', choices=['prism', 'bids', 'skip'], default='prism',
                        help='Dataset validator for --preflight: PRISM+BIDS (default), plain BIDS, or skip')
    parser.add_argument('--skip-validator', action='store_true', help='Same as --validator skip')
```
and

```python
def handle_preflight(config_file, args):
    """Print the preflight report as JSON; exit 1 when a check blocks the run."""
    import json
    from lib.preflight import run_preflight_from_config
    with open(config_file, encoding='utf-8') as fh:
        cfg = json.load(fh)
    result = run_preflight_from_config(cfg, model=args.model or '',
                                       validator='skip' if args.skip_validator else args.validator)
    print(json.dumps(result, indent=2))
    sys.exit(1 if result['verdict'] == 'blocked' else 0)
```
called in `main()` right after the `handle_check_environment` block: `if args.preflight: handle_preflight(config_file, args)`.
- [ ] **Step 4: Run** — `python -m pytest -q tests/test_preflight_cli.py tests/test_bidspm_cli.py` → PASS.
- [ ] **Step 5: Commit** — `feat(preflight): bidspm.py --preflight with --validator / --skip-validator`.

---

### Task 8: API route + blocking `/run`

**Files:** Create `webapp/web_preflight_api.py`, `tests/test_preflight_route.py`; Modify `bidspm_gui.py` (register), `webapp/web_execution_api.py` (gate), possibly `tests/test_web_execution_api.py`.

**Interfaces:** `POST /api/preflight` body `{config: {...unifiedStudyConfig}, model?, validator?}` → report JSON. `POST /run` returns `400 {"error", "preflight"}` when blocked. Run payload may carry `validator`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_preflight_route.py
import json
from unittest.mock import patch

from bidspm_gui import app
from tests.preflight_support import make_trees

BLOCKED = {"verdict": "blocked", "checks": [{"id": "bids_dir", "severity": "error", "subject": None, "message": "m", "fix": "f"}]}


def cfg(tmp_path, **over):
    bids, fmriprep = make_trees(tmp_path)
    return {"BIDS_DIR": str(bids), "FMRIPREP_DIR": str(fmriprep), "SPACE": "MNI", "TASKS": ["x"], **over}


def test_api_preflight_returns_the_report(tmp_path):
    res = app.test_client().post("/api/preflight", json={"config": cfg(tmp_path), "validator": "skip"})
    assert res.status_code == 200 and res.get_json()["verdict"] == "warnings"


def test_api_preflight_reports_blocking_problems(tmp_path):
    res = app.test_client().post("/api/preflight", json={"config": cfg(tmp_path, SPACE="T1w"), "validator": "skip"})
    assert res.get_json()["verdict"] == "blocked"


def test_run_refuses_to_start_when_preflight_is_blocked(tmp_path):
    settings = tmp_path / "s.json"
    settings.write_text(json.dumps(cfg(tmp_path)))
    with patch("webapp.web_execution_api.run_preflight_from_config", return_value=BLOCKED), \
         patch("webapp.web_execution_api.subprocess.Popen") as popen:
        res = app.test_client().post("/run", json={"actions": ["stats"], "settings": str(settings)})
    assert res.status_code == 400 and res.get_json()["preflight"]["verdict"] == "blocked"
    popen.assert_not_called()


def test_run_does_not_gate_report_or_bms_actions(tmp_path):
    settings = tmp_path / "s.json"
    settings.write_text(json.dumps(cfg(tmp_path)))
    with patch("webapp.web_execution_api.run_preflight_from_config") as pf, \
         patch("webapp.web_execution_api.subprocess.Popen"):
        app.test_client().post("/run", json={"actions": ["report"], "settings": str(settings)})
    pf.assert_not_called()
```

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement.**

```python
# webapp/web_preflight_api.py
"""Thin route for the GUI's readiness panel; the logic lives in lib/preflight.py."""
from flask import Flask, jsonify, request

from lib.preflight import run_preflight_from_config


def register_preflight_routes(app: Flask) -> None:
    @app.route('/api/preflight', methods=['POST'])
    def api_preflight():
        data = request.json or {}
        return jsonify(run_preflight_from_config(
            data.get('config') or {}, model=data.get('model') or '', validator=data.get('validator') or 'prism'))
```
Register in `bidspm_gui.py` next to the other `register_*` calls (import at the top, `register_preflight_routes(app)`).
In `webapp/web_execution_api.py` add `from lib.preflight import run_preflight_from_config` and, after the model-validation block and before `python_exe = ...`:

```python
        if data.get('settings') and any(a in ('smooth', 'stats', 'dataset') for a in actions):
            try:
                with open(data['settings'], encoding='utf-8') as stream:
                    preflight = run_preflight_from_config(
                        json.load(stream), model=data.get('model') or '', validator=data.get('validator') or 'prism')
            except (OSError, ValueError) as exc:
                return jsonify({'error': f'Failed to read settings file: {exc}'}), 400
            if preflight['verdict'] == 'blocked':
                return jsonify({'error': 'Preflight check failed: fix the listed problems before running.',
                                'preflight': preflight}), 400
```
- [ ] **Step 4: Run** the new file, then the full `python -m pytest -q tests`. Existing `/run` tests that pass fake settings paths may now fail: patch `webapp.web_execution_api.run_preflight_from_config` to return `{"verdict": "ready", "checks": []}` inside their `setUp` (do not weaken the new tests). Re-run until green.
- [ ] **Step 5: Commit** — `feat(preflight): /api/preflight and block /run on preflight errors`.

---

### Task 9: GUI panel

**Files:** Create `static/js/analysis_preflight.js`, `tests/test_preflight_browser.py`; Modify `templates/analysis.html`, `static/js/analysis_run.js`.

**Interfaces:** Elements `#validator-mode` (values `prism|bids|skip`), `#btn-preflight`, `#preflight-panel`; globals `validatorMode()`, `renderPreflight(report)`, `runPreflight()`. `startExecution` adds `payload.validator = validatorMode()` and renders `result.preflight` on a 400.

- [ ] **Step 1: Failing browser test** (mirror `tests/test_analysis_page_browser.py`; add the same `skipUnless(chromium_available(), ...)` guard)

```python
# tests/test_preflight_browser.py
import tempfile
import unittest
from pathlib import Path

from tests.browser_support import chromium_available, make_dataset, start_server, sync_playwright


@unittest.skipUnless(chromium_available(), "Playwright + Chromium not available")
class TestPreflightPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        make_dataset(Path(cls.tmp.name))
        cls.server, cls.base, cls.project_id = start_server(Path(cls.tmp.name))
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.tmp.cleanup()

    def test_button_renders_a_blocked_report_with_fix_hints(self):
        page = self.browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{self.base}/analysis/{self.project_id}", wait_until="networkidle")
        page.select_option("#validator-mode", "skip")
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .preflight-verdict")
        self.assertIn("blocked", page.inner_text("#preflight-panel").lower())  # the test project has no fMRIPrep tree
        self.assertTrue(page.locator("#preflight-panel .preflight-fix").count() >= 1)
        self.assertEqual(errors, [])

    def test_validator_choice_is_remembered_per_project(self):
        page = self.browser.new_page()
        page.goto(f"{self.base}/analysis/{self.project_id}", wait_until="networkidle")
        page.select_option("#validator-mode", "bids")
        page.reload(wait_until="networkidle")
        self.assertEqual(page.input_value("#validator-mode"), "bids")
```

- [ ] **Step 2: Run, verify fail** — `python -m pytest -q tests/test_preflight_browser.py` (needs Chromium; FAIL on missing `#validator-mode`).
- [ ] **Step 3: Implement.** In `templates/analysis.html` next to `#btn-check-paths` (inside the `btn-group`/column at ~line 147) add:

```html
<select class="form-select form-select-sm d-inline-block w-auto" id="validator-mode" title="Dataset validator used by the readiness check">
    <option value="prism">Validator: PRISM + BIDS</option>
    <option value="bids">Validator: plain BIDS</option>
    <option value="skip">Validator: skip</option>
</select>
<button type="button" class="btn btn-sm btn-outline-success" id="btn-preflight">Check readiness</button>
<div id="preflight-panel" class="mt-2"></div>
```
and register `analysis_preflight.js` in the existing script-tag loop (before `analysis_run.js`). New file:

```js
// analysis_preflight.js -- readiness panel: calls /api/preflight and renders the report. Logic lives in lib/preflight.py.
const VALIDATOR_KEY = `bidspm_validator_mode_${typeof currentProjectId !== 'undefined' ? currentProjectId : ''}`;

function validatorMode() {
    return document.getElementById('validator-mode')?.value || 'prism';
}

function renderPreflight(report) {
    const panel = document.getElementById('preflight-panel');
    if (!panel) return;
    const tone = {blocked: 'danger', warnings: 'warning', ready: 'success'}[report.verdict];
    const rows = report.checks.map(c => `<li class="small ${c.severity === 'error' ? 'text-danger' : 'text-warning'}">
        <strong>${c.subject ? 'sub-' + c.subject + ': ' : ''}</strong>${c.message}
        ${c.fix ? `<div class="preflight-fix text-muted">&rarr; ${c.fix}</div>` : ''}</li>`).join('');
    panel.innerHTML = `<div class="alert alert-${tone} py-1 mb-1 preflight-verdict">Readiness: <strong>${report.verdict}</strong></div><ul class="list-unstyled mb-0">${rows}</ul>`;
}

async function runPreflight() {
    updateInternalState();
    const res = await fetch('/api/preflight', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({config: unifiedStudyConfig, validator: validatorMode()})
    });
    renderPreflight(await res.json());
}

(function () {
    const select = document.getElementById('validator-mode');
    try { select.value = localStorage.getItem(VALIDATOR_KEY) || 'prism'; } catch (e) { /* storage unavailable */ }
    select.addEventListener('change', () => { try { localStorage.setItem(VALIDATOR_KEY, select.value); } catch (e) { /* ignore */ } });
    document.getElementById('btn-preflight').addEventListener('click', runPreflight);
})();
```
In `analysis_run.js` `startExecution`: before `fetch('/run'...)` add `payload.validator = validatorMode();` and replace the `if (result.error)` line with:
```js
    if (result.preflight) renderPreflight(result.preflight);
    if (result.error) { terminal.innerText += 'ERROR: ' + result.error; resetStatus(); return; }
```
(The script is loaded as a classic script after `updateInternalState`/`unifiedStudyConfig` exist; verify the load order in the template and place the tag after `analysis_project_form.js`.) Add `"renderPreflight"`, `"runPreflight"`, `"validatorMode"` to `GLOBAL_FUNCTIONS` in `tests/test_analysis_page_browser.py`.
- [ ] **Step 4: Run** — `python -m pytest -q tests/test_preflight_browser.py tests/test_analysis_page_browser.py tests/test_web_routes.py` → PASS.
- [ ] **Step 5: Commit** — `feat(preflight): readiness panel in the analysis page`.

---

### Task 10: Docs, review, wrap-up

**Files:** Modify `README.md`.

- [ ] **Step 1:** Add a "Readiness check (preflight)" section to `README.md`: what is checked (the list from the spec), `python bidspm.py --preflight -s config/config.json [--validator bids|--skip-validator]`, that errors block Run in the GUI, that `skip` disables only the dataset validator, and the version (2.0.1, shown in the footer, from `pyproject.toml`). Mention that `prism-validator` is installed by `uv sync`.
- [ ] **Step 2:** Full suite: `python -m pytest -q tests` → all green (browser tests may skip). Fix anything red; do not weaken tests.
- [ ] **Step 3:** Smoke it for real: `python bidspm.py --preflight --skip-validator -s <a real project's exported settings>`; read the output; check a known-good study yields no errors and a deliberately wrong `SPACE` yields `preproc_missing`. Report actual output.
- [ ] **Step 4:** Run `/ponytail:ponytail-review` on `git diff main...HEAD`; resolve or consciously defer each finding (CLAUDE.md).
- [ ] **Step 5:** Commit docs; use superpowers:verification-before-completion, then superpowers:finishing-a-development-branch. Do not merge or tag without the user's go-ahead. Part A (task wizard + transformer recipes) gets its own brainstorm after this merges.
