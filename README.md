# BIDSPM Runner

A Python-based tool for running BIDS-StatsModel pipelines via containers (Docker or Apptainer) without requiring MATLAB.

## Overview

BIDSPM Runner enables neuroimaging data analysis using the bidspm framework by leveraging containerized environments. The tool supports both Docker and Apptainer and can automatically perform smoothing and statistical analyses on BIDS-compliant datasets.

**New here? Follow the [student walkthrough](docs/walkthrough.md)** (install, wizard, readiness check, run, results, with screenshots).

## Features

- 🐳 **Container Support**: Works with Docker and Apptainer with enhanced security
- 📊 **BIDS Compatibility**: Full support for BIDS-StatsModel schema
- 🔧 **Flexible Configuration**: JSON-based configuration for easy customization
- 📝 **Logging**: Detailed logging of all processing steps with configurable verbosity
- ✅ **Validation**: Automatic validation of BIDS-StatsModel files and SPACE compatibility
- 🚀 **Batch Processing**: Processing of multiple subjects and tasks
- 🧪 **Pilot Mode**: Test configuration with one random subject
- 🛡️ **Container Security**: Uses `--containall` and `--writable-tmpfs` for Apptainer isolation
- 🗂️ **Tmp Management**: Automatic creation and cleanup of run-specific temporary directories
- 🌍 **SPACE Validation**: Validates spatial reference spaces exist in fMRIPrep data
- 🔄 **Error Recovery**: Non-fatal error handling allows processing to continue
- 🧾 **Licence-clean image**: the `spm-bids-runner` image ships only free/open-source components (no atlases; see Atlases)

## Repository layout

