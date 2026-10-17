# Stages and Readiness Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make both pages stage-based (one stage on screen, summaries, Back/Next) and give the readiness check live progress (phases, per-subject counter, early errors, cancel).

**Architecture:** `lib/preflight.py` gains an optional progress/cancel interface and a small recent-result cache; `webapp/web_preflight_api.py` adds an in-memory job registry with SSE start/stream/cancel endpoints (mirroring `/stream/<execution_id>`); a shared `readiness_panel.js` renders progress for both pages; the analysis page gets `data-stage` visibility staging without removing any DOM; the model wizard becomes a real stepper with a recipe gallery and summary rail.

**Tech Stack:** Python 3.12 (uv), Flask SSE, threads, vanilla JS + Bootstrap, Playwright browser tests. No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-16-stages-and-readiness-feedback-design.md` (approved). Existing behaviour that must not change: report shape `{"verdict","checks"}`, check item shape, validator items first, errors block Run, `/api/preflight` synchronous endpoint (kept for tests/CLI).
- TDD always (CLAUDE.md): failing test first, see it fail, then the code. Logic in `lib/`; JS only renders and collects.
- **Lessons from the preflight and wizard reviews — apply from the start:** (1) every server string goes into the DOM via `textContent`/DOM nodes, never `innerHTML`; (2) wrong-typed or malformed request input returns a JSON 400, never an HTML 500 (check `request.get_json(silent=True)` shapes); (3) never silently drop or skip user input when saving/running — refuse with a visible message; (4) stale-response guards (sequence counters) for every async render; (5) a callback/stream failure must degrade to a clear message, never an unhandled rejection or a blank panel; (6) browser tests: `tearDown` closes pages, use `wait_until="load"` for `/analysis/<id>` (it never reaches networkidle), no `time.sleep` inside Playwright route handlers, Event/condition waits instead of wall-clock margins, and mutation-check important tests (temporarily break the code, see RED, revert); (7) a11y: labels or aria-labels on every control, `type="button"` on buttons, focus kept sensible after re-render; (8) tests must assert behaviour (no tests that only check an element exists).
- Browser tests must really run (check `-rs`). Known flake: `tests/test_new_features.py::test_analysis_page_renders_second_level_add_node_menu` (rerun alone). Run `.bidspm/bin/python -m pytest -q tests` before the last commit of each task. Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Before merging to main: `/ponytail:ponytail-review` on the branch diff (Task 8). Do not bump the version.

## File Structure

- Modify `lib/preflight.py` (progress/cancel, recent-result cache), `bidspm.py` (`--progress`), `webapp/web_preflight_api.py` (jobs + SSE), `webapp/web_execution_api.py` (`/run` reuses a recent passing result), `static/js/analysis_preflight.js`, `static/js/analysis_run.js` (only if needed), `templates/analysis.html`, `static/js/analysis_stepper.js` (replaced by `analysis_stages.js`), `templates/model_wizard.html`, `static/js/model_wizard.js`, `README.md`.
- Create `static/js/readiness_panel.js` (shared progress panel), `static/js/analysis_stages.js`, tests: `tests/test_preflight_progress.py`, `tests/test_preflight_jobs.py`, `tests/test_preflight_recent.py`, `tests/test_readiness_panel_browser.py`, `tests/test_analysis_stages_browser.py`; extend `tests/test_wizard_browser.py`; add `go_to_stage` helper to `tests/browser_support.py`.

---

### Task 1: Progress and cancel in `run_preflight` + CLI `--progress`

**Files:** Modify `lib/preflight.py`, `bidspm.py`; Create `tests/test_preflight_progress.py`.

**Interfaces:**
- Produces: `run_preflight(..., progress=None, cancelled=None)` and `run_preflight_from_config(..., progress=None, cancelled=None)`. `progress(event: dict)` is called with `{"phase": "folders"|"validator"|"subjects"|"model"|"done", "state": "start"|"progress"|"done", "message": str, "index": int|None, "total": int|None, "subject": str|None, "elapsed": float, "items": list[dict]}` where `items` are the check items found since the previous event. `cancelled()` is polled between subjects and before slow phases; when true the run stops and returns `{"verdict": "cancelled", "checks": [<items found so far>]}`. Callback exceptions are swallowed (they must never break the preflight).
- Event order: `folders` start/done; `validator` start (only when a validator thread runs; `done` with its items as soon as it finishes — poll the future after each subject); `subjects` start with total=N, then one `progress` event per subject with index 1..N (the loop over tasks x subjects counts each (task, subject) once; total = len(tasks) x len(present subjects)); `model` start/done; final `done` event carrying all remaining items and `"verdict"`.

- [ ] **Step 1: Failing tests** (`tests/test_preflight_progress.py`; use `tests/preflight_support.make_trees`)

```python
import time
from unittest.mock import patch

