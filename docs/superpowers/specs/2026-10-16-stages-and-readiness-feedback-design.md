# Stage-based UX + live readiness feedback

Status: design approved 2026-10-16 (layout: one step at a time + summary rail; scope: wizard AND analysis page; final stage
"Review and run" holds readiness + Run). Follows the model wizard (a4eb5da) and the preflight speedups (feature/preflight-speed).

## Problem
Both pages show every option at once, which overwhelms first-time users. The readiness check gives one "Checking readiness..."
line and blocks a request; on a 100-subject dataset it still takes ~15 s (validator) after the speedups and the user sees nothing.

## Principles (both pages)
- One stage on screen; a strip shows done / current / upcoming stages with a one-line summary of each finished stage.
- Back and Next buttons; any visited stage is clickable. Next works with defaults; invalid stages (missing folders, no model,
  incomplete recipe) block Next with a plain-language reason, never silently.
- Anything optional is behind an "Advanced" disclosure inside its stage.
- Pure view logic in JS (show/hide, summaries); validity rules that exist in lib/ (preflight, wizard engine) stay there.

## A. Analysis page stages (no DOM removal)
Stages: **1 Folders -> 2 Model -> 3 Options -> 4 Review and run**. The existing "Setup Guide" strip (templates/analysis.html
~L71, static/js/analysis_stepper.js) is replaced by the stage strip. Every existing element stays in the DOM (the ~20
analysis_*.js modules look elements up by id), stages only toggle visibility through a `data-stage` attribute + a CSS class.
- Folders: WD, BIDS, derivatives, fMRIPrep, tasks, Space/FWHM/Verbosity ("Advanced": verbosity, derivatives folder).
- Model: the MODELS_FILE row (moved by `data-stage`, not by DOM surgery), model workspace (Create Model -> opens the wizard,
  Contrast Builder, Transformer Builder, editor).
- Options: actions (smooth/stats/dataset/report/bms), execution options, container settings (container under Advanced).
- Review and run: summary of stages 1-3, the readiness check (Check readiness + validator mode + live progress panel), the
  action bar (Save & Run, Save, Run, Stop), run issues, terminal. Run controls exist only here.
- Next enabled when the stage is valid: Folders = four paths set; Model = models file set; Options = at least one action.
- The last stage is remembered per project (localStorage, try/catch) and `#stage=<name>` deep-links work; first visit starts at
  the first incomplete stage.
- Existing browser tests that click elements now first select the stage (a test helper `go_to_stage(page, name)`); JS tests that
  call functions via evaluate() are unaffected.

## B. Model wizard stages
Replace the five stacked cards (templates/model_wizard.html, static/js/model_wizard.js) by a real stepper: Task and conditions ->
Recipes -> Nuisance -> Contrasts -> Review. A slim right-hand rail shows the live preview (regressors, contrasts, warnings)
on every step.
- Recipes step: a gallery of four cards (Only valid trials, Split a condition, Merge or rename, Parametric modulator), each with a
  one-line explanation; clicking adds the recipe and opens its small form; nothing added = "No special handling needed";
  reorder/remove stays; incomplete recipes block Next.
- Nuisance step: preset radios; custom list under Advanced.
- Contrasts step: automatic contrasts on by default; "Add a comparison" reveals the pair table; the advanced link opens the full
  contrast builder.
- Review step: preview, Check readiness (progress panel below), Save.

## C. Readiness feedback (progress)
Builds on the speedups (header-only confounds, validator overlapped, one listing per subject: 141 3 s without validator).
- `run_preflight(..., progress=None)`: optional callback receiving events `{phase, index, total, subject, elapsed, items}`;
  phases: folders, subjects, validator (indeterminate), per-subject checks (i/N), model, done. Partial items are emitted as found.
- GUI transport: SSE, mirroring `/stream/<execution_id>` (webapp/web_execution_api.py): `POST /api/preflight/start` ->
  `{id}`, `GET /api/preflight/stream/<id>` (events replay from an index on reconnect), `POST /api/preflight/cancel/<id>`;
  jobs live in memory, cleaned up after completion (cap the registry). The synchronous `/api/preflight` stays for tests/CLI users.
  The `/run` gate reuses a recent passing result for the same settings signature instead of repeating the check.
- CLI: `--progress` writes progress lines to stderr; stdout stays pure JSON.
- Panel (analysis_preflight.js, shared by the wizard review step): phase list with a per-subject bar, indeterminate bar for the
  validator, errors appended live with running counts, Cancel button, final verdict as today. All text via textContent.

## Testing (TDD)
- Python: progress events from run_preflight (order, counts, partial items, cancel), SSE route (events, reconnect replay, cancel,
  registry cleanup), `/run` reuse of a recent result.
- Browser (Playwright): stage navigation and Next gating on both pages, remembered stage, deep link, recipe gallery,
  summary rail updates, live progress panel with mocked SSE, cancel.
- Real-data check at the end: preflight progress on study 141 visible in the GUI (screenshot-free assertions on events) and a
  wizard flow end to end.

## Out of scope
Redesigning the model editor internals, the projects page, the transformer builder page; mobile layout.