- `bidspm.py` – primary entry point for all container workflows
- `bidspm_overrides/` – locally-patched upstream bidspm files, baked into the Docker
  image at build time (see `bidspm_overrides/README.md` for what's patched and why)
- `containers/dockerfile/` – the Dockerfile and build scripts for the bidspm image
- `lib/spm_standalone.py` – optional estimation in SPM's compiled standalone (see below)
- `scripts/` – helper utilities (environment activation, setup, wrapper scripts); `scripts/check_run_log.py` fails on any unexpected error or warning in a run log
- `logs/` – auto-generated run logs (e.g., `run_bidspm.log`, `model_*_timestamp.log`)
- `tests/` – automated tests for API and feature behavior
- `docs/repository_notes.md` – engineering notes (OO direction and test policy)

## ⚠️ Known Issues

- **The image runs SPM 26.10.01 on GNU Octave 9.4, with bidspm v4.0.0** (which was written for SPM12). SPM does not
  officially support Octave; this setup is tested here (results match SPM12 to r ≥ 0.99996 on first-level stats, and
  match SPM's own MATLAB-Runtime standalone to 1e-8). bidspm's lab patches live in `bidspm_overrides/`.
- **Rebuild the image after every `git pull`** that touches `bidspm_overrides/` or `containers/dockerfile/`:
  the patches are baked in at build time, so an old image silently lacks newer fixes
  (`docker build -f containers/dockerfile/dockerfile -t ghcr.io/mri-lab-graz/spm-bids-runner:latest .`).
- **The image is called `spm-bids-runner`** (`ghcr.io/mri-lab-graz/spm-bids-runner:latest`), not bidspm: it packages other people's software
  (bidspm, SPM, GNU Octave; credits and licences in `/usr/share/doc/spm-bids-runner/NOTICE` inside the image and in
  `docs/third-party-licenses.md`). Until it is published on GHCR, build it locally (Installation). The older
  SPM12-era image named `bidspm` in the same GHCR organisation does not match this code; do not use it. Projects saved
  with an old image name keep it (nothing is rewritten); the readiness check reports `image_missing` when that image
  is not on the machine.
- **No atlases in the image** (licence reasons): results tables are not labelled with brain regions, and bidspm's ROI
  features need an atlas you add yourself (see Atlases).
- "Slice timing information was missing" in a stats log is expected for fMRIPrep input: fMRIPrep drops `SliceTiming`
  after correcting and records `StartTime`, which is used for SPM's `fmri_t0`.

## 🌍 Multi-Platform Support

The tool automatically detects your platform and selects the appropriate container runtime:

### 🖥️ **macOS (Development/Piloting)**

- **Auto-detected**: Docker (Apptainer not supported on macOS)
- **Container**: `containers/container.json` (Docker configuration)
- **Usage**: Perfect for testing and piloting analyses

### 🐧 **Linux (Production/HPC)**

- **Auto-detected**: Apptainer (preferred) or Docker
- **Container**: `containers/container_apptainer.json` (Apptainer) or `containers/container.json` (Docker)
- **Usage**: Production runs on high-performance computing systems

### 🚀 **Quick Platform Setup**

```bash
python bidspm.py --pilot  # Automatically selects the right container
```

### 📁 **Container Configuration Files**

The tool supports multiple container configurations:

- `containers/container.json` - Docker for macOS/development
- `containers/container_apptainer.json` - Apptainer for Linux/HPC

Which one a run uses: a `--container` file wins; otherwise the `container_type` / `docker_image` / `apptainer_image` / `spm_standalone_image` keys of the run settings (the GUI project's container settings); otherwise the platform auto-detect picks one of these files.

**Example Docker config (macOS):**
```json
{
  "container_type": "docker",
  "docker_image": "ghcr.io/mri-lab-graz/spm-bids-runner:latest",
  "apptainer_image": ""
}
```

**Example Apptainer config (Linux):**
```json
{
  "container_type": "apptainer", 
  "docker_image": "",
  "apptainer_image": "/path/to/bidspm.sif"
}
```

## Prerequisites

- No Python needed: `scripts/setup.sh` makes uv download its own Python 3.12 (internet access is needed for the first setup)
- Docker (your user in the `docker` group) or Apptainer
- Disk: about 3.5 GB for the image plus 0.7 GB for the Python environment
- BIDS-compliant dataset
- Preprocessed fMRI data (e.g., from fMRIPrep)

## Installation

### Install and start (Docker or Apptainer)

This repo is a Python CLI/webapp that drives a Docker (or Apptainer)
container where the actual SPM/Octave analysis runs -- you need both parts. Follow these steps in order:

```bash
git clone https://github.com/MRI-Lab-Graz/bidspm.git
cd bidspm
# get the image, EITHER pull it from GHCR (once it is published there):
#   docker pull ghcr.io/mri-lab-graz/spm-bids-runner:latest
# OR build it from this checkout (SPM 26.10.01 is compiled for Octave during the build;
# versions are build arguments: --build-arg SPM_TAG=26.10.01 --build-arg BIDSPM_TAG=v4.0.0):
docker build -f containers/dockerfile/dockerfile -t ghcr.io/mri-lab-graz/spm-bids-runner:latest .
./scripts/setup.sh        # uv builds .bidspm: its own Python 3.12 (.python-version) + the packages in uv.lock
./scripts/start_gui.sh    # or: .bidspm/bin/python bidspm.py --help
```

(`containers/dockerfile/build_mri_lab_container.sh` wraps the same docker build.) The default
`containers/container.json` already points at `ghcr.io/mri-lab-graz/spm-bids-runner:latest` (the one image-name setting is
`DEFAULT_DOCKER_IMAGE` in `lib/config.py`), so nothing needs editing. A cold build (no cache) took about
5 minutes on the lab server (image 3.4 GB) and needs internet access (Debian, GitHub, PyPI, npm).

`scripts/setup.sh` downloads uv into `./build/uv` with curl (curl and internet access are required; an uv already
installed on the system is not used).

The environment is managed entirely by [uv](https://docs.astral.sh/uv/): dependencies live in `pyproject.toml` and are
locked in `uv.lock`. It uses uv's own Python, never the OS's or FSL's. To change dependencies edit `pyproject.toml`, run
`uv lock`, then `UV_PROJECT_ENVIRONMENT=.bidspm uv sync --managed-python`.

**Starting the GUI:** `./scripts/start_gui.sh` activates the project's `.bidspm` virtual environment and starts it
(port `$BIDSPM_PORT`, default 5100; any options such as `--host` or `--no-browser` are passed on). If an older bidspm GUI
already listens on that port it is stopped and replaced; any other program on the port is left alone and the script exits
with its PID (choose another port: `BIDSPM_PORT=5101 ./scripts/start_gui.sh`). On start the GUI prints a "Pre-flight check"
(a list of what is ready or missing); the same check runs on demand with `python bidspm.py --check-environment`.
There are no web routes for it. A GUI started in the background (`./scripts/start_gui.sh > gui.log 2>&1 &`) ignores Ctrl+C;
stop it with `kill <pid>` (SIGTERM). The GUI listens on `127.0.0.1:5100` only and has no login: do not expose the port.
On a shared server each student runs their own instance on their own port.

**VS Code Remote SSH:** VS Code shows "Your application running on port 5100 is available. Open in Browser" every time.
To open the browser at once instead, add this to the (untracked) `.vscode/settings.json`:
`"remote.portsAttributes": {"5100": {"label": "BIDSPM GUI", "onAutoForward": "openBrowser"}}`.

**On a remote server without a display:** the web GUI starts without opening a browser when it detects an SSH session
(or with `--no-browser`). It listens on `127.0.0.1` only, because it has no login (anyone who can reach the port can run
jobs and read files). Forward the port from your own machine instead of exposing it:
`ssh -L 5100:localhost:5100 you@server`, then open `http://localhost:5100`. Use `--host 0.0.0.0` only on a network you trust.

To activate the environment in your shell: `source ./scripts/activate_bidspm.sh`.

**Environment already set up but broken?** `scripts/setup.sh` writes an
`.install.lock` file after a successful run and skips re-running by default —
so if the `.bidspm` venv later breaks (e.g. its Python interpreter was a
symlink into a system Python that got moved/reinstalled), a plain re-run of
`./scripts/setup.sh` is a silent no-op. Rebuild it with:

```bash
./scripts/setup.sh --force
```

Alternatively, point the GUI/CLI at any working interpreter directly without
touching the venv, via `BIDSPM_PYTHON=/path/to/python python bidspm_gui.py`.

### Manual installation (instead of `scripts/setup.sh`)

```bash
UV_PROJECT_ENVIRONMENT=.bidspm uv sync --managed-python   # needs uv (https://docs.astral.sh/uv/)
source .bidspm/bin/activate
```

## Testing

Run the test suite from repository root:

```bash
.bidspm/bin/python -m pytest -q tests   # pytest, playwright, pandas and coverage are in the uv "dev" group
```

A few tests need extras and skip themselves when they are missing (pandas for `scripts/fix_events_format.py`, GNU Octave on the host
for the `.m` override tests). The image smoke test runs only with `BIDSPM_TEST_IMAGE=<built image>`. `tests/test_analysis_page_browser.py`, `tests/test_transformer_builder_browser.py` and
`tests/test_transformer_handoff_browser.py` (the analysis page <-> transformer builder round trip) open the pages in headless Chromium and need a headless Chromium: run `.bidspm/bin/playwright install chromium` once (about 130 MB). Without it about 200 browser tests skip silently.
The full suite takes about 5 minutes.

Notes:

- Add tests for each new feature under `tests/`.
- Keep tests deterministic and independent from external services.

## Readiness check (preflight)

Before a run, bidspm can check whether the BIDS dataset, the fMRIPrep output and the model fit together. It checks:

- BIDS and fMRIPrep folders exist, have `dataset_description.json` and `sub-*` folders (`bids_dir`, `fmriprep_dir`)
- selected subjects exist in both trees (`subject_missing`); tasks are found (`no_tasks`)
- preprocessed BOLD exists for each task and `SPACE` (`preproc_missing`)
- events files exist, have valid `onset`/`duration` (and `trial_type` if the model uses it), and the model's conditions occur in them
  (`events_missing`, `events_columns`, `events_values`, `events_trial_type`, `condition_missing`, `scan_length` warning)
- confounds files exist and contain the model's nuisance regressors (`confounds_missing`, `confound_columns`)
- the model is valid (`model`), and the chosen container tool is installed (`container`, warning)
- the dataset validator (`validator`)

**Multiple runs.** All runs (and sessions) of a subject/task go into ONE subject-level SPM.mat, one SPM session per run
(own constant, motion regressors and conditions). Subject-level t contrasts AVERAGE each condition over the runs that contain it
(weights `1/n` per run, SPM's replicate-and-scale; upstream bidspm summed them, so a 3-run subject's contrast was 3x a 1-run
subject's); session-level and cross-session contrasts average the runs within each session, so `ses-1 > ses-2` sums to zero.
Single-run subjects and F contrasts are unchanged. **Results from earlier versions:** multi-run subject con images were
n× larger (n = runs with the condition; betas themselves are unchanged); subject-level T/F maps are identical, but group
results change unless every subject had the same number of runs, so re-run stats and dataset for multi-run data. The first
line of every stats log says which overrides the image has (`bidspm runner overrides: ... runs-averaged ...`; `unknown`
means an older image that still sums runs: rebuild it). The readiness check pairs events,
preprocessed BOLD and confounds per run by their BIDS entities (`ses`, `task`, `acq`, `run`, ...) and checks every run;
messages name the run, e.g. `sub-01 ses-1 run-2 (task-x) has preprocessed BOLD but no events file` (`run_unpaired`), or
`... has events but no preprocessed BOLD` (`preproc_missing`), `... has no confounds file` (`confounds_missing`). A run with
Stats but without Smooth needs every run smoothed at the project's FWHM (`smoothed_missing`, also tells you which FWHMs do
exist), and a Dataset-only run needs each subject's SPM.mat and the contrasts the dataset node uses
(`subject_results_missing`); the run itself also stops a subject whose run lacks its smoothed image instead of modelling fewer runs.

The GUI writes the settings file for you. For command-line use, start from the shipped template once
(`config/config.json` is your own copy and is not part of the repository):

```bash
cp config/config.example.json config/config.json   # then edit the paths
python bidspm.py --preflight -s config/config.json [--validator auto|prism|bids|skip | --skip-validator]
```

It prints a JSON report (`verdict`: `ready`, `warnings` or `blocked`) and exits 1 if blocked. With `--progress` it also writes
progress lines to stderr; stdout stays pure JSON.

```bash
python bidspm.py --preflight --progress -s config/config.json
```

In the GUI the readiness check lives in the last stage ("Review and run") of the analysis page, next to a validator select;
errors block Run (smooth/stats/dataset). While it runs the panel shows the current phase, a per-subject counter for the
per-subject checks, and errors as they are found; **Cancel** stops the check. The GUI starts a check with
`/api/preflight/start` and follows it on `/api/preflight/stream/<job>` (cancel: `/api/preflight/cancel/<job>`); at most 3
readiness checks run at once.

`/run` reuses a passing result (`ready` or `warnings`) for identical inputs for 10 minutes instead of checking again.
Dataset edits made in that window are not noticed. Any change of what the check covers invalidates the result: the BIDS
folder, the fMRIPrep folder, the tasks, the space, the subject selection, the container type, the validator mode, the
actions, the skip-model-validation flag and the model's content (not its path or timestamp). "Check readiness" sends the
same actions and flag as Run, so a passing check is reused by the next Run when nothing was changed in between.

Validator modes: `auto` (default: PRISM if the BIDS root has a `project.json`, otherwise plain BIDS), `prism` (PRISM + BIDS, forced), `bids` (plain BIDS), `skip`. `skip` disables only the dataset validator and
is shown as a warning; all other checks still run. `prism-validator` is installed by `uv sync`.

The version (2.1.1) comes from `pyproject.toml` and is shown in the GUI footer.

## Analysis page stages

The analysis page shows one stage at a time: **Folders**, **Model**, **Options**, **Review and run**. Next is enabled when the
current stage is valid:

- Folders: working directory, BIDS folder and fMRIPrep folder are set (Derivatives defaults to the Working Directory)
- Model: a models file is chosen
- Options: at least one action is selected

Finished stages show a one-line summary under their button. The last stage you were on is remembered per project, and
`#stage=folders|model|options|run` in the URL opens a stage directly (a deep link can skip ahead; the server still checks
everything on Run). The run controls and the readiness check are in the last stage.

## Model wizard

"New model" on the analysis page opens a wizard that builds a first-level BIDS Stats Model from the events files of your
project, so common models need no hand-written JSON. It is a one-step-at-a-time stepper with a live summary rail; Next is blocked
with a reason when the input of a step is incomplete. Five steps:

1. **Task and conditions**: pick the task; the wizard scans the events files (`trial_type` values and other columns) of all subjects. Uncheck conditions here to exclude them from the model.
2. **Recipes**: a gallery of four recipe cards (below); click one to add it. Recipes are applied in order.
3. **Nuisance**: a confound preset (e.g. motion6) or a custom comma-separated list of confound columns.
4. **Contrasts**: generated automatically (one per condition) plus simple pairs.
5. **Review and save**: shows the generated names live; "Check readiness" runs the preflight for the proposed model (it is slow on large studies, so the live preview skips it); saving does not repeat it.

Recipes:

- `valid_only`: keep only some trials, e.g. `response_validity == valid`
- `split_by_column`: split a condition by a column, e.g. split `item` by `response_validity`
- `merge_rename`: merge conditions, e.g. `a, b -> ab`
- `parametric_modulator`: modulate a regressor, e.g. `RT`, polynomial order 1-3; add it last: a later recipe that would consume the modulated regressor is rejected

Name rules: letters, digits and underscore only; `-` is also allowed in condition and value names. Values that start with a digit
get a `v` prefix in the generated column names (`2` becomes `v2`).

Splits with more than one value (or with the original kept) rename the split cells to the output column, so each regressor is a different condition in SPM (e.g. `valid_item.valid_item` and `invalid_item.invalid_item`); a single-value split keeps `valid_item.item`.

The readiness verdict is shown in the review step before saving. Saving is still allowed when preflight reports data problems (for example events
missing for one subject), so you can fix the data afterwards.

Contrasts are the basics only (auto + simple pairs). For anything else (weighted, F-contrasts, ...) save the model and open it in
the model editor, whose contrast builder is the advanced path.

Out of scope: editing existing models in the wizard (use the editor), group-level steps, per-trial split, recipes beyond these
four, SESSION/RUN selection, and showing transformed TSV rows (the preview shows names only).

## Configuration

### 1. Data configuration (`config.json`)

Create a `config.json` file with your specific settings:

```json
{
  "WD": "/path/to/your/working/directory",
  "BIDS_DIR": "/path/to/your/rawdata",
  "DERIVATIVES_DIR": "/path/to/your/derivatives",
  "FMRIPREP_DIR": "/path/to/your/derivatives/fmriprep",
  "SPACE": "MNI152NLin6Asym",
  "FWHM": 8,
  // (actions are now controlled via --action argument, not in config.json)
  "MODELS_FILE": "model_d1.json",
  "TASKS": ["nonsymbol", "symbol"],
  "SUBJECTS": ["01", "02", "03"],
  "VERBOSITY": 3
}
```


**Parameter explanation:**

- `WD`: Working directory (contains derivatives, models, etc.)
- `BIDS_DIR`: Path to BIDS raw data
- `DERIVATIVES_DIR`: Path to derivatives directory (where preprocessed data is stored)
- `FMRIPREP_DIR`: Path to fMRIPrep output directory
- `SPACE`: Spatial reference space for analysis
- `FWHM`: Full Width at Half Maximum for smoothing (in mm)
- `MODELS_FILE`: Name of the BIDS-StatsModel JSON file
- `TASKS`: List of fMRI tasks to process
- `SUBJECTS`: List of specific subjects to process (optional - if omitted, all subjects found will be processed)
- `VERBOSITY`: Logging verbosity level (0=minimal, 3=debug)
- `ROI`, `ROI_CONFIG`: Optional, for ROI analysis (see below)

**Note:** The actions (smoothing, stats, dataset-level) are now controlled via the `--action` command line argument, e.g. `--action smooth stats dataset`.

### 2. Container configuration (`container.json`)

#### For Docker

Use the image you pulled or built (see Installation above):

```json
{
  "container_type": "docker",
  "docker_image": "ghcr.io/mri-lab-graz/spm-bids-runner:latest",
  "apptainer_image": ""
}
```

#### For Apptainer

```json
{
  "container_type": "apptainer",
  "docker_image": "",
  "apptainer_image": "/path/to/containers/bidspm.sif"
}
```

Build a `.sif` from the local Docker image, e.g.
`apptainer build spm-bids-runner.sif docker-daemon://ghcr.io/mri-lab-graz/spm-bids-runner:latest`, or, once the image is published on GHCR,
`apptainer pull spm-bids-runner.sif docker://ghcr.io/mri-lab-graz/spm-bids-runner:latest`.

#### Optional: `spm_standalone_image`

Only needed for `--estimation-engine standalone` (next section). A Docker image reference (pin it by digest or image id)
or, for Apptainer, the path of a `.sif`:

```json
{ "container_type": "docker", "docker_image": "ghcr.io/mri-lab-graz/spm-bids-runner:latest",
  "spm_standalone_image": "sha256:<image id of your SPM standalone build>" }
```

## Faster estimation with SPM standalone (optional)

On long scans nearly all of a subject's time is SPM's model estimation (`spm_spm`), and Octave is much slower than
MATLAB at it. SPM publishes a compiled **standalone** that runs on the free MATLAB Runtime (no MATLAB licence). With
`--estimation-engine standalone` bidspm runs per subject: **design** in the Octave image, **estimation** in the SPM
standalone image, **contrasts** in the Octave image. Everything else (BMS, ROI features, smoothing, dataset level, reports)
stays on Octave, because the standalone has only SPM's core toolboxes.

Measured on one 1006-volume subject (study 141): 391 s end to end instead of about 33 minutes. The results match the
all-Octave run (43 files, r = 1.00000000, max relative difference 3e-8). Four standalone estimations in parallel took
346-378 s each. The default stays `octave`; nothing changes unless you ask.

**You provide the image.** SPM has no pinned SPM 26 container yet (26.10.01 was released 2026-10-13), so build one from
SPM's own recipe. The 26.10.01 standalone needs MATLAB Runtime **R2026a**:

```bash
git clone https://github.com/spm/spm-docker && cd spm-docker/matlab
docker build -t spm-standalone:26.10.01 \
  --build-arg MATLAB_VERSION=R2026a --build-arg SPM_RELEASE=26.10 --build-arg SPM_REVISION=01 .
docker inspect --format '{{.Id}}' spm-standalone:26.10.01      # pin this in container.json
```

(The build downloads the MATLAB Runtime, ~4 GB, and accepts MathWorks' runtime licence.) SPM also publishes SPM 25
images (`ghcr.io/spm/spm-docker:docker-matlab-25.01.02`); they work the same way and gave the same numbers, but then the
design/contrast steps (SPM 26) and the estimation (SPM 25) differ in version. Estimation code is unchanged between them.

Enable it with `--estimation-engine standalone` on the command line, or the "Model estimation engine" select in the GUI.
If `spm_standalone_image` is empty or the image is missing the run stops before the first subject with instructions;
it never falls back silently. The image id/digest is logged for reproducibility.

## Speed notes

Measured on a 32-core machine (study 132, 3 subjects in parallel, stats only): 8 min 9 s originally, 113 s now.

- **Thread cap per container.** Octave starts one busy-waiting BLAS thread per core, so parallel workers thrashed each other
  (394 s vs 115 s). Each container now gets `OPENBLAS_NUM_THREADS` = cores / workers (max 8).
- **Parallel subjects.** Heavy first-level estimation is single-core per subject, so a whole study scales by running more
  subjects at once. The GUI's **Suggest** button proposes a value from your CPU count and free memory (about 4 GB per worker).
- **SPM Results export is opt-in** (`--results`, or the checkbox in the GUI): it costs about a third of the per-subject time
  on short runs. The `report` action needs it and turns it on automatically.
  It writes csv result tables per contrast (subject and dataset level); no png or montage in this container (no Java, headless SPM).
- **Readiness check.** A 100-subject study checks in about 3 s without the dataset validator and about 17 s with it; the
  validator dominates the time.
- The BIDS dataset is validated by the first container only; the image ships no atlases, so nothing is unpacked per run.

## Checking a run log

`python scripts/check_run_log.py <logfile>` exits 1 if the log contains any error or warning that is not on a short
allow-list of data-dependent notices (contrasts without significant voxels, missing slice timing, features Octave lacks).

## Usage

### Basic usage

1. **Prepare configuration files**: Ensure that `config.json` and `container.json` are correctly configured.

2. **Create BIDS-StatsModel**: Create a BIDS-StatsModel JSON file in the `models/` folder of your Derivatives folder (the model wizard saves there; if you left Derivatives empty it is the working directory, so `{WD}/models/`)

3. **Run pipeline**:

```bash
python bidspm.py
```

**Command line options:**

```bash
# Run with default configuration files
python bidspm.py

# Run with custom configuration files
python bidspm.py -s my_config.json -c my_container.json

# Run with custom model file
python bidspm.py -m /path/to/my_model.json

# Run with all custom files
python bidspm.py -s config.json -c container.json -m models/task_model.json

# Show help
python bidspm.py -h
```

**Available options:**

- `-h, --help`: Show help message and exit
- `-s, --settings, --config`: Path to main configuration file (default: config.json)
- `-c, --container`: Path to container configuration file (default: container.json)
- `-m, --model, --model-file`: Path to BIDS-StatsModel JSON file (overrides MODELS_FILE in config)
- `--pilot`: Pilot mode - process only one random subject for testing
- `--skip-modelvalidation`: Skip BIDS-StatsModel JSON validation

**Logging:**

Log files are automatically generated with timestamps and model names for easy tracking:

- Format: `{model_name}_{YYYYMMDD_HHMMSS}.log`
- Example: `model_task1_20250721_143022.log`
- Stored in the `logs/` directory (created automatically)
- Contains detailed debug information and processing logs

### Advanced examples


#### Example: Minimal config.json

```json
{
  "WD": "/data/study01",
  "BIDS_DIR": "/data/study01/rawdata",
  "DERIVATIVES_DIR": "/data/study01/derivatives",
  "FMRIPREP_DIR": "/data/study01/derivatives/fmriprep",
  "SPACE": "MNI152NLin6Asym",
  "FWHM": 6,
  "MODELS_FILE": "task-localizer_model.json",
  "TASKS": ["localizer"]
}
```

**Actions are now selected at runtime:**

```bash
python bidspm.py --action smooth stats
```
## Configuration Validation

The tool automatically validates your `config.json` against a JSON schema (`config_schema.json`) using the [jsonschema](https://pypi.org/project/jsonschema/) package. This ensures your configuration is complete and correctly structured before processing starts.

**How it works:**

- The schema is defined in `config_schema.json` (see repository for example).
- On startup, `bidspm.py` checks that your `config.json` matches the schema.
- If validation fails, you get a clear error message and the run is aborted.
- The schema validation uses the `jsonschema` Python package (installed automatically via setup.sh/pyproject.toml).

**Example schema:**

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["WD", "BIDS_DIR", "DERIVATIVES_DIR", "FMRIPREP_DIR", "SPACE", "FWHM", "MODELS_FILE", "TASKS"],
  "properties": {
    "WD": {"type": "string"},
    "BIDS_DIR": {"type": "string"},
    "DERIVATIVES_DIR": {"type": "string"},
    "FMRIPREP_DIR": {"type": "string"},
    "SPACE": {"type": "string"},
    "FWHM": {"type": "number"},
    "MODELS_FILE": {"type": "string"},
    "TASKS": {"type": "array", "items": {"type": "string"}, "minItems": 1},
    "VERBOSITY": {"type": "integer", "minimum": 0, "maximum": 3},
    "SUBJECTS": {"type": "array", "items": {"type": "string"}},
    "ROI": {"type": "boolean"},
    "ROI_CONFIG": {
      "type": "object",
      "properties": {
        "roi_atlas": {"type": "string"},
        "roi_name": {"type": "array", "items": {"type": "string"}},
        "space": {"type": "array", "items": {"type": "string"}}
      },
      "required": ["roi_atlas", "roi_name", "space"]
    }
  },
  "additionalProperties": false
}
```

**Tip:** You can adapt the schema to your needs if you want to enforce additional fields or constraints.

#### Example 3: Custom model file

```bash
# Use a specific model file instead of the one specified in config.json
python bidspm.py -m /path/to/custom_model.json

# Combine with custom configuration files
python bidspm.py -s study_config.json -c docker_config.json -m models/task_analysis.json
```

#### Example 4: Pilot mode for testing

```bash
# Test your configuration with one random subject
python bidspm.py -s config.json -c container.json --pilot

# Pilot mode can be combined with other options
python bidspm.py -s test_config.json -c container.json -m pilot_model.json --pilot
```

**Note:** Pilot mode is particularly useful for:

- Testing your configuration before running the full dataset
- Quick validation of container setup and model files
- Debugging analysis parameters with faster execution
- If `SUBJECTS` is specified in config, pilot mode selects randomly from that list
- If no `SUBJECTS` specified, pilot mode selects randomly from all discovered subjects

#### Example 5: Multi-subject batch processing

The tool automatically processes all subjects in the fMRIPrep output directory:

```bash
# Working directory structure:
/data/study/
├── rawdata/
│   ├── sub-01/
│   ├── sub-02/
│   └── ...
├── derivatives/
│   ├── fmriprep/
│   │   ├── sub-01/
│   │   ├── sub-02/
│   │   └── ...
│   └── models/
│       └── my_model.json
└── config.json
```

### Logs and debugging

- All activities are logged to timestamped files: `{model_name}_{YYYYMMDD_HHMMSS}.log`
- Debug mode can be enabled in `bidspm.py` (DEBUG = True)
- Container commands are displayed before execution
- Log files include configuration details, processing steps, and any errors

## 🐳 Container Security & Performance

The tool implements several container security and performance enhancements:

### Apptainer Security Features

- **`--containall`**: Provides complete environment isolation
- **`--writable-tmpfs`**: Allows writing to `/tmp` and other temporary locations
- **Custom tmp directories**: Each run gets a unique temporary directory
- **Environment isolation**: Sets `HOME`, `TMPDIR`, and `TMP` to container `/tmp`

### Automatic Cleanup

- Old temporary directories (>24 hours) are automatically cleaned up
- Each run creates a unique tmp directory: `run_YYYYMMDD_HHMMSS_XXXX`
- Failed runs preserve tmp directories for debugging

### SPACE Validation

Before processing, the tool validates that the specified `SPACE` exists in your fMRIPrep data:

```bash
>>> Validating SPACE 'MNI152NLin6Asym' availability for task 'rest'...
❌ SPACE validation failed!
   Specified SPACE: 'MNI152NLin6Asym'
   Task: 'rest'
   Subjects missing SPACE 'MNI152NLin6Asym': ['sub-01', 'sub-02']
   Available spaces found: ['MNI152NLin2009cAsym', 'T1w']
   💡 Suggestion: Update SPACE in config.json to one of the available spaces
```

## BIDS-StatsModel validation

The tool automatically validates your BIDS-StatsModel file against the official schema before processing:

```bash
# Default behavior - automatic validation
python bidspm.py

# Skip validation if you're confident your model is correct
python bidspm.py --skip-modelvalidation

# Manual validation (standalone)
python validate_bids_model.py /path/to/your/model.json
```

**Note**: Validation ensures your BIDS-StatsModel follows the official specification and helps catch configuration errors early. Only skip validation if you're certain your model file is correctly formatted.

## Directory structure

```text
working_directory/
├── rawdata/                    # BIDS raw data
├── derivatives/
│   ├── fmriprep/              # fMRIPrep output
│   ├── bidspm-preproc/        # BIDSPM preprocessing output
│   ├── bidspm-stats/          # BIDSPM statistics output
│   └── models/                # BIDS-StatsModel files
├── config.json               # Main configuration
├── container.json            # Container configuration
└── run_bidspm.log           # Log file
```

## Troubleshooting

### Common issues

1. **Container not found**:

   ```bash
   # Check Docker
   docker --version
   docker images
   
   # Check Apptainer
   apptainer --version
   ls -la /path/to/bidspm.sif
   ```

2. **Path issues**:
   - Use absolute paths in configuration
   - Ensure all directories exist

3. **Model validation failed**:
   - Check BIDS-StatsModel syntax
   - Use validation script: `python validate_bids_model.py model.json`

4. **Docker permission issues**:

   ```bash
   sudo usermod -aG docker $USER
   # Then log out and log back in
   ```

### Debug tips

- Enable debug mode in `bidspm.py`
- Check the log file `run_bidspm.log`
- Test container commands manually

## Atlases

The `spm-bids-runner` image contains **no atlas**: none of the atlases bidspm knows has a clearly free licence
(Neuromorphometrics is CC BY-NC; AAL3, visfAtlas, Wang and Yeo have no licence; Glasser/HCPex carry the HCP data use
terms; details in `docs/third-party-licenses.md`). What this means:

- Statistics, contrasts, BMS and the results export work as before. Results tables (`--results`, report action) are
  written **without region labels**; the log shows a `labelActivations` WARNING "Atlas ... is not included in this
  image". The readiness check warns about this up front (`atlas_missing`).
- This runner does not run ROI extraction; the `ROI` / `ROI_CONFIG` settings are not used (the readiness check says
  so when they are set). bidspm's own ROI commands (`bidspm create_roi`) stop with the same clear message.

To use an atlas whose terms you accept, build a derived image that adds your own copy and point `docker_image`
(or your `.sif`) at it:

```dockerfile
FROM ghcr.io/mri-lab-graz/spm-bids-runner:latest
USER root
# Neuromorphometrics, from your own SPM12 download (labels for results tables):
COPY labels_Neuromorphometrics.nii labels_Neuromorphometrics.xml /opt/spm/tpm/
# CPP_ROI atlases (aal, wang, visfatlas, hcpex, glasser), from github.com/cpp-lln-lab/CPP_ROI (v0.4.0) atlas/:
COPY atlas/ /home/neuro/bidspm/lib/CPP_ROI/atlas/
RUN octave-cli --eval "cd('/home/neuro/bidspm'); bidspm('init'); copyAtlasToSpmDir('wang')" && chmod -R a+rX /opt/spm
USER neuro
```

(`copyAtlasToSpmDir` once per atlas you added, at build time: the container later runs as your host uid and cannot
write to `/opt/spm`.)

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the [GNU GPL v3.0 only](LICENSE) (GPL-3.0-only): it ships overrides derived from bidspm, which is GPL-3.0 without an "or later" grant. SPM and Octave are credited in the image NOTICE.

The container image is a separate work: it is distributed under GPL-3.0 (bidspm is GPL-3.0, SPM GPL-2.0-or-later,
GNU Octave GPL-3.0-or-later); see `/usr/share/doc/spm-bids-runner/NOTICE` in the image and
`docs/third-party-licenses.md`.

## Support

For questions or issues:

- Open an [Issue](https://github.com/MRI-Lab-Graz/bidspm/issues)
- Consult the [BIDSPM documentation](https://bidspm.readthedocs.io/)
- Check the [BIDS-StatsModel specification](https://bids-standard.github.io/stats-models/)

## Acknowledgments

- [bidspm](https://github.com/cpp-lln-lab/bidspm) by the CPP Lab (Remi Gau et al.) for the original framework
- [SPM](https://github.com/spm/spm) by the Wellcome Centre for Human Neuroimaging
- [GNU Octave](https://octave.org) for running SPM without MATLAB
- [BIDS-StatsModel](https://bids-standard.github.io/stats-models/) for standardization
- [fMRIPrep](https://fmriprep.org/) for the preprocessing pipeline
