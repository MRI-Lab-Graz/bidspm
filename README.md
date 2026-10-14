# BIDSPM Runner

A Python-based tool for running BIDS-StatsModel pipelines via containers (Docker or Apptainer) without requiring MATLAB.

## Overview

BIDSPM Runner enables neuroimaging data analysis using the bidspm framework by leveraging containerized environments. The tool supports both Docker and Apptainer and can automatically perform smoothing and statistical analyses on BIDS-compliant datasets.

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
- 🎯 **ROI Analysis**: Extract signals from regions of interest using multiple atlases (Wang, Neuromorphometrics, etc.)

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
  (`docker build -f containers/dockerfile/dockerfile -t bidspm/bidspm:latest .`, about 10 minutes, ~4.6 GB).
- The published `ghcr.io/mri-lab-graz/bidspm:latest` predates this SPM 26 image and is not compatible with this code; the defaults point at the image you build locally (`bidspm/bidspm:latest`).
- "Slice timing information was missing" in a stats log is expected for fMRIPrep input: fMRIPrep drops `SliceTiming`
  after correcting and records `StartTime`, which is used for SPM's `fmri_t0`.

## 🌍 Multi-Platform Support

The tool automatically detects your platform and selects the appropriate container runtime:

### 🖥️ **macOS (Development/Piloting)**

- **Auto-detected**: Docker (Apptainer not supported on macOS)
- **Container**: `container.json` (Docker configuration)
- **Usage**: Perfect for testing and piloting analyses

### 🐧 **Linux (Production/HPC)**

- **Auto-detected**: Apptainer (preferred) or Docker
- **Container**: `container_apptainer.json` (Apptainer) or `container.json` (Docker)
- **Usage**: Production runs on high-performance computing systems

### 🚀 **Quick Platform Setup**

```bash
# Run platform-specific setup
./setup_platform.sh

# Or let the tool auto-detect
python bidspm.py --pilot  # Automatically selects the right container
```

### 📁 **Container Configuration Files**

The tool supports multiple container configurations:

- `container.json` - Docker for macOS/development
- `container_apptainer.json` - Apptainer for Linux/HPC

**Example Docker config (macOS):**
```json
{
  "container_type": "docker",
  "docker_image": "bidspm/bidspm:latest",
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

- Python 3.8 or higher
- Docker or Apptainer
- BIDS-compliant dataset
- Preprocessed fMRI data (e.g., from fMRIPrep)

## Installation

### Option 1: Docker image (recommended)

This repo is a Python CLI/webapp that drives a Docker (or Apptainer)
container where the actual SPM/Octave analysis runs -- you need both parts.

Build the image from this checkout (SPM 26.10.01 is compiled for Octave during the build; the SPM version is a
build argument, `--build-arg SPM_TAG=26.10.01`):

```bash
docker build -f containers/dockerfile/dockerfile -t bidspm/bidspm:latest .
```

(`containers/dockerfile/build_mri_lab_container.sh` wraps the same command.)

Then get the Python side running:

```bash
git clone https://github.com/MRI-Lab-Graz/bidspm.git
cd bidspm
pip install -r requirements.txt
```

Point `container.json` at the image you built (`"docker_image": "bidspm/bidspm:latest"`).

**On a remote server without a display:** the web GUI starts without opening a browser when it detects an SSH session
(or with `--no-browser`). It listens on `127.0.0.1` only, because it has no login (anyone who can reach the port can run
jobs and read files). Forward the port from your own machine instead of exposing it:
`ssh -L 5100:localhost:5100 you@server`, then open `http://localhost:5100`. Use `--host 0.0.0.0` only on a network you trust.

### Option 2: With setup script (cross-platform)

The included setup script automatically creates a virtual environment (`.bidspm/`) using UV and installs all dependencies:

```bash
git clone https://github.com/MRI-Lab-Graz/bidspm.git
cd bidspm
./scripts/setup.sh
```

Then activate the environment:

```bash
source ./scripts/activate_bidspm.sh
```

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

### Option 3: Manual installation

