# Roadmap — Model-variant output separation & Bayesian Model Selection (BMS)

Two related workstreams. **A** fixes the silent-overwrite problem where nuisance-regressor
variants collide in the same output folder. **B** adds a BMS pipeline that compares those
variants. B depends on A: BMS is only meaningful once competing variants land in distinct
folders with distinct `SPM.mat` files.

---

## Background — how the output path is actually built

- The folder `sub-X/task-T_space-S_FWHM-F_node-N` is produced by **upstream** bidspm's
  `getFFXdir(subLabel, opt)`, source confirmed at
  `/data/local/container/bidspm/bidspm/src/stats/subject_level/getFFXdir.m` (v4.0.0, the
  version behind `/data/local/container/bidspm/bidspm_4.0.0.sif`), called from
  [setBatchEstimateModel.m:39](../bidspm_overrides/src/batches/stats/setBatchEstimateModel.m#L39).
- The `node-N` segment is the smdl.json **root node's** `Name` field — **but with a special
  case** (`getFFXdir.m:29-32`):

  ```matlab
  nodeNameLabel = regexprep(nodeName, '[ -_]', '');
  if ~isempty(nodeNameLabel) && ~ismember(nodeNameLabel, {'runlevel', 'run'})
    glmDirName = [glmDirName, '_node-', bids.internal.camel_case(nodeName)];
  end
  ```

  If the root node's name — after stripping spaces/hyphens/underscores — equals `"runlevel"`
  or `"run"`, **no `_node-` suffix is added at all.** This is a deliberate default-name
  omission, not a bug in bidspm itself.
- This Python wrapper never *builds* that path — it only *reads* it to check completion at
  [core.py:726](../lib/core.py#L726): `f"task-{task}_space-{config.SPACE}_FWHM-{config.FWHM}_node-*"`,
  which silently **never matches** for projects whose root node is named `run_level`/`Run`
  (see project 141 below) — every "already processed" check fails open, so stats always
  re-runs even when nothing changed. This is what A2 needs to guard against.
- **Confirmed collision (project 141):** all four competing model files
  (`studies/141.json`, `141_new.json`, `141_fix.json`, `141_fix_pmod.json`) used the exact
  same task (`crom`) **and** the exact same Run-level node name `"run_level"` — which hits the
  omission rule above. All four wrote to the *unsuffixed* folder
  `sub-X/task-crom_space-MNI152NLin2009cAsym_FWHM-{6,9}` with zero folder-level distinction,
  so whichever ran last silently overwrote the others' `SPM.mat`/betas/contrasts. This matches
  the exact path the user reported.
- The top-level smdl.json `"Name"` (e.g. `"crom"`, `"default-model"`) is used only for
  logging/error messages and is never threaded into the output path.
- An **unused** mechanism already exists: `addConfoundsToDesignMatrix` in
  `bidspm_overrides/src/bids_model/BidsModel.m` (~L426–574) has an `updateName` option
  (default `false`) whose `appendSuffixToNodeName` (~L758) appends
  `rp-{motion}_scrub-{scrub}_tissue-{wm_csf}_nsso-{nonSteadyState}` to the node name. If
  turned on, it auto-derives a distinct `node-` folder per confound strategy — though note it
  would still need to avoid landing back on `"runlevel"`/`"run"` after stripping.
- **Other latent risk found:** `studies/132/model_al_ses.json` also names its Run-level root
  node `"Run"`, which hits the same omission. It doesn't currently collide with anything
  (the other 132 model files use `"subject_level"`, which does get suffixed), but it's one
  future variant away from silently repeating this bug. Not changed yet — flagging only.

---

## Workstream A — separate model variants in the output

### A1. Immediate mitigation (no code) ✅ DONE
Renamed the Run-level `Nodes[].Name` in each of project 141's four competing model files to a
distinct, non-`{run,runlevel}` value, so each now gets its own `_node-<Name>` folder:

| File | Old name | New name | What distinguishes it |
|---|---|---|---|
| `studies/141.json` | `run_level` | `default` | intercept-only (`X: [1]`), v4-compatible default |
| `studies/141_new.json` | `run_level` | `eventsAuto` | trial-type events only, no motion regressors, auto-generated from events files |
| `studies/141_fix.json` | `run_level` | `simple` | `valid_item.item` + trial-type subset + wildcard motion (`trans_*`, `rot_*`) — currently the active model per `config/run_settings_override_0ad37d4aa9d6cf13.json` |
| `studies/141_fix_pmod.json` | `run_level` | `pmod` | same as `simple` but with parametric modulation of `valid_item.item` by `ai_rating`, explicit motion regressor names |

Going forward, running any of these four will produce e.g.
`sub-X/task-crom_space-MNI152NLin2009cAsym_FWHM-6_node-Default/`,
`..._node-EventsAuto/`, `..._node-Simple/`, `..._node-Pmod/` (exact casing depends on
`bids.internal.camel_case`) — no more collisions between them.

**Important caveat:** this does *not* recover past results. The existing unsuffixed
`task-crom_space-..._FWHM-{6,9}` folders on disk contain whatever combination of these four
variants happened to run last — there's no way to tell which files belong to which model
after the fact. If clean per-variant results are needed, re-run `stats` for task `crom` for
project 141 now that the folders are separated (existing unsuffixed folders are left
untouched and simply won't be touched or matched by future runs).

- Files changed: `studies/141.json`, `studies/141_new.json`, `studies/141_fix.json`,
  `studies/141_fix_pmod.json` (not git-tracked — `studies/` is gitignored, so these are local
  edits only).
- Risk: none to existing data (old folders untouched); reversible.

### A2. Overwrite guardrail (Python)
Make the wrapper refuse to silently clobber an existing variant.
- In `check_subject_processed` ([core.py:710](../lib/core.py#L710)) and the pre-run gate in
  `run()` (~[core.py:1411](../lib/core.py#L1411)), resolve the *expected* node name from the
  selected model file and warn/skip (unless `--force`) when a `node-<thatname>` folder with
  `beta_*.nii` already exists.
- Add a validation check that flags when two model files in a project share task/space/FWHM
  **and** node Name (extend the `validate_bids_model` semantic checks around
  [core.py:839](../lib/core.py#L839)).

### A3. Auto-suffix from confound strategy (MATLAB, optional)
Wire up the existing `updateName` path so users don't hand-name every variant.
- Set `updateName=true` where `addConfoundsToDesignMatrix` is invoked in
  `bidspm_overrides/src/bids_model/BidsModel.m`, gated by a new opt/flag so it's opt-in.
- Surface as a CLI flag (e.g. `--name-by-confounds`) plumbed like the existing `node_name`
  option ([core.py:1526](../lib/core.py#L1526), [core.py:1561](../lib/core.py#L1561),
  [core.py:1650](../lib/core.py#L1650)).
- Update `check_subject_processed` glob to tolerate the suffixed names.

### A4. Webapp UX (optional)
Expose a "variant label" field in the run form that maps to the node Name / `--node-name`
already accepted at [web_execution_api.py:181](../webapp/web_execution_api.py#L181), and show
the resolved output folder in the run summary.

---

## Workstream B — BMS pipeline ✅ DONE (container mode)

**Correction to the original plan below:** bidspm v4.0.0 does **not** need a from-scratch
Bayesian-estimation branch or a new BMS batch script — the whole workflow (cross-validated
first-level BMS via the bundled **MACS toolbox**, matching the linked demo) already ships in
`src/workflows/stats/bidsModelSelection.m`, and MACS itself is already installed inside the
container image at `/opt/spm12/toolbox/MACS` (confirmed via `apptainer exec ... ls
/opt/spm12/toolbox/MACS`). The real work turned out to be wrapper plumbing plus two genuine
upstream bugs blocking that path — both confirmed live against the actual container and fixed
via the existing `bidspm_overrides/` mechanism.

**Decisions locked in (2026-07-08):** first-level BMS now, group-level BMS as a later
follow-on (Workstream C, not started); Bayesian/cvLME estimation runs as its own **separate,
opt-in pass** — it does not touch or replace the existing Classical `stats` estimation.

### What BMS actually needs, end to end
1. `stats` already run (Classical estimation) for **every** competing model — each with a
   distinct root-node `Name` so they don't collide (Workstream A).
2. Each competing model's `Input` must declare the **same `space`** (not just `task`) — see
   `checks()` in `bidsModelSelection.m`. Added `"space": "MNI152NLin2009cAsym"` to all four
   project-141 model files' `Input` blocks (small, user-approved edit distinct from A1's
   renaming).
3. A dedicated directory containing **only** the competing models, each named with a
   **`_smdl.json` suffix** — `getOptionsFromModel.m:18-20` globs exactly
   `spm_select('FPList', opt.toolbox.MACS.model.dir, '.*_smdl.json')`, not `*.json` as
   initially assumed. Created `studies/141_bms_models/` with copies of the four project-141
   models renamed accordingly: `141_default_smdl.json`, `141_eventsAuto_smdl.json`,
   `141_simple_smdl.json`, `141_pmod_smdl.json`.
   **Known drift risk:** these are copies, not symlinks/generated — editing the originals in
   `studies/*.json` does not update the BMS copies. Fixed properly by B4 below (materialize
   models_dir from a file list at run time instead of maintaining hand-made copies).

### Two upstream bugs found and fixed (confirmed against the real `bidspm_4.0.0.sif`)
1. **The container's `bidspm` CLI outright refuses `bms`.** `bidspm/src/bidspm/cli.py` has
   `NOT_IMPLEMENTED = {"bms", "bms-posterior", "bms-bms", "copy", "specify_only"}` — even
   though `generate_command_bms()` and the MATLAB-side dispatch are both fully implemented.
   Running `bidspm /raw /derivatives subject bms --models_dir ...` always errors `"The action
   'bms' is not yet implemented."` regardless of arguments. **Fix:** bypass the Python CLI
   entirely and call the MATLAB `bidspm(...)` function directly via `octave --eval`, the same
   way this wrapper's local (non-container) execution mode already invokes bidspm for
   smooth/stats/dataset. No override file needed for this one — it's just a different
   invocation shape from our side (see B3).
2. **`cliBayesModel.m` calls that only work under licensed MATLAB, not Octave.**
   `bidsModelSelection(opt, 'action', 'all')` — `bidsModelSelection.m`'s own `inputParser`
   registers `'action'` via `addOptional` (positional), not `addParameter` (name-value).
   Octave's `inputParser` enforces this strictly (`argument 'ACTION' is not a valid
   parameter`); MATLAB's apparently doesn't. **Fix:** override
   `bidspm_overrides/src/cli/cliBayesModel.m` to call `bidsModelSelection(opt, 'all')`
   positionally (verified isolated in plain Octave: name-value form fails, positional
   succeeds).
3. **Dead-code crash in `bidsModelSelection.m`'s `checks()`.** Line 322 correctly builds
   `space = cellfun(@(x) x.space, inputs, 'UniformOutput', false)`, then lines 323-325
   unconditionally redo it *without* `'UniformOutput', false` (the `if iscell(space)` guard is
   always true right after the first call, so this branch always runs) — crashes with
   `cellfun: all values must be scalars when UniformOutput = true` for any `space` value
   longer than one character, i.e. always, for real space labels like
   `MNI152NLin2009cAsym`. **Fix:** override
   `bidspm_overrides/src/workflows/stats/bidsModelSelection.m`, deleting the redundant
   re-assignment (the first call's cellstr output already works fine with `unique()`).

Both overrides are mounted unconditionally in `build_docker_command`/`build_apptainer_command`
(harmless for non-BMS actions), same list as the existing `Factor.m`/`BidsModel.m`/etc.
overrides in [lib/core.py](../lib/core.py).

**Verified:** with both overrides applied, `bidspm(..., 'action','bms', 'models_dir',
'/models/bms_models', 'dry_run', true)` run for real inside `bidspm_4.0.0.sif` reaches
`********* Pipeline done :) *********`, correctly iterating all subjects × all four
(now-distinctly-named) models and looking for `SPM.mat` at exactly the `_node-<Name>` paths
Workstream A produces. It reports "Could not find a SPM.mat file" for every subject/model —
expected, since `stats` has never been run under the new node names yet (only the old,
overwritten unsuffixed folder has real data). Re-run `stats` per model (per A1's caveat)
before running `bms` for real.

### B1. `resolve_models_dir()` + `run_bms()` (Python, `lib/core.py`) ✅ DONE
- `resolve_models_dir(models_dir)`: validates the directory exists and contains ≥2
  `*_smdl.json` files.
- `run_bms(config_file, container_config_file, models_dir, fwhm=None,
  participant_label=None, dry_run=False, skip_validation=False, on_progress=None)`:
  loads config/container config, resolves the models-dir container mount (reusing the same
  relative-to-`DERIVATIVES_DIR` vs. dedicated-bind logic as the existing single-file
  `--model` mount), builds a direct `octave --eval "bidspm('init'); try; bidspm(...); catch
  ...; end;"` call via the new `override_entrypoint` param (see B2), and runs it. Container
  execution only — no local/Octave-on-host path implemented (not needed for this project's
  setup, which uses apptainer).
- Exported from `lib/__init__.py`.

### B2. `override_entrypoint` param on the container builders ✅ DONE
`build_docker_command` / `build_apptainer_command` / `build_container_command` in
[lib/core.py](../lib/core.py) gained an `override_entrypoint: Optional[List[str]] = None`
parameter. When set, it replaces the normal `exec bidspm <args>` final command with an
arbitrary one (the `octave --eval ...` call for BMS) while still setting up every bind mount,
override file, and env var exactly as for `stats`/`dataset`. All existing call sites are
unaffected (parameter defaults to `None`).

### B3. CLI wiring (`bidspm.py`) ✅ DONE
- Added `'bms'` to `--action` choices and a `--models-dir` flag.
- `bms` is stripped out of the per-subject/task `Pipeline` loop before construction (same
  precedent as `report` — neither fits that loop: report is pure Python with no MATLAB call,
  bms compares already-estimated models across a directory rather than looping subjects/tasks
  against one model file).
- New `_handle_bms(config_file, args)` calls `run_bms(...)` and prints result/errors; wired to
  run standalone (`--action bms` alone) or after the main pipeline finishes if combined with
  smooth/stats/dataset (mirrors the `report` post-pipeline hook).
- `estimate_processing_time` ([core.py](../lib/core.py)) got a `"bms": 20`-min-per-task entry
  and a guard against unknown actions (pre-existing gap: `report` already had no entry and
  would `KeyError` — not fixed here, out of scope, but `bms` doesn't repeat it).

**Verified end to end**: `python3 bidspm.py --settings
config/run_settings_override_0ad37d4aa9d6cf13.json --action bms --models-dir
studies/141_bms_models --dry-run` builds the exact command validated by hand above and
reports success. Missing `--models-dir` and a directory with 0 matching files both fail with
clear messages.

### B4. Fix the model-copy drift risk + webapp integration (not started)
- Replace the hand-maintained `studies/141_bms_models/` copy approach with either: (a) a
  `--models` flag taking explicit file paths that `run_bms` materializes into a temp dir with
  the `_smdl.json` suffix at run time, or (b) a documented convention that the BMS models dir
  is the source of truth and `studies/*.json` are edited there directly. (a) is safer against
  drift; worth deciding before this gets used on a second project.
- Webapp: add a BMS mode to the run form (multi-select model variants), wire through
  `web_execution_api.py` like the other flags; add a results view for the posterior/
  exceedance-probability maps `bidsModelSelection.m` produces under
  `bidspm-modelSelection/group/`.

---

## Workstream C — group-level (random-effects) BMS (not started)

Deferred per the 2026-07-08 decision. Needs first-level BMS (Workstream B) validated with real
data first. Revisit scope once B has been run on actual re-estimated `stats` outputs.

---

## Suggested order (updated)

1. **A1** — rename nodes ✅ done.
2. Add `Input.space` to competing models ✅ done.
3. **B1-B3** — BMS wrapper plumbing + two upstream-bug overrides ✅ done, dry-run verified
   against the real container.
4. **Re-run `stats`** for project 141's four models under their new node names (needed before
   a *real*, non-dry-run `bms` call has any `SPM.mat` files to compare).
5. **A2** — overwrite guardrail (stops this class of bug recurring for future projects).
6. **B4** — fix model-copy drift, webapp integration.
7. **A3, A4** — ergonomics, as time allows.
8. **Workstream C** — group-level BMS, once B is validated on real data.