from lib.preflight import run_preflight
from tests.preflight_support import make_trees


def collect(tmp_path, **kw):
    bids, fmriprep = make_trees(tmp_path, subjects=("01", "02", "03"))
    events = []
    args = dict(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    args.update(kw)
    report = run_preflight(**args, progress=events.append)
    return report, events


def test_subject_progress_counts_1_to_n_and_ends_with_done(tmp_path):
    report, events = collect(tmp_path)
    steps = [e for e in events if e["phase"] == "subjects" and e["state"] == "progress"]
    assert [(e["index"], e["total"]) for e in steps] == [(1, 3), (2, 3), (3, 3)]
    assert [e["subject"] for e in steps] == ["01", "02", "03"]
    assert events[-1]["phase"] == "done" and events[-1]["verdict"] == report["verdict"]
    assert all(e["elapsed"] >= 0 for e in events)


def test_partial_items_arrive_with_the_subject_that_caused_them(tmp_path):
    bids, fmriprep = make_trees(tmp_path, subjects=("01", "02"))
    next((fmriprep / "sub-02").rglob("*desc-preproc_bold.nii.gz")).unlink()
    events = []
    run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip", progress=events.append)
    by_subject = {e["subject"]: e["items"] for e in events if e["phase"] == "subjects" and e["state"] == "progress"}
    assert not [i for i in by_subject["01"] if i["severity"] == "error"]
    assert [i["id"] for i in by_subject["02"] if i["severity"] == "error"] == ["preproc_missing"]


def test_cancel_stops_between_subjects_and_reports_cancelled(tmp_path):
    seen = []
    bids, fmriprep = make_trees(tmp_path, subjects=("01", "02", "03"))
    report = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip",
                           progress=lambda e: seen.append(e),
                           cancelled=lambda: sum(1 for e in seen if e["phase"] == "subjects" and e["state"] == "progress") >= 1)
    assert report["verdict"] == "cancelled"
    assert sum(1 for e in seen if e["phase"] == "subjects" and e["state"] == "progress") == 1


def test_validator_events_when_it_runs(tmp_path):
    with patch("lib.preflight.check_validator", return_value=[]):
        _, events = collect(tmp_path, validator="bids")
    states = [(e["phase"], e["state"]) for e in events if e["phase"] == "validator"]
    assert states[0] == ("validator", "start") and states[-1] == ("validator", "done")


def test_validator_items_are_emitted_when_it_finishes_and_stay_first_in_the_report(tmp_path):
    item = {"id": "validator", "severity": "warn", "subject": None, "message": "m", "fix": ""}

    def slow(*a, **k):
        time.sleep(0.05)
        return [item]
    with patch("lib.preflight.check_validator", side_effect=slow):
        report, events = collect(tmp_path, validator="bids")
    assert report["checks"][0] == item
    assert any(item in e["items"] for e in events if e["phase"] == "validator")


def test_a_failing_callback_never_breaks_the_check(tmp_path):
    bids, fmriprep = make_trees(tmp_path)

    def boom(event):
        raise RuntimeError("callback bug")
    report = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip", progress=boom)
    assert report["verdict"] in ("ready", "warnings")


