# bidspm_overrides

This directory mirrors the directory tree of upstream `bidspm` (as installed at
`/home/neuro/bidspm` inside the container image) and contains locally-patched
files that fix real bugs in the upstream `v4.0.0` release used by
`containers/dockerfile/dockerfile`.

The Dockerfile bakes these in at build time with a single recursive
`COPY bidspm_overrides/ /home/neuro/bidspm/`, so the built image is
self-contained — no runtime bind-mounts or patching steps are needed to get
correct behavior.

## Per-file rationale

- **Factor.m**: adds cross-product support for multi-column input.
- **validateContrasts.m**: adds missing cell-array guard (container v4.0.0 bug).
- **setBatchSubjectLevelContrasts.m**: coerces cell→struct before validate call.
- **return_file_index.m**: suppresses benign warnings for fMRIPrep 'figures' QC files.
- **Filter.m / get_input.m / check_field.m / identify_rows.m**: ensure the full
  transformer chain uses our local versions so Filter + Factor work end-to-end.
- **BidsModel.m**: fixes cellfun crash in validateConstrasts — Octave cannot use
  `x == 1` to test for the intercept when x is a multi-char string.
- **setBatchEstimateModel.m**: fixes `for j = 1:size(contrastsList)` (container
  v4.0.0 bug) which should be `1:numel(contrastsList)` — size() on a cellstr
  returns a dimension vector, not a count, so the group-level GLM estimate
  batch silently ended up empty.
- **getDummyContrastFromParentNode.m**: the Run-level base case returned {}
  instead of falling back to that node's HRF Variables, so any dataset/subject
  node relying on inherited (un-named) DummyContrasts resolved to an empty
  contrast list and the group-level GLM batch was silently skipped with no
  error.
- **getRegressorIdx.m**: adds support for a 'condition:pmodName^order' syntax
  in Contrasts/ConditionList so explicit contrasts can target a parametric
  modulation term (e.g. valid_item.item:ai_rating_mod^1), not just a
  condition's unmodulated main effect.
- **cliBayesModel.m**: container v4.0.0 bug — calls bidsModelSelection(opt,
  'action', <value>) but bidsModelSelection's inputParser registers 'action'
  via addOptional (positional), not addParameter. GNU Octave's inputParser
  enforces this strictly and errors with "argument 'ACTION' is not a valid
  parameter"; MATLAB's is lenient. Calls positionally instead, which works on
  both.
- **bidsModelSelection.m**: container v4.0.0 bug in checks() — unconditionally
  redid a cellfun(@(x) x.space, inputs) call without 'UniformOutput', false
  right after computing it correctly, which crashes with "cellfun: all values
  must be scalars when UniformOutput = true" for any space value longer than
  one character (i.e. always, for real space labels like
  'MNI152NLin2009cAsym'). Also adds an env-var-driven output-dir override
  (`BIDSPM_BMS_WORKER_ID`) so concurrent cvLME workers don't race on a shared
  `group/MS.mat` path.
- **copyAtlasToSpmDir.m**: container v4.0.0 bug — the "is this atlas already
  cached" check does exist(targetAtlasImage(1:end-3), 'file'), assuming the
  target always ends in '.gz' (true only for 'aal'). For
  'hcpex'/'glasser'/'visfatlas'/'wang' the target is already a plain .nii
  path, so stripping the last 3 chars chops "nii" instead and checks for a
  file that can never exist — atlasPresent was therefore always false for
  those 4 atlases, forcing every invocation to unconditionally re-copy (and
  for 'wang', re-merge and delete its source) regardless of whether it was
  already cached. Confirmed live: this is what caused concurrent
  stats-workers to race on the shared atlas cache/source dirs ("copyfile: no
  files to move", "delete: no such file"). Only strip '.gz' when the target
  path actually has it.
- **allowed_actions.json**: keeps the CLI's list of allowed actions in sync
  with the workflows added/patched above (e.g. BMS actions).

## Adding a new override

Add the patched file at the same relative path under this directory (mirroring
its location under upstream bidspm's root), document the rationale above, and
rebuild the image — no other wiring is required.
