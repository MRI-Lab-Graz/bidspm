# Opt-in SPM-standalone estimation for subject-level stats

Date: 2026-10-13 · Branch: `spm26-octave-upgrade` · Status: **approved with decisions below (2026-10-13)**

## Problem

On long scans (study 141: 1006 volumes, one run) a subject takes ~1970 s end to end, of which
~1900 s (97 %) is SPM's `spm_spm` model estimation running under Octave on one core. bidspm's
own overhead is ~30 s. We do not want to modify `spm_spm`.

## Evidence (spikes, 2026-10-13, study 141 subject 141A332C)

| Step | Engine | Time |
|---|---|---|
| design (specify) | Octave bidspm | ~50 s |
| estimation | SPM standalone, `ghcr.io/spm/spm-docker:docker-matlab-latest` | 327 s (exit 0) |
| contrasts | Octave bidspm on the MATLAB-written `SPM.mat` | 22 s, 14 con + 14 spmT, 0 log problems |
| all-Octave reference | Octave | 1871-1969 s |

* Standalone vs Octave estimation: 15 files (13 betas, ResMS, RPV) r = 1.00000000, max rel diff 2.4e-8,
  mask identical (223 198 voxels); contrasts/T-maps max rel diff 3.2e-8.
* 4 standalone containers in parallel: 346-378 s each, all exit 0, all outputs identical.
* The standalone is compiled `-singleCompThread` (SPM docs), so the gain is MATLAB's interpreter/BLAS,
  not threads; parallelism comes from more processes.
* Standalone has only core toolboxes (SPM docs): the MACS toolbox (BMS) is **not** available there.

## Design

### Scope
* New option `estimation_engine` ∈ {`octave` (default), `standalone`}; applies only to
  `--action stats` at **subject level**. Dataset level, BMS, ROI-based GLM, smoothing, report: unchanged.
* Opt-in. Nothing changes for users who do not set it.

### Flow per subject (`standalone`)
1. **design** — Octave bidspm container, action `stats` with `--design_only`
   (specifies the model, writes `SPM.mat`, confounds, onsets, scrubbing stats; no estimation).
2. **estimate** — official SPM container runs a generated `job.m`
   (`spm.stats.fmri_est.spmmat = {…/SPM.mat}`, then `exit`) for every `SPM.mat` the design step wrote.
3. **contrasts** — Octave bidspm container, action `contrasts` (plus Results export only if
   `--results`/report, as today).
Steps share the same `/raw`, `/derivatives`, `/fmriprep` mount layout so absolute paths inside
`SPM.mat` stay valid. Any step failing marks the subject failed (existing summary/`--force` semantics).

### Required bidspm fix (override)
`cliStats.m` v4.0.0 runs `opt = rmfield(opt, 'model')` at the top of the model loop, which drops
`opt.model.designOnly`, so `--design_only` never stops before estimation. Override: read the flag
before the loop and set `estimate = false` when it is true. (Verified in a real run: the profiling
run of `--design_only` went on to "Model estimation".)

### Components
* `PipelineOptions.estimation_engine`; CLI `--estimation-engine {octave,standalone}`; GUI select
  "Estimation engine" next to Parallel subjects, **always shown**, with a hint (≈5× faster on long scans; needs an
  SPM standalone image that you provide, see README) and a field for the image name.
* `ContainerConfig`: `spm_standalone_image` (Docker) and `spm_standalone_sif` (Apptainer). **No default:
  the user supplies the image** and pins it by digest (`name@sha256:…`) or local tag. We ship no image.
* `lib/core.py`: `build_spm_standalone_command(...)` (Docker + Apptainer; env `MCR_INHIBIT_CTF_LOCK=1`,
  `SPM_HTML_BROWSER=0`, `HOME=/tmp`, `--user <host uid>`), `_write_estimation_job(spm_mats, dir)`,
  `_find_new_spm_mats(...)` (SPM.mat files under the subject's stats dir for this task/space/FWHM modified by
  the design step), and the 3-step branch in `_process_subject`.
* Preflight: when the engine is `standalone`, check the configured image exists locally (Docker:
  `docker image inspect`; Apptainer: SIF file) **before** processing any subject. If the setting is empty or
  the image is missing: stop with an error that says how to get/build one (see "Providing the image"); no
  auto-pull and **no silent fallback** to Octave. Log the image id/digest once per run.
* Worker suggestion keeps the 4 GB/worker assumption until standalone memory is measured (next spike).

### Non-goals (YAGNI)
Auto-choosing the engine, standalone for BMS/dataset level, installing the MATLAB Runtime ourselves,
patching `spm_spm`, publishing the SPM image.

## Testing (TDD)
Unit (no containers): command builders for both runtimes (env, user, mounts, `batch /job/job.m`); job-file
generator (paths, trailing `exit`); `SPM.mat` discovery (task/space/FWHM filter, mtime); orchestration with
mocked `run_command` (3 calls in order; subject fails if step N fails; steps 2-3 skipped on failure; engine
`octave` still makes exactly one call); CLI flag; `/run` pass-through; GUI select defaults to octave;
preflight error when image missing. Host-Octave test for the `cliStats` designOnly fix where stubbable, else
covered by the e2e check. Opt-in e2e (`BIDSPM_TEST_ENGINE=standalone`): 132 subject, compare betas/contrasts
against the Octave engine (r ≥ 0.9999) and run `scripts/check_run_log.py`.

## Acceptance
* 141 subject: total ≤ 8 min with `standalone` (all-Octave ≈ 33 min), results identical to Octave engine
  (r ≥ 0.9999999, max rel diff ≤ 1e-6), log scan 0 problems.
* 4 subjects in parallel with `standalone` finish in < 1.3 × single-subject time.
* `octave` engine unchanged: existing tests pass; 132 end-to-end still ~113 s.

## Decisions (from review)
1. **Pin by digest**: `spm_standalone_image` is expected as `name@sha256:…` (a local tag is accepted); the digest is logged.
2. **SPM 26 everywhere**: the standalone image must be SPM 26.x. The official `latest` (SPM 25) is not used. No SPM 26
   image is published yet (26.10.01 released 2026-10-13), so users build one from SPM's recipe.
3. **Measure standalone memory per worker** before changing the 4 GB/worker suggestion (next spike).
4. **Apptainer SIF cache**: later.
5. **No gating, user-provided image**: the engine option is always visible; the image comes from the user.

## Providing the image (goes into the README)
```
git clone https://github.com/spm/spm-docker && cd spm-docker/matlab
docker build -t spm-standalone:26.10.01 \
  --build-arg MATLAB_VERSION=R2026a --build-arg SPM_RELEASE=26.10 --build-arg SPM_REVISION=01 .
docker inspect --format '{{index .RepoDigests 0}}{{.Id}}' spm-standalone:26.10.01   # pin this in container.json
```
(`R2026a` is what the SPM 26.10.01 standalone's runtime installer expects; builds the MATLAB Runtime, ~4 GB.
Building accepts the MathWorks MATLAB Runtime license via `AGREE_TO_MATLAB_RUNTIME_LICENSE`.)