def test_no_callback_behaves_as_before(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    assert run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")["verdict"] == "warnings"
```
Also a CLI test in the same file or `tests/test_preflight_cli.py`: `bidspm.py --preflight --skip-validator --progress -s cfg` -> stdout is exactly one JSON document, stderr contains `sub-01` and `/` progress counters.

- [ ] **Step 2: Run, verify fail.** `.bidspm/bin/python -m pytest -q tests/test_preflight_progress.py` -> FAIL (unexpected keyword `progress`).
- [ ] **Step 3: Implement.** Read `lib/preflight.py` (`run_preflight`, `_subject_checks`) first. Add a tiny internal `_Progress` helper (monotonic start time, `emit(phase, state="progress", message="", index=None, total=None, subject=None, items=(), **extra)` that wraps the callback in try/except and does nothing when no callback; `cancelled()` wrapper) and thread it through `_subject_checks` (emit after each (task, subject), check `cancelled()` before each). When the validator thread is running, after each subject poll `pending.done()` once and emit its items (then remember it was emitted so the final report still puts them first); emit `validator` start before submit. The final `done` event contains the verdict and all items not yet emitted. On cancel: stop the loop, still `pool.shutdown(wait=True)`? — NO: on cancel use `pool.shutdown(wait=False, cancel_futures=True)` (a cancelled check must return promptly; the validator subprocess finishes in the background), return `{"verdict": "cancelled", "checks": <items so far>}`. Add `progress`/`cancelled` pass-through parameters to `run_preflight_from_config`. CLI: `--progress` (store_true) in `bidspm.py`; `handle_preflight` passes a callback that writes one line per event to stderr (e.g. `[2/100] sub-02 ... 0 issues`, phase lines for validator/model), stdout stays the pure JSON. Keep `_verdict` for normal runs.
- [ ] **Step 4: Run** `tests/test_preflight*.py tests/test_wizard_route.py` -> PASS (all existing preflight tests unchanged).
- [ ] **Step 5: Commit** `feat(preflight): progress events, cancel, CLI --progress`.

---

### Task 2: Jobs API with SSE (start / stream / cancel) and `model_json`

**Files:** Modify `webapp/web_preflight_api.py`; Create `tests/test_preflight_jobs.py`.

**Interfaces:**
- Consumes: Task 1 (`progress`, `cancelled`).
- Produces: `POST /api/preflight/start` body `{config, model?, model_json?, validator?, actions?, skip_model_validation?}` -> `{"id": str}` (400 JSON on malformed bodies; `model_json` must be a dict, written to a temp file used as the model and removed when the job ends); `GET /api/preflight/stream/<id>?from=N` -> `text/event-stream`, each event `id: <index>\ndata: <json event>\n\n`, keepalive comment every second while waiting, the stream ends after the terminal `done` event, which carries `report` (the full `{"verdict","checks"}`); unknown id -> one `data: {"phase":"error","message":"job not found"}` event; `POST /api/preflight/cancel/<id>` -> `{"status": "cancelling"|"finished"|"unknown"}`. In-memory registry `_JOBS` guarded by a lock, keeps at most 20 finished jobs (oldest evicted) and never evicts a running job.

- [ ] **Step 1: Failing tests** (Flask test client; patch `run_preflight_from_config` where timing matters; real tree via `make_trees` for one end-to-end test)

```python
# tests/test_preflight_jobs.py -- cases to implement fully
# 1. start -> {"id"}; GET stream returns events in order ending with phase "done" whose "report" equals the
#    synchronous /api/preflight result for the same body (real tree, validator "skip").
# 2. reconnect: GET stream?from=3 yields only events with index >= 3 (collect once, then replay the tail).
# 3. cancel: start a job whose patched run_preflight_from_config blocks on a threading.Event until cancelled() is true;
#    POST cancel -> "cancelling"; stream ends with verdict "cancelled"; cancel again after finish -> "finished";
#    unknown id -> "unknown".
# 4. model_json: the temp model file exists while the job runs (patched runner asserts os.path.isfile(model)) and is
#    deleted afterwards; model_json that is not a dict -> 400.
# 5. malformed bodies (non-dict body, config not a dict, actions not a list) -> 400 JSON, never 500.
# 6. registry cap: start 25 quick jobs sequentially; at most 20 finished jobs remain; a running job is never evicted.
# 7. a job whose runner raises ends with a terminal event {"phase":"done","report":{"verdict":"error",...}} or an
#    explicit {"phase":"error","message":...} — choose one, document it, test it (the GUI must show the message).
```
- [ ] **Step 2: Run, verify fail** (404s).
- [ ] **Step 3: Implement.** Job object: `events` list, `lock`, `cancel_event`, `done_event`, `report`. Worker thread runs `run_preflight_from_config(config, model=..., validator=..., skip_model_validation=..., actions=..., progress=job.add_event, cancelled=cancel_event.is_set)`; `add_event` appends `{**event, "index": len(events)}` under the lock; the terminal event is `{"phase": "done", "state": "done", "report": report, "index": ...}`. Stream generator loops: yield events from `from` onward, keepalive, stop after the done/error event; use `stream_with_context` as `/stream/<execution_id>` does. Wrap worker body in try/except Exception -> terminal error event. Temp model file via `tempfile.mkstemp`, removed in `finally`. Keep `/api/preflight` unchanged.
- [ ] **Step 4: Run** `tests/test_preflight_jobs.py tests/test_preflight_route.py tests/test_gui_smoke.py` -> PASS. **Step 5: Commit** `feat(preflight): job API with SSE progress stream and cancel`.

---

### Task 3: Recent-result reuse in the `/run` gate

**Files:** Modify `lib/preflight.py`, `webapp/web_preflight_api.py`, `webapp/web_execution_api.py`; Create `tests/test_preflight_recent.py`.

**Interfaces:** `lib.preflight.signature(cfg, model, validator, actions, skip_model_validation) -> str` (stable hash of the config dict content, model path + its mtime/size, validator, sorted actions, flag); `remember(sig, report)` stores only reports whose verdict is `ready` or `warnings` (never `blocked`/`cancelled`) with a monotonic timestamp; `recent(sig, ttl=600) -> report|None`. The jobs endpoint calls `remember` when a job finishes; the `/run` gate calls `recent(sig)` before running the check and, on a hit, skips it. A model edit changes the signature (mtime/size); a changed settings value changes it; `ponytail:` comment: dataset edits during the TTL are not noticed (10 min), fine for a local single-user tool.

- [ ] **Step 1: Failing tests:** signature differs per config value/model mtime/validator/actions; `remember` ignores blocked/cancelled; `recent` expires after ttl (patch the clock); `/run` with a remembered signature does not call `run_preflight_from_config` (patch it, assert not called) while a different signature does; a blocked remembered result is never reused (a blocked run still blocks).
- [ ] **Step 2-5:** implement, run `tests/test_preflight_recent.py tests/test_preflight_route.py tests/test_web_execution_api.py tests/test_web_routes.py`, commit `feat(preflight): /run reuses a recent passing readiness result`.

---

### Task 4: Shared readiness panel with live progress (analysis page)

**Files:** Create `static/js/readiness_panel.js`, `tests/test_readiness_panel_browser.py`; Modify `static/js/analysis_preflight.js`, `templates/analysis.html` (script tag + panel container only), `tests/test_analysis_page_browser.py` (GLOBAL_FUNCTIONS if names change).

**Interfaces:** `window.ReadinessPanel.run({target: HTMLElement, body: object, onDone?: (report)=>void}) -> {cancel()}` posts `/api/preflight/start`, opens `EventSource('/api/preflight/stream/<id>')`, renders into `target`: a phase list (folders, dataset validator, subjects, model — each pending/running/done with a tick), an indeterminate bar while the validator runs, a determinate bar with "i / N subjects" while subjects are checked, errors/warnings appended live under the list with running counts, a Cancel button (calls `/api/preflight/cancel/<id>` and shows "Cancelled"), and the final verdict banner (same look as today's `renderPreflight`, which becomes the final render). Failure paths: start returns non-JSON/!ok, EventSource error before `done` (show "Lost connection to the server" + a Retry button, no unhandled rejection), terminal `phase:"error"` event (show its message). A sequence counter ignores events of an older run. `analysis_preflight.js` keeps `validatorMode()` and the validator select behaviour and the `Check readiness` button now calls `ReadinessPanel.run` with `{config: unifiedStudyConfig, validator, actions: ...}`; `renderPreflight` stays exported for the run-gate 400 path (`analysis_run.js`).

- [ ] **Step 1: Failing browser tests** (mock the endpoints with `page.route`: start returns `{"id":"j1"}`; the stream response is a prepared `text/event-stream` body — Playwright's `route.fulfill` can deliver the whole stream at once, which is enough for rendering assertions; use a second test with a small local test server or an in-process Flask route from the real app for true incremental streaming if you need to assert intermediate states): phases tick in order; the subject bar shows "2 / 3"; errors appear before the final verdict; Cancel posts the cancel request and shows "Cancelled"; a stream cut before `done` shows the connection message and Retry; non-JSON 500 on start shows a message; an event message containing `<b>x</b>` renders as text; an older run's late events are ignored after a second click.
- [ ] **Step 2-5:** implement; run `tests/test_readiness_panel_browser.py tests/test_preflight_browser.py tests/test_analysis_page_browser.py`; commit `feat(preflight): live readiness progress panel`.

---

### Task 5: Analysis page stages

**Files:** Create `static/js/analysis_stages.js`, `tests/test_analysis_stages_browser.py`; Modify `templates/analysis.html`, `static/js/analysis_stepper.js` (delete after replacing), `tests/browser_support.py` (`go_to_stage(page, name)`), existing browser tests that interact with elements that will now be hidden by default.

**Interfaces:** stage names `folders`, `model`, `options`, `run`. Elements get `data-stage="<name>"` (container-level; the MODELS_FILE `path_input` row gets `data-stage="model"` through its wrapper without moving DOM; the readiness controls — Check Folders/Validate JSON/validator select/Check readiness/panel — and the action bar, run issues, terminal get `data-stage="run"`; the execution-options column and actions get `options`; paths, tasks, space/FWHM get `folders`; the model workspace section gets `model`). CSS class `stage-hidden { display: none !important; }` (no DOM removal; all `getElementById` lookups keep working). A stage strip (replaces `#analysis-stepper`) with `role="tablist"`-style buttons `data-stage-btn`, done/current/upcoming classes, a one-line summary under finished stages (Folders: BIDS folder name + space + FWHM; Model: model file name; Options: selected actions), Back/Next buttons (`#stage-back`, `#stage-next`) with a visible reason when Next is blocked (`#stage-hint`): Folders needs the four path fields set, Model needs a models file, Options needs at least one action. Advanced disclosures (`<details>`) for verbosity and container settings inside their stages. The "Review and run" stage shows a read-only summary of stages 1-3 above the readiness panel and the action bar. Persistence: last stage per project in localStorage (try/catch), `#stage=<name>` deep link wins, first visit starts at the first incomplete stage. `window.analysisStages = {goTo(name), current(), isValid(name)}` for tests.

- [ ] **Step 1: Failing browser tests:** initial stage is the first incomplete one; only the current stage's `[data-stage]` elements are visible, the others `hidden` (assert via `is_visible`), all ids still exist in the DOM (the 43 globals test keeps passing); Next blocked with the reason text until fields are set, then enabled; Back works; clicking a visited stage jumps; last stage remembered across reload; deep link `#stage=model`; summary text updates when a field changes; Run controls (`#btn-save-start`, terminal, readiness panel) are only visible in the run stage; localStorage failure does not break the page (patch `Storage.prototype.getItem` to throw).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** the template attributes, the strip markup (accessible labels, buttons `type="button"`), `analysis_stages.js` (classic script; register in the template's script loop; does not depend on `analysis_stepper.js`, which is removed together with its markup and any references/tests), and `go_to_stage` in `tests/browser_support.py`. Update every existing browser test that clicks/reads now-hidden elements to call `go_to_stage` first (`tests/test_analysis_page_browser.py`, `tests/test_preflight_browser.py`, `tests/test_wizard_browser.py` where it opens the analysis page, `tests/test_transformer_handoff_browser.py`, `tests/test_new_features.py` if affected). Do not weaken any assertion.
- [ ] **Step 4: Run** `.bidspm/bin/python -m pytest -q tests/test_analysis_stages_browser.py tests/test_analysis_page_browser.py tests/test_preflight_browser.py tests/test_transformer_handoff_browser.py tests/test_transformer_builder_browser.py tests/test_web_routes.py` -> PASS (browser tests running). **Step 5: Commit** `feat(analysis): stage-based page (Folders, Model, Options, Review and run)`.

