# Model wizard: guided BIDS-StatsModel creation with transformer recipes (Part A)

Status: design approved 2026-10-16 (Python implementation). Follows Part B (preflight, merged 4d5177d).

## Goal
A scientist with fMRIPrep + BIDS events builds a valid BIDS-StatsModel without hand-writing JSON: pick the task and
conditions, choose transformer *recipes* (what they want to model), choose nuisance regressors and contrasts, review a live
preview + preflight, save. Transformers become a guided choice instead of a side trip.

## Architecture
- `lib/model_wizard.py` (pure Python, no Flask): recipe registry + `scan_choices(...)`, `build_model(choices) -> {"model", "preview"}`.
  `preview` = regressors (the final Run `X` entries), contrasts, warnings. Each recipe is data: id, title, parameter schema,
  `apply(state, params)` returning Transformations instructions, extra X names, optional SPM parametric modulations.
- `webapp/web_wizard_api.py` (thin): `POST /api/wizard/scan` (task list, per-task events columns + values, confound columns;
  reuses `_discover_event_info` / `_discover_confound_info` / `discover_tasks`), `POST /api/wizard/build` (returns model + preview;
  `save_path` optional -> writes the file, 409 unless `overwrite`), preflight on the proposed model via `run_preflight`.
- `templates/model_wizard.html` + `static/js/model_wizard.js`: stepper page `/model-wizard/<project_id>` in the style of the
  transformer builder page. "New model" on the analysis page opens it (replaces the `prompt()` path box); it ends by saving and
  returning to the analysis editor with the new model loaded. No logic in JS beyond rendering and collecting choices.

## Steps
1. Task and conditions (scanned from events). 2. Recipes (all offered; the user chooses which to apply, in order).
3. Nuisance regressors: presets none / 6 motion / 24 motion (Friston) / 6 motion + FD, a custom comma-separated list of confound columns instead of the existing picker.
4. Contrasts: auto "condition > baseline" for every regressor + a simple pair table ("A > B", "mean(A,B) > C"); the full
   contrast builder stays available as an advanced option (the wizard writes the model, then the user can open it there).
5. Review: preview of regressors + contrasts + the preflight panel for the proposed model; save.
Second level: default Subject and Dataset nodes (one-sample) as today; group comparisons via the existing dataset presets.

## Recipes (v1: all four are offered)
Formats verified against bidspm 4.0.0 (`/data/local/container/bidspm/bidspm`) and the repo's own studies:
- **Only valid/correct trials**: chain of `Filter` instructions (`trial_type==item` -> `trial_item`, `response_validity==valid` ->
  `valid_item`); X gets `valid_item.item`. Reference: `studies/141_fix_pmod.json`.
- **Split a condition by a column**: for each value: `Filter` (condition and column value) -> named output.
- **Parametric modulator**: not mean-centred by the wizard (SPM centres modulators itself); adds
  `Model.Software.SPM.ParametricModulations: [{Name, Conditions: ["trial_type.x"], Values: ["<col>"], PolynomialExpansion}]`
  (amplitude column read from the events TSV; NaN coerced to 1 by bidspm).
- **Merge / rename conditions**: `Replace` on `trial_type` (regex key -> value) for merging, rename = Replace with literal key.
Recipes compose in the order the user applies them; each declares inputs/outputs so later recipes and the X list stay consistent.

## Correctness
- Conditions produced by recipes are tracked by the engine (no re-implementation of the transformer runtime): the preview lists
  the regressors; the preflight panel (events columns/values present, confound columns, model schema) validates the result.
- A recipe whose inputs are unusable (e.g. no numeric column for pmod) is not disabled up front; the error appears when building (the preview shows the engine message). Recipes with unfilled required fields are not sent and are marked incomplete.
- Scan returns confound columns, but they are informational only (the build does not use them).
- Unique SPM names: bidspm names an SPM condition after the part of a regressor behind its first '.', so every regressor must have a distinct name there. Splits with several values (or keep_original) add a Replace instruction that renames the kept cell values to the output column and use `<out>.<out>`; a single-value split keeps `<out>.<condition>`. build_model rejects any remaining clash.
- The live preview skips the preflight (slow on real studies); the "Check readiness" button and Save run it. Scans are cached for 60 s per (bids, task).
- The wizard never writes a model bidspm would silently ignore: unsupported combinations are rejected with a message.
- Acceptance test: the "valid trials" recipe on study 141's choices reproduces the Run node `Transformations`, `X` and
  `ParametricModulations` of `studies/141_fix_pmod.json` (golden test).

## Testing (TDD, per project rule)
Unit tests per recipe and for `build_model` (golden JSON), route tests, a Playwright test of the stepper (skips without
playwright), preflight integration test on the generated model against synthetic trees (`tests/preflight_support.py`).

## Out of scope (v1)
Editing existing models in the wizard (use the editor), group-level wizard steps, running transformers to show transformed
TSV rows (preview shows names, not rows), recipes beyond the four, SESSION/RUN selection,
per-trial split (`LabelIdenticalRows`; regressor names would depend on trial counts, which the preview cannot know).

## Defaults
The generated Run node is named `run_level`; the intercept in `X` is the integer `1`.
