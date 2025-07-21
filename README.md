# BIDSPM Runner

A Python-based tool for running BIDS-StatsModel pipelines via containers (Docker or Apptainer) without requiring MATLAB.

## Overview

BIDSPM Runner enables neuroimaging data analysis using the bidspm framework by leveraging containerized environments. The tool supports both Docker and Apptainer and can automatically perform smoothing and statistical analyses on BIDS-compliant datasets.

## Features

- 🐳 **Container Support**: Works with Docker and Apptainer
- 📊 **BIDS Compatibility**: Full support for BIDS-StatsModel schema
- 🔧 **Flexible Configuration**: JSON-based configuration for easy customization
- 📝 **Logging**: Detailed logging of all processing steps
- ✅ **Validation**: Automatic validation of BIDS-StatsModel files
- 🚀 **Batch Processing**: Processing of multiple subjects and tasks

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
  "SPACE": "MNI152NLin6Asym",
  "FWHM": 8,
  "SMOOTH": true,
  "STATS": true,
  "DATASET": true,
  "MODELS_FILE": "model_d1.json",
  "TASKS": ["nonsymbol", "symbol"]
}
```

**Parameter explanation:**

- `WD`: Working directory (contains derivatives, models, etc.)
- `BIDS_DIR`: Path to BIDS raw data
- `SPACE`: Spatial reference space for analysis
- `FWHM`: Full Width at Half Maximum for smoothing (in mm)
- `SMOOTH`: Boolean - whether to perform smoothing
- `STATS`: Boolean - whether to perform statistical analyses
- `DATASET`: Boolean - whether to perform dataset-level analyses
- `MODELS_FILE`: Name of the BIDS-StatsModel JSON file
- `TASKS`: List of fMRI tasks to process

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

**Logging:**

Log files are automatically generated with timestamps and model names for easy tracking:

- Format: `{model_name}_{YYYYMMDD_HHMMSS}.log`
- Example: `model_task1_20250721_143022.log`
- Contains detailed debug information and processing logs

### Advanced examples

#### Example 1: Smoothing only

```json
{
  "WD": "/data/study01",
  "BIDS_DIR": "/data/study01/rawdata",
  "SPACE": "MNI152NLin6Asym",
  "FWHM": 6,
  "SMOOTH": true,
  "STATS": false,
  "DATASET": false,
  "MODELS_FILE": "task-localizer_model.json",
  "TASKS": ["localizer"]
}
```

#### Example 2: Complete analysis pipeline

```json
{
  "WD": "/data/study02",
  "BIDS_DIR": "/data/study02/rawdata",
  "SPACE": "MNI152NLin2009cAsym",
  "FWHM": 8,
  "SMOOTH": true,
  "STATS": true,
  "DATASET": true,
  "MODELS_FILE": "full_analysis_model.json",
  "TASKS": ["rest", "task", "localizer"]
}
```

#### Example 3: Custom model file

```bash
# Use a specific model file instead of the one specified in config.json
python bidspm.py -m /path/to/custom_model.json

# Combine with custom configuration files
python bidspm.py -s study_config.json -c docker_config.json -m models/task_analysis.json
```

#### Example 4: Multi-subject batch processing

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

## BIDS-StatsModel validation

The tool automatically validates your BIDS-StatsModel file against the official schema:

```bash
# Manual validation
python validate_bids_model.py /path/to/your/model.json
```

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