---

### Task 6: Model wizard stepper

**Files:** Modify `templates/model_wizard.html`, `static/js/model_wizard.js`, `tests/test_wizard_browser.py`.

**Interfaces:** steps `task`, `recipes`, `nuisance`, `contrasts`, `review`. One step visible at a time; strip with done/current/upcoming + one-line summary per finished step; `#wiz-back`/`#wiz-next`; a right-hand rail `#wiz-rail` with the live preview (regressors, contrasts, warnings) visible on every step; existing element ids that tests use are preserved where the element still exists (`#wiz-task`, `#wiz-conditions`, `#wiz-recipes`, `#wiz-nuisance`, `#wiz-nuisance-custom`, `#wiz-auto-contrasts`, `#wiz-pair-table`, `#wiz-add-pair`, `#wiz-name`, `#wiz-save-path`, `#wiz-save`, `#wiz-error`, `#wiz-review`). Recipes step: a gallery of cards `#wiz-gallery .wiz-card[data-recipe=<id>]` (title + one-line description from the catalog); clicking a card adds the recipe and opens its form (the existing recipe cards with move/remove stay below the gallery as "Your recipes"); empty list shows "No special handling needed"; the old select+button (`#wiz-recipe-add`, `#wiz-add-recipe`) is removed. Nuisance step: radio presets, custom list inside `<details>` "Advanced". Contrasts step: automatic contrasts checkbox on by default, `#wiz-pair-table` inside a collapsed "Add a comparison" disclosure, link to the analysis page contrast builder as before. Next is blocked (with a visible reason in `#wiz-hint`) when the scan failed, no regressor is left, or a recipe is incomplete (reusing the existing completeness logic); Review also shows the model name/save path fields. Keep all earlier hardening: stale-response guards, deferred option refresh, XSS discipline, scan error handling, double-save protection, the 409 flow.

