# Preflight readiness check + repo version 2.0.1

Status: approved 2026-10-16. Part B of "B then A" (A = task wizard + transformer recipes, separate spec).

## Goal
A scientist supplying fMRIPrep derivatives + BIDS events should learn *before* a run, in plain language,
whether the run can succeed. Errors block Run; there is no override.

## Version
Single source: `pyproject.toml` `version = "2.0.1"`. `bidspm_gui.py` reads it (tomllib) into `app.config['APP_VERSION']`; `base.html` footer shows `v2.0.1`.
No git tag is created until the user asks.

## Architecture
- `lib/preflight.py`: pure functions, no Flask. `run_preflight(bids_dir, fmriprep_dir, model_file, tasks, space, subjects) -> dict`
  returning `{verdict: ready|blocked|warnings, checks: [{id, severity: error|warn, subject, message, fix}]}`.
- `bidspm.py preflight ...` CLI command prints/returns the same JSON (GUI triggers the CLI/lib; logic stays in `lib/`).
- `/run` gates only smooth/stats/dataset; the CLI run path is not gated (only `--preflight` reports).
- `webapp/`: thin `POST /api/preflight` route. The "Check Folders" and "Check readiness" buttons both exist; Run executes the
  preflight first and refuses to start while any check has severity `error`.

## Checks
1. BIDS and fMRIPrep dirs exist; `dataset_description.json` and `sub-*` present (error).
2. Selected subjects exist in BIDS and in fMRIPrep (error).
3. Per subject/task: `desc-preproc_bold` in the requested space (error).
4. Per subject/task: `*_events.tsv` with `onset`, `duration` columns (error).
5. Events plausible: numeric onsets, non-negative durations; `trial_type` present when model uses it (error); onset beyond scan length (warn). Scan-length compares only when a subject/task has exactly one events file and one preproc file.
6. Model-referenced conditions exist in the events: error if a condition is absent from every events file of the task; warn per subject if absent only for some.
7. Confounds file exists and model-used regressors are among its columns (error). Check 7 runs only when the model lists nuisance regressors.
8. Model passes existing checks: dataset node name, empty contrasts, schema (reuses `lib/core.py`).
9. Container image/engine available (warn).

## Dataset validator (check 0)
- `prism-validator <bids_dir> --json` as a subprocess (BIDS validator + PRISM checks; `--no-prism` for plain BIDS). Mode is a user choice, default `prism`: GUI select (PRISM / plain BIDS / skip), CLI `--validator {prism,bids,skip}` + alias `--skip-validator`; remembered per project in localStorage. Skipping only affects this check (e.g. unrelated DWI problems); every other check still blocks, and a skipped validator is a `warn`. Validator errors are grouped by code + first message line (count and one example path). No marker detection. Never `--fix`, never `--plugins`.
- Validator errors -> `error` (blocks Run); warnings -> `warn`. Dependency in `pyproject.toml`/`uv.lock`; if missing -> `warn`, other checks still run.
- No result cache in v1 (add if validation proves slow); shown as its own labelled section in the panel.
- The first test fixture is a real `--json` run on a small dataset to pin the severity mapping.

## Testing (TDD)
Failing test first for each check, using small synthetic BIDS/fMRIPrep trees in `tmp_path`
(`tests/test_preflight.py`); then route test, CLI test, version test, and a Playwright test of the panel (skips without playwright).

## Gate behaviour
- Actions-aware: when the requested actions contain neither `stats` nor `dataset` (e.g. smooth only), only folder, subject, preproc and validator checks run, so a task without events can still be smoothed. The `/api/preflight` route accepts optional `actions`; CLI `--preflight` uses `--action`.
- `/run` with `skip_validation` skips the model check (the same validation was skipped by `/run`); all other checks still run.
- Nuisance regressors in the model: intercepts (`1`, `0`, int or string), columns of the task's events files (e.g. parametric modulators) and names produced by the node's Transformations (`Output`) are not looked up in the confounds file; if the node has Transformations, an unmatched name is a `warn`. `Transformations` without `Instructions` count as none. Negative onsets are a `warn`; a dataset-level `task-<task>_events.tsv` is accepted when a subject has none.

## Out of scope
SESSION and RUNS settings are not honoured by the preflight (all sessions/runs of a task are checked).
Auto-fixing problems; image-content checks (voxel size, TR vs sidecar).