```bash
git clone https://github.com/MRI-Lab-Graz/bidspm.git
cd bidspm
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Testing

Run the test suite from repository root:

```bash
pip install pytest        # not in requirements.txt
python -m pytest -q tests # `python -m unittest discover -s tests -p "test_*.py"` also works
```

A few tests need extras and skip themselves when they are missing (pandas for `scripts/fix_events_format.py`, GNU Octave on the host
for the `.m` override tests). The image smoke test runs only with `BIDSPM_TEST_IMAGE=<built image>`. `tests/test_analysis_page_browser.py` opens the
analysis page in headless Chromium and needs `pip install playwright && playwright install chromium` (it skips itself otherwise).

Notes:

- Add tests for each new feature under `tests/`.
- Keep tests deterministic and independent from external services.

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

Use the image you built (see Installation above):

```json
{
  "container_type": "docker",
  "docker_image": "bidspm/bidspm:latest",
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

Build a `.sif` from the Docker image above, e.g.
`apptainer build bidspm.sif docker-daemon://bidspm/bidspm:latest`.

#### Optional: `spm_standalone_image`

Only needed for `--estimation-engine standalone` (next section). A Docker image reference (pin it by digest or image id)
or, for Apptainer, the path of a `.sif`:

```json
{ "container_type": "docker", "docker_image": "bidspm/bidspm:latest",
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
- The BIDS dataset is validated by the first container only, and the atlases are unpacked at build time (no warm-up subject).

## Checking a run log

`python scripts/check_run_log.py <logfile>` exits 1 if the log contains any error or warning that is not on a short
allow-list of data-dependent notices (contrasts without significant voxels, missing slice timing, features Octave lacks).

## Usage

### Basic usage

1. **Prepare configuration files**: Ensure that `config.json` and `container.json` are correctly configured.

2. **Create BIDS-StatsModel**: Create a BIDS-StatsModel JSON file in `{WD}/derivatives/models/`

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

## ROI Analysis

BIDSPM supports region of interest (ROI) analysis for extracting signals from specific brain regions. The ROI analysis uses various atlases to define regions and extract time series data.

### ROI Configuration

To enable ROI analysis, add the following to your `config.json`:

```json
{
  "ROI": true,
  "ROI_CONFIG": {
    "roi_atlas": "wang",
    "roi_name": ["V1v", "V1d"],
    "space": ["MNI152NLin6Asym"]
  }
}
```

### ROI Parameters

- **`ROI`**: Boolean flag to enable/disable ROI analysis
- **`roi_atlas`**: Atlas name to use for ROI extraction (e.g., "wang", "neuromorphometrics")
- **`roi_name`**: Array of specific ROI names to extract from the atlas
- **`space`**: Array of spatial reference spaces to use (must match available fMRIPrep outputs)

### Available Atlases and ROIs

#### Wang Atlas
The Wang atlas provides retinotopic visual cortex parcellations:
- **V1v**: Ventral V1
- **V1d**: Dorsal V1
- **V2v**: Ventral V2
- **V2d**: Dorsal V2
- **V3v**: Ventral V3
- **V3d**: Dorsal V3

### ROI Analysis Workflow

1. **Prerequisites Check**: Verifies Docker/Apptainer availability
2. **ROI Extraction**: Extracts time series from specified ROIs using the selected atlas
3. **Statistics**: Computes ROI-based statistics in the specified spatial reference space
4. **Output**: Results are saved to `/derivatives/bidspm-roi/`

### Example ROI Configuration

```json
{
  "BIDSPM_PATH": "/path/to/bidspm-container.sif",
  "BIDS_DIR": "/path/to/bids",
  "OUTPUT_DIR": "/path/to/output",
  "DERIVATIVES_DIR": "/path/to/derivatives",
  "PARTICIPANT_LABEL": ["01", "02"],
  "TASK_LABEL": ["task1"],
  "SPACE": ["MNI152NLin6Asym"],
  "FWHM": [8],
  "MODEL_FILE": "/path/to/model.json",
  "PREPROC_DIR": "/path/to/fmriprep",
  "STATS": true,
  "PREPROC": false,
  "QC": false,
  "ROI": true,
  "ROI_CONFIG": {
    "roi_atlas": "wang",
    "roi_name": ["V1v", "V1d"],
    "space": ["MNI152NLin6Asym"]
  }
}
```

### ROI Output Structure

The ROI analysis creates the following output structure:

```
derivatives/bidspm-roi/
├── dataset_description.json
└── sub-*/
    └── roi/
        ├── *_roi-V1v_timeseries.tsv
        ├── *_roi-V1d_timeseries.tsv
        └── *_roi-stats.json
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the [MIT License](LICENSE).

## Support

For questions or issues:

- Open an [Issue](https://github.com/MRI-Lab-Graz/bidspm/issues)
- Consult the [BIDSPM documentation](https://bidspm.readthedocs.io/)
- Check the [BIDS-StatsModel specification](https://bids-standard.github.io/stats-models/)

## Acknowledgments

- [BIDSPM](https://github.com/cpp-lln-lab/bidspm) for the original framework
- [BIDS-StatsModel](https://bids-standard.github.io/stats-models/) for standardization
- [fMRIPrep](https://fmriprep.org/) for the preprocessing pipeline