- [ ] **Step 1: Failing browser tests:** only one step visible at a time; Next gating reasons (incomplete recipe, no regressors); gallery adds a recipe and opens its form; empty recipes message; summaries on the strip; rail updates after each change and stays visible across steps; advanced disclosures collapsed by default and the custom nuisance list still works when opened; every existing wizard test updated minimally (navigate to the right step first; assert the same behaviours).
- [ ] **Step 2-5:** implement; keep `model_wizard.js` under ~450 lines (stop with DONE_WITH_CONCERNS if it needs more and say what to split); run `tests/test_wizard_browser.py tests/test_wizard_route.py tests/test_analysis_page_browser.py`; commit `feat(wizard): one-step-at-a-time stepper, recipe gallery, summary rail`.

---

### Task 7: Wizard review uses the live readiness panel

**Files:** Modify `static/js/model_wizard.js`, `templates/model_wizard.html` (load `readiness_panel.js`), `tests/test_wizard_browser.py`.

**Interfaces:** the review step's "Check readiness" button calls `ReadinessPanel.run({target: #wiz-readiness, body: {config: {BIDS_DIR, FMRIPREP_DIR, SPACE, TASKS: [task]}, model_json: <model from the last successful build>, validator: "skip", actions: ["stats"]}})` (the dataset validator is not model-related and stays off here, as in `_preflight` today); the build response's synchronous `preflight` stays for Save. A model edit after a finished check marks the panel "out of date" (muted note) until re-run. Cancel works. If no successful build exists yet, the button is disabled with a reason.

