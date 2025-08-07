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

## ⚠️ Known Issues and Solutions

### 🗺️ Atlas Initialization Error

You may encounter this error when using BIDSPM containers:

```bash
'returnAtlasDir' undefined near line 88, column 88
Error Octave:undefined-function occurred:
  - Error in copyAtlasToSpmDir>prepareFiles
    line 88 in /home/neuro/bidspm/lib/CPP_ROI/src/atlas/copyAtlasToSpmDir.m
```

**Cause**: This is a bug in the BIDSPM container where the `returnAtlasDir` function from CPP_ROI is not properly accessible due to MATLAB path configuration issues.

**Solutions**:

1. **Use Specific Version** (Recommended):

   ```bash
   # Edit your container configuration to use a specific working version
   "apptainer_image": "docker://cpplab/bidspm:4.0.0"  # instead of latest
   ```

2. **Skip Atlas Initialization**:

   ```bash
   # The tool automatically sets this environment variable
   BIDSPM_SKIP_ATLAS_INIT=1
   ```

3. **Test Different Versions**:

   Try different container versions to find one that works:
   ```bash
   # Edit container.json to test different versions
   "docker_image": "cpplab/bidspm:4.0.0"
   ```

4. **Manual Path Configuration**:

   If issues persist, the tool automatically configures enhanced MATLAB paths to work around this issue.

### 🔧 Enhanced MATLAB Path Configuration

The tool automatically configures the MATLAB path to include:

- `/home/neuro/bidspm` (main BIDSPM directory)
- `/home/neuro/bidspm/lib/CPP_ROI` (CPP_ROI library)
- `/home/neuro/bidspm/lib/CPP_ROI/atlas` (atlas functions including returnAtlasDir)
- `/opt/spm12` (SPM12 installation)

This ensures that all required functions are accessible within the container.

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
  "docker_image": "cpplab/bidspm:latest",
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

### Option 1: With pip (recommended)

```bash
git clone https://github.com/MRI-Lab-Graz/bidspm.git
cd bidspm
pip install -e .
```

### Option 2: With setup script (cross-platform)

The included setup script automatically creates a virtual environment using UV and installs all dependencies:

```bash
git clone https://github.com/MRI-Lab-Graz/bidspm.git
cd bidspm
chmod +x setup.sh
./setup.sh
```

Then activate the environment:

```bash
source ./activate_bidspm.sh
```

### Option 3: Manual installation

```bash
git clone https://github.com/MRI-Lab-Graz/bidspm.git
cd bidspm
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install requests jsonschema
```

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

```json
{
  "container_type": "docker",
  "docker_image": "cpplab/bidspm:arm64",
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
