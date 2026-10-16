# Preflight readiness check + repo version 2.0.1

Status: approved 2026-10-16. Part B of "B then A" (A = task wizard + transformer recipes, separate spec).

## Goal
A scientist supplying fMRIPrep derivatives + BIDS events should learn *before* a run, in plain language,
whether the run can succeed. Errors block Run; there is no override.

## Version
Single source: `pyproject.toml` `version = "2.0.1"`. `bidspm_gui.py` reads it via `importlib.metadata`
(fallback: parse pyproject) into `app.config['APP_VERSION']`; `base.html` footer shows `v2.0.1`.
No git tag is created until the user asks.

## Architecture
- `lib/preflight.py`: pure functions, no Flask. `run_preflight(bids_dir, fmriprep_dir, model_file, tasks, space, subjects) -> dict`
  returning `{verdict: ready|blocked|warnings, checks: [{id, severity: error|warn|ok, subject, message, fix}]}`.
- `bidspm.py preflight ...` CLI command prints/returns the same JSON (GUI triggers the CLI/lib; logic stays in `lib/`).
- `webapp/`: thin `POST /api/preflight` route. "Check Folders" becomes "Check readiness"; Run executes the
  preflight first and refuses to start while any check has severity `error`.

## Checks
1. BIDS and fMRIPrep dirs exist; `dataset_description.json` and `sub-*` present (error).
2. Selected subjects exist in BIDS and in fMRIPrep (error).
3. Per subject/task: `desc-preproc_bold` in the requested space (error).
4. Per subject/task: `*_events.tsv` with `onset`, `duration` columns (error).
5. Events plausible: numeric onsets, non-negative durations; `trial_type` present when model uses it (error); onset beyond scan length (warn).
6. Model-referenced conditions exist in the events (error).
7. Confounds file exists and model-used regressors are among its columns (error).
8. Model passes existing checks: dataset node name, empty contrasts, schema (reuses `lib/core.py`).
9. Container image/engine available (warn).

## Testing (TDD)
Failing test first for each check, using small synthetic BIDS/fMRIPrep trees in `tmp_path`
(`tests/test_preflight.py`); then route test, CLI test, version test, and a Playwright test of the panel (skips without playwright).

## Out of scope
Auto-fixing problems; image-content checks (voxel size, TR vs sidecar).