- [ ] **Step 1: Failing browser tests** (mock start/stream like Task 4; also one real end-to-end test against the real server on the synthetic tree: click Check readiness, wait for the verdict, assert a `ready`/`warnings` verdict and that the request body contained `model_json` equal to the preview's model).
- [ ] **Step 2-5:** implement; run the wizard + panel browser tests; commit `feat(wizard): live readiness check in the review step`.

---

### Task 8: Docs, real-data check, review, wrap-up

**Files:** Modify `README.md`.

- [ ] **Step 1:** README: stage-based analysis page (the four stages, Next gating, deep link `#stage=...`), wizard stepper, readiness progress (phases, cancel, `--progress` on the CLI, `/run` reuse window of 10 minutes and its limit), and update the preflight timing note (3 s / 17 s on a 100-subject study).
- [ ] **Step 2:** Full suite `.bidspm/bin/python -m pytest -q tests -rs`; browser tests must run.
- [ ] **Step 3:** Real-data checks (read-only, no containers): (a) `python bidspm.py --preflight --progress --skip-validator -s <study 141 export>`: stderr progress lines (count == subjects), stdout pure JSON; (b) start a real job through the Flask test client or a live server on study 141 with the default validator, read the SSE stream and report the event timeline (first event latency, validator done time, per-subject steady rate), then cancel a second job midway and report that it stops promptly; (c) drive the real analysis page and the wizard in headless Chromium on study 141 (project with the real folders; scratch copy of the project config): stage flow end to end, readiness progress visible, no console errors; report anything surprising.
- [ ] **Step 4:** `/ponytail:ponytail-review` on `git diff main...HEAD`; resolve or consciously defer each finding.
- [ ] **Step 5:** superpowers:verification-before-completion, then superpowers:finishing-a-development-branch. Do not merge without the user's go-ahead.
