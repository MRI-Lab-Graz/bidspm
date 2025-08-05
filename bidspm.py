#!/usr/bin/env python3

import json
import subprocess
import sys
import shutil
import argparse
import random
import re
import platform
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional


# ------------------------------
# Configuration
# ------------------------------

CONFIG_FILE = "config.json"
CONTAINER_CONFIG_FILE = "container.json"
LOG_FILE = "run_bidspm.log"
DEBUG = True  # Set to False to suppress debug output


@dataclass
class Config:
    WD: Path
    BIDS_DIR: Path
    DERIVATIVES_DIR: Path
    SPACE: str
    FWHM: float
    SMOOTH: bool
    STATS: bool
    MODELS_FILE: str
    TASKS: List[str]
    DATASET: bool
    FMRIPREP_DIR: Path
    VERBOSITY: int = 0  # Default to 0, can be increased for more verbose output
    SUBJECTS: Optional[List[str]] = None  # If None, process all subjects found


@dataclass
class ContainerConfig:
    container_type: str  # "docker" or "apptainer"
    docker_image: str
    apptainer_image: str


def load_config(config_file: str) -> Config:
    if not Path(config_file).exists():
        log_error(f"Config file '{config_file}' not found.")

    with open(config_file) as f:
        data = json.load(f)

    # --- Validation ---
    required_fields = ["WD", "BIDS_DIR", "DERIVATIVES_DIR", "SPACE", "FWHM", "SMOOTH", "STATS", "DATASET", "TASKS", "FMRIPREP_DIR"]
    for field in required_fields:
        if field not in data:
            log_error(f"Missing required field in config: '{field}'")

    # MODELS_FILE is optional if -m is used, but warn if beides fehlt
    if "MODELS_FILE" not in data:
        print("⚠️  No MODELS_FILE in config. You must provide -m on the command line!")

    # Check types and values
    if not isinstance(data["TASKS"], list) or not data["TASKS"]:
        log_error("'TASKS' must be a non-empty list!")
    if "SUBJECTS" in data and data["SUBJECTS"] is not None:
        if not isinstance(data["SUBJECTS"], list):
            log_error("'SUBJECTS' must be a list or omitted/null!")
        if len(data["SUBJECTS"]) == 0:
            print("⚠️  'SUBJECTS' is an empty list. No subjects will be processed!")

    # Validate VERBOSITY if provided
    verbosity = data.get("VERBOSITY", 0)
    if not isinstance(verbosity, int) or verbosity < 0 or verbosity > 3:
        print("⚠️  VERBOSITY must be an integer between 0-3. Using default value 0.")
        verbosity = 0

    # Path checks
    wd = Path(data["WD"])
    bids_dir = Path(data["BIDS_DIR"])
    derivatives_dir = Path(data["DERIVATIVES_DIR"])
    fmriprep_dir = Path(data["FMRIPREP_DIR"])
    for p, name in [(wd, "WD"), (bids_dir, "BIDS_DIR"), (derivatives_dir, "DERIVATIVES_DIR"), (fmriprep_dir, "FMRIPREP_DIR")]:
        if not p.exists() or not p.is_dir():
            log_error(f"{name} '{p}' does not exist or is not a directory!")

    # Log config summary
    print("--- Loaded configuration ---")
    for k, v in data.items():
        print(f"{k}: {v}")
    print("---------------------------")

    return Config(
        WD=wd,
        BIDS_DIR=bids_dir,
        DERIVATIVES_DIR=derivatives_dir,
        SPACE=data["SPACE"],
        FWHM=data["FWHM"],
        SMOOTH=data["SMOOTH"],
        STATS=data["STATS"],
        MODELS_FILE=data.get("MODELS_FILE", None),
        TASKS=data["TASKS"],
        DATASET=data["DATASET"],
        FMRIPREP_DIR=fmriprep_dir,
        VERBOSITY=verbosity,
        SUBJECTS=data.get("SUBJECTS")  # Optional field, defaults to None
    )


def load_container_config(config_file: str) -> ContainerConfig:
    if not Path(config_file).exists():
        log_error(f"Container config file '{config_file}' not found.")

    with open(config_file) as f:
        data = json.load(f)

    container_type = data.get("container_type", "docker").lower()
    if container_type not in ["docker", "apptainer"]:
        log_error(f"Invalid container_type '{container_type}'. Must be 'docker' or 'apptainer'.")

    return ContainerConfig(
        container_type=container_type,
        docker_image=data.get("docker_image", ""),
        apptainer_image=data.get("apptainer_image", "")
    )


def detect_platform_and_suggest_container():
    """Detect platform and suggest appropriate container configuration."""
    system = platform.system().lower()
    
    if system == "darwin":  # macOS
        return "docker", "Docker recommended for macOS (Apptainer not supported)."
    elif system == "linux":
        # Check what's available - prefer what user has configured
        docker_available = False
        apptainer_available = False
        
        try:
            subprocess.run(["docker", "--version"], capture_output=True, check=True)
            docker_available = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
            
        try:
            subprocess.run(["apptainer", "--version"], capture_output=True, check=True)
            apptainer_available = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        
        # HPC systems often only have Apptainer
        if apptainer_available and not docker_available:
            return "apptainer", "HPC environment detected - using Apptainer (Docker not available)."
        elif docker_available and not apptainer_available:
            return "docker", "Docker detected on Linux."
        elif docker_available and apptainer_available:
            return "docker", "Both Docker and Apptainer available - using Docker for consistency."
        else:
            return None, "Neither Docker nor Apptainer found on Linux system."
    else:
        return "docker", f"Unknown platform ({system}), Docker recommended."


def auto_select_container_config():
    """Automatically select container configuration based on platform."""
    detected_type, message = detect_platform_and_suggest_container()
    
    print(f"🔍 Platform detection: {message}")
    
    # Try to find appropriate container config
    config_candidates = []
    
    if detected_type == "docker":
        config_candidates = ["container.json", "container_docker.json", "container_dev.json"]
    elif detected_type == "apptainer":
        config_candidates = ["container_production.json", "container_apptainer.json", "container.json"]
    
    for candidate in config_candidates:
        if Path(candidate).exists():
            try:
                with open(candidate, 'r') as f:
                    config = json.load(f)
                if config.get("container_type") == detected_type:
                    print(f"✅ Auto-selected container config: {candidate}")
                    return candidate
            except Exception:
                continue
    
    return None


# ------------------------------
# Logging & Utilities
# ------------------------------

def get_container_model_path(model_file_path: Path, derivatives_dir: Path) -> str:
    """Get the correct model file path within the container"""
    try:
        # If model file is inside derivatives directory, use relative path
        relative_path = model_file_path.relative_to(derivatives_dir)
        return f"/derivatives/{relative_path}"
    except ValueError:
        # Model file is outside derivatives, use mounted path
        return "/models/smdl.json"


def generate_log_filename(model_file_path: str) -> str:
    """Generate log filename based on model name and timestamp"""
    model_name = Path(model_file_path).stem  # Get filename without extension
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{model_name}_{timestamp}.log"


def log_debug(msg):
    if DEBUG:
        log(f"[DEBUG] {msg}")


def log_error(msg):
    log(f"[ERROR] {msg}", error=True)
    sys.exit(1)


def log(msg, error=False):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_msg = f"{timestamp} {msg}"
    with open(LOG_FILE, "a") as f:
        f.write(full_msg + "\n")
    print(full_msg, file=sys.stderr if error else sys.stdout)


def validate_space_availability(config: Config, subjects_to_process: List[str], task: str) -> bool:
    """Validate that the specified SPACE exists in fMRIPrep derivatives for the given subjects and task"""
    log_debug(f"Validating SPACE '{config.SPACE}' for task '{task}'")
    
    found_subjects = []
    missing_subjects = []
    available_spaces = set()
    
    for subject_label in subjects_to_process:
        subject_dir = config.FMRIPREP_DIR / f"sub-{subject_label}"
        if not subject_dir.is_dir():
            missing_subjects.append(subject_label)
            continue
            
        # Look for BOLD files with the specified task
        pattern = f"sub-{subject_label}_*task-{task}_*space-*_desc-preproc_bold.nii.gz"
        bold_files = list(subject_dir.rglob(pattern))
        
        # Extract available spaces for this subject/task
        subject_spaces = set()
        space_found = False
        
        for bold_file in bold_files:
            # Extract space from filename using regex
            space_match = re.search(r'space-([^_]+)', bold_file.name)
            if space_match:
                space_name = space_match.group(1)
                subject_spaces.add(space_name)
                available_spaces.add(space_name)
                
                if space_name == config.SPACE:
                    space_found = True
        
        if space_found:
            found_subjects.append(subject_label)
            log_debug(f"Subject {subject_label}: SPACE '{config.SPACE}' found")
        else:
            missing_subjects.append(subject_label)
            if subject_spaces:
                log_debug(f"Subject {subject_label}: SPACE '{config.SPACE}' NOT found. Available spaces: {sorted(subject_spaces)}")
            else:
                log_debug(f"Subject {subject_label}: No BOLD files found for task '{task}'")
    
    # Report results
    if missing_subjects:
        print("❌ SPACE validation failed!")
        print(f"   Specified SPACE: '{config.SPACE}'")
        print(f"   Task: '{task}'")
        print(f"   Subjects missing SPACE '{config.SPACE}': {missing_subjects}")
        if available_spaces:
            print(f"   Available spaces found: {sorted(available_spaces)}")
            print("   💡 Suggestion: Update SPACE in config.json to one of the available spaces")
        else:
            print(f"   ⚠️  No BOLD files found for task '{task}' in any subject")
        return False
    
    print(f"✅ SPACE validation passed: '{config.SPACE}' found for all {len(found_subjects)} subjects")
    return True


def check_command(cmd):
    if not shutil.which(cmd):
        log_error(f"'{cmd}' is required but not installed or in PATH.")


def run_command(cmd_list, capture_output=False):
    log_debug(f"Running command: {' '.join(cmd_list)}")
    
    try:
        result = subprocess.run(cmd_list, check=True, text=True,
                                stdout=subprocess.PIPE if capture_output else None,
                                stderr=subprocess.STDOUT)
        if capture_output:
            log(result.stdout)
        return True  # Success
    except subprocess.CalledProcessError as e:
        log_error_non_fatal(f"Command failed with exit code {e.returncode}: {' '.join(cmd_list)}")
        if e.stdout:
            log(f"Command output: {e.stdout}")
        return False  # Failure


def log_error_non_fatal(msg):
    """Log non-fatal error that doesn't stop execution"""
    print(f"⚠️  {msg}", file=sys.stderr)

def setup_octave_compatibility(container_config: ContainerConfig):
    """Setup Octave compatibility for older versions that lack 'contains' function"""
    setup_script = '''
    mkdir -p /tmp/octave_compat
    
    # Create compatibility function for 'contains' (missing in Octave < 7.0)
    cat > /tmp/octave_compat/octaverc << 'EOF'
% Octave compatibility startup script for BIDSPM
warning('off', 'all');

% Add compatibility function for contains (Octave < 7.0)
if ~exist('contains', 'builtin') && ~exist('contains', 'file')
    function result = contains(str, pattern)
        if ischar(str) && ischar(pattern)
            result = ~isempty(strfind(str, pattern));
        elseif iscell(str)
            result = false(size(str));
            for i = 1:numel(str)
                if ischar(str{i})
                    result(i) = ~isempty(strfind(str{i}, pattern));
                end
            end
        else
            result = false;
        end
    end
end

% Add BIDSPM paths
addpath('/home/neuro/bidspm');
addpath('/home/neuro/bidspm/lib/CPP_ROI');
addpath('/home/neuro/bidspm/lib/CPP_ROI/atlas');
addpath('/opt/spm12');

fprintf('🔧 Octave compatibility loaded\\n');
EOF
    '''
    
    try:
        # Determine container path and command based on container type
        if container_config.container_type == "docker":
            # For docker, we would need different handling, but mainly using apptainer
            log_error_non_fatal("Octave compatibility setup not implemented for Docker containers")
            return False
        elif container_config.container_type == "apptainer":
            container_path = container_config.apptainer_image
            cmd = ["apptainer", "exec", "--writable-tmpfs", container_path, "bash", "-c", setup_script]
        else:
            log_error_non_fatal(f"Unknown container type: {container_config.container_type}")
            return False
        
        # Set up compatibility in the container
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            log("✅ Octave compatibility setup successful")
            return True
        else:
            log_error_non_fatal(f"Octave compatibility setup warning: {result.stderr}")
            return False
    except Exception as e:
        log_error_non_fatal(f"Could not setup Octave compatibility: {e}")
        return False


def build_container_command(container_config: ContainerConfig, config: Config, args: List[str], model_file_path: Path) -> List[str]:
    """Build container command based on container type (docker or apptainer)"""
    
    if container_config.container_type == "docker":
        if not container_config.docker_image:
            log_error("Docker image not specified in container configuration.")
        
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{config.BIDS_DIR}:/raw",
            "-v", f"{config.DERIVATIVES_DIR}:/derivatives"
        ]
        
        # Create and mount a dedicated tmp directory for this run
        run_tmp_dir = config.WD / "tmp" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"
        run_tmp_dir.mkdir(parents=True, exist_ok=True)
        cmd.extend(["-v", f"{run_tmp_dir}:/tmp"])
        
        # Check if model file is inside derivatives directory
        try:
            model_file_path.relative_to(config.DERIVATIVES_DIR)
            # Model file is inside derivatives, use relative path - no additional volume mount needed
        except ValueError:
            # Model file is outside derivatives, mount it separately
            cmd.extend(["-v", f"{model_file_path}:/models/smdl.json"])
        
        # Set environment variables for better container isolation
        cmd.extend([
            "-e", "HOME=/tmp",
            "-e", "TMPDIR=/tmp",
            "-e", "TMP=/tmp"
        ])

        cmd.append(container_config.docker_image)
        cmd.extend(args)
        return cmd
    
    elif container_config.container_type == "apptainer":
        if not container_config.apptainer_image:
            log_error("Apptainer image not specified in container configuration.")
        
        # Check if it's a docker:// URL or local .sif file
        if not container_config.apptainer_image.startswith("docker://") and not Path(container_config.apptainer_image).exists():
            log_error(f"Apptainer image file '{container_config.apptainer_image}' not found.")
        
        cmd = [
            "apptainer", "run",
            "--containall",  # Isolate container environment
            "--writable-tmpfs",  # Allow writing to /tmp and other temp locations
            "--cleanenv",  # Start with clean environment
            "--bind", f"{config.BIDS_DIR}:/raw",
            "--bind", f"{config.DERIVATIVES_DIR}:/derivatives"
        ]
        
        # Check if model file is inside derivatives directory
        try:
            model_file_path.relative_to(config.DERIVATIVES_DIR)
            # Model file is inside derivatives, use relative path - no additional bind needed
        except ValueError:
            # Model file is outside derivatives, mount it separately
            cmd.extend(["--bind", f"{model_file_path}:/models/smdl.json"])
        
        # Create and mount a dedicated tmp directory for this run
        run_tmp_dir = config.WD / "tmp" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"
        run_tmp_dir.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--bind", f"{run_tmp_dir}:/tmp"])
        
        # Add additional bind mounts for writable directories to solve "Read-only file system" issues
        atlas_dir = config.WD / "atlas"
        cpp_roi_atlas_dir = config.WD / "cpp_roi_atlas"
        error_logs_dir = config.WD / "error_logs"
        spm_dir = config.WD / "spm"
        matlab_cache_dir = config.WD / "matlab_cache"
        
        # Create directories if they don't exist
        atlas_dir.mkdir(exist_ok=True)
        cpp_roi_atlas_dir.mkdir(exist_ok=True)
        error_logs_dir.mkdir(exist_ok=True)
        spm_dir.mkdir(exist_ok=True)
        matlab_cache_dir.mkdir(exist_ok=True)
        
        cmd.extend([
            "--bind", f"{atlas_dir}:/opt/spm12/atlas",
            "--bind", f"{cpp_roi_atlas_dir}:/home/neuro/bidspm/lib/CPP_ROI/atlas",
            "--bind", f"{error_logs_dir}:/home/neuro/bidspm/error_logs",
            "--bind", f"{spm_dir}:/home/neuro/spm",  # SPM working directory
            "--bind", f"{matlab_cache_dir}:/home/neuro/.matlab"  # MATLAB cache
        ])
        
        # Set important environment variables for the container
        cmd.extend([
            "--env", "HOME=/tmp",  # Set HOME to tmp directory
            "--env", "TMPDIR=/tmp",  # Set TMPDIR
            "--env", "TMP=/tmp",     # Set TMP
            "--env", "MATLAB_LOG_DIR=/tmp",  # MATLAB logs to tmp
            "--env", "SPM_HTML_BROWSER=0",   # Disable SPM browser for headless operation
            "--env", "BIDSPM_SKIP_ATLAS_INIT=1",  # Try to skip problematic atlas initialization
            "--env", "OCTAVE_EXECUTABLE=/usr/bin/octave",  # Ensure Octave path
            "--env", "MATLABPATH=/home/neuro/bidspm:/home/neuro/bidspm/lib/CPP_ROI:/home/neuro/bidspm/lib/CPP_ROI/atlas:/opt/spm12",  # Explicit MATLAB path with atlas directory
            "--env", "CPP_ROI_SKIP_ATLAS=1",  # Skip CPP_ROI atlas operations if supported
            "--env", "OCTAVE_INIT_FILE=/tmp/octave_init.m",  # Custom Octave initialization to force atlas path
            "--env", "OCTAVE_SITE_INITFILE=/tmp/octave_compat/octaverc"  # Octave compatibility startup script
        ])

        cmd.append(container_config.apptainer_image)
        cmd.extend(args)
        return cmd
    
    else:
        log_error(f"Unsupported container type: {container_config.container_type}")


def cleanup_tmp_directories(config: Config, max_age_hours: int = 24):
    """Clean up old temporary directories to prevent disk space issues."""
    try:
        tmp_base_dir = config.WD / "tmp"
        if not tmp_base_dir.exists():
            return
        
        current_time = datetime.now()
        removed_count = 0
        
        for tmp_dir in tmp_base_dir.iterdir():
            if tmp_dir.is_dir() and tmp_dir.name.startswith("run_"):
                # Check age of directory
                dir_age = current_time - datetime.fromtimestamp(tmp_dir.stat().st_mtime)
                if dir_age.total_seconds() > (max_age_hours * 3600):
                    try:
                        shutil.rmtree(tmp_dir)
                        removed_count += 1
                        log_debug(f"Cleaned up old tmp directory: {tmp_dir}")
                    except Exception as e:
                        log_debug(f"Could not clean up tmp directory {tmp_dir}: {e}")
        
        if removed_count > 0:
            print(f"🧹 Cleaned up {removed_count} old temporary directories")
            log_debug(f"Cleaned up {removed_count} old temporary directories")
    
    except Exception as e:
        log_debug(f"Error during tmp directory cleanup: {e}")


# ------------------------------
# Help and Usage
# ------------------------------

def show_help():
    """Display help information for BIDSPM Runner"""
    help_text = """
BIDSPM Runner - A Python tool for running BIDS-StatsModel pipelines via containers

USAGE:
    python bidspm.py [OPTIONS]

OPTIONS:
    -h, --help                    Show this help message and exit
    -s, --settings, --config     Path to main configuration file
    -c, --container               Path to container configuration file
    -m, --model, --model-file     Path to BIDS-StatsModel JSON file (overrides MODELS_FILE in config)
    --pilot                       Pilot mode: process only one random subject for testing

DESCRIPTION:
    BIDSPM Runner executes neuroimaging analysis pipelines using containerized 
    environments (Docker or Apptainer) without requiring MATLAB. The tool 
    processes BIDS-compliant datasets and performs smoothing and statistical 
    analyses based on configuration files.

CONFIGURATION FILES:
    Main config file contains analysis parameters (paths, smoothing, tasks, etc.)
    Container config file specifies Docker or Apptainer settings
    
    If not specified with -s and -c options, the tool will look for:
    - config.json (main configuration)
    - container.json (container configuration)

CONFIGURATION EXAMPLE (main config file):
    {
        "WD": "/path/to/working/directory",
        "BIDS_DIR": "/path/to/bids/rawdata", 
        "SPACE": "MNI152NLin6Asym",
        "FWHM": 8,
        "SMOOTH": true,
        "STATS": true,
        "DATASET": true,
        "MODELS_FILE": "model.json",
        "TASKS": ["task1", "task2"],
        "SUBJECTS": ["01", "02", "03"],
        "VERBOSITY": 1
    }
    
    Note: SUBJECTS is optional - if omitted, all subjects found will be processed
    Note: VERBOSITY is optional (0-3) - higher values provide more detailed output

CONTAINER CONFIGURATION EXAMPLE:
    {
        "container_type": "docker",
        "docker_image": "cpplab/bidspm:arm64",
        "apptainer_image": ""
    }

WORKFLOW:
    1. Validates BIDS-StatsModel file against official schema
    2. For each subject and task:
       - Performs smoothing (if SMOOTH=true)
       - Runs statistical analysis (if STATS=true)
    3. Runs dataset-level analysis (if DATASET=true)
    4. Logs all activities to timestamped log file

REQUIREMENTS:
    - Python 3.8+
    - Docker or Apptainer
    - BIDS-compliant dataset
    - Preprocessed fMRI data (e.g., from fMRIPrep)
    - BIDS-StatsModel JSON file

EXAMPLES:
    # Run with default configuration files (config.json, container.json)
    python bidspm.py -s config.json -c container.json
    
    # Run with custom configuration files
    python bidspm.py -s my_analysis.json -c my_container.json
    
    # Run with custom model file
    python bidspm.py -s config.json -c container.json -m /path/to/my_model.json
    
    # Pilot mode: test with one random subject
    python bidspm.py -s config.json -c container.json --pilot
    
    # Run with all custom files
    python bidspm.py -s study_config.json -c docker_setup.json -m models/task_model.json
    
    # Show help
    python bidspm.py -h

LOGGING:
    Log files are automatically named with model name and timestamp:
    Example: model_task1_20250721_143022.log

MORE INFORMATION:
    GitHub: https://github.com/MRI-Lab-Graz/bidspm
    BIDS-StatsModel: https://bids-standard.github.io/stats-models/
    """
    print(help_text)


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="BIDSPM Runner - Run BIDS-StatsModel pipelines via containers",
        add_help=False  # We'll handle help manually
    )
    parser.add_argument('-h', '--help', action='store_true', 
                       help='Show help message and exit')
    parser.add_argument('-s', '--settings', '--config', 
                       help='Path to main configuration file')
    parser.add_argument('-c', '--container', '--container-config',
                       help='Path to container configuration file')
    parser.add_argument('-m', '--model', '--model-file',
                       help='Path to BIDS-StatsModel JSON file (overrides MODELS_FILE in config)')
    parser.add_argument('--pilot', action='store_true',
                       help='Pilot mode: process only one random subject for testing')
    
    return parser.parse_args()


# ------------------------------
# Main Script
# ------------------------------

def main():
    # Parse command line arguments
    args = parse_arguments()
    
    # Show help if requested
    if args.help:
        show_help()
        sys.exit(0)
    
    # If no arguments provided, show help
    if len(sys.argv) == 1:
        show_help()
        sys.exit(0)
    
    # Use specified config files or look for defaults
    config_file = args.settings if args.settings else CONFIG_FILE
    
    # Auto-select container config if not specified
    if args.container:
        container_config_file = args.container
    else:
        auto_selected = auto_select_container_config()
        container_config_file = auto_selected if auto_selected else CONTAINER_CONFIG_FILE

    # Check if configuration files exist, show help if not
    missing_files = []
    if not Path(config_file).exists():
        missing_files.append(config_file)
    if not Path(container_config_file).exists():
        missing_files.append(container_config_file)
    if missing_files:
        print("❌ Configuration files not found!")
        for f in missing_files:
            print(f"   Missing: {f}")
        print("\nPlease specify configuration files using -s and -c options, or ensure default files exist.")
        print("\n" + "="*60)
        show_help()
        sys.exit(1)

    # Dependency Checks
    check_command("python3")

    # Load configurations
    config = load_config(config_file)
    container_config = load_container_config(container_config_file)
    
    # Setup Octave compatibility for older containers
    log("🔧 Setting up Octave compatibility...")
    setup_octave_compatibility(container_config)

    # Validate MODELS_FILE or -m
    if not args.model and not config.MODELS_FILE:
        log_error("No model file specified! Please provide MODELS_FILE in config or use -m.")
    
    # Determine model file path - command line argument overrides config
    if args.model:
        model_file_path = Path(args.model)
        if not model_file_path.is_absolute():
            # If relative path, make it relative to derivatives directory
            model_file_path = config.DERIVATIVES_DIR / "models" / model_file_path
        models_file_name = model_file_path.name
    else:
        # If MODELS_FILE is absolute path, use it directly
        if config.MODELS_FILE and Path(config.MODELS_FILE).is_absolute():
            model_file_path = Path(config.MODELS_FILE)
        else:
            model_file_path = config.DERIVATIVES_DIR / "models" / config.MODELS_FILE
        models_file_name = model_file_path.name
    
    # Set up log file with model name and timestamp
    global LOG_FILE
    LOG_FILE = generate_log_filename(models_file_name)
    
    log_debug(f"Using configuration file: {config_file}")
    log_debug(f"Using container configuration: {container_config_file}")
    log_debug(f"Using model file: {model_file_path}")
    log_debug(f"Log file: {LOG_FILE}")
    
    # Check container runtime availability
    if container_config.container_type == "docker":
        check_command("docker")
        log_debug(f"Using Docker with image: {container_config.docker_image}")
    elif container_config.container_type == "apptainer":
        check_command("apptainer")
        log_debug(f"Using Apptainer with image: {container_config.apptainer_image}")

    if not model_file_path.exists():
        log_error(f"Model file '{models_file_name}' not found at '{model_file_path}'.")

    log_debug("Validating model JSON against BIDS Stats Model schema")
    run_command(["python3", "validate_bids_model.py", str(model_file_path)], capture_output=True)

    # Path validations
    if not config.WD.is_dir():
        log_error(f"Working directory '{config.WD}' does not exist.")
    if not config.BIDS_DIR.is_dir():
        log_error(f"BIDS directory '{config.BIDS_DIR}' does not exist.")
    if not config.DERIVATIVES_DIR.is_dir():
        log_error(f"Derivatives directory '{config.DERIVATIVES_DIR}' does not exist.")

    # Validate that FMRIPREP_DIR is within DERIVATIVES_DIR
    if not str(config.FMRIPREP_DIR).startswith(str(config.DERIVATIVES_DIR)):
        print(f"⚠️  WARNING: FMRIPREP_DIR ({config.FMRIPREP_DIR}) is not within DERIVATIVES_DIR ({config.DERIVATIVES_DIR})")
        print("   Container expects fmriprep at /derivatives/fmriprep inside container")


    # Processing loop
    for task in config.TASKS:
        print("---------------------------------------------------")
        print(f">>> Processing task: {task}")
        print("---------------------------------------------------")

        # Get list of subjects to process
        if args.pilot:
            # Pilot mode: use one random subject
            all_subjects = []
            if config.SUBJECTS:
                # Random from specified subjects
                all_subjects = config.SUBJECTS
            else:
                # Random from auto-discovered subjects
                for sub_dir in config.FMRIPREP_DIR.glob("sub-*"):
                    if sub_dir.is_dir():
                        subject_label = sub_dir.name.replace("sub-", "")
                        all_subjects.append(subject_label)
            if not all_subjects:
                log_error("No subjects found for pilot mode.")
            # Select random subject
            pilot_subject = random.choice(all_subjects)
            subjects_to_process = [pilot_subject]
            log_debug(f"Pilot mode: selected random subject {pilot_subject}")
            print(f">>> PILOT MODE: Processing random subject: {pilot_subject}")
        elif config.SUBJECTS:
            # Use specific subjects from config
            subjects_to_process = config.SUBJECTS
            log_debug(f"Processing specific subjects: {', '.join(subjects_to_process)}")
            print(f">>> Processing specific subjects: {', '.join(subjects_to_process)}")
        else:
            # Auto-discover all subjects from fmriprep derivatives
            subjects_to_process = []
            for sub_dir in config.FMRIPREP_DIR.glob("sub-*"):
                if sub_dir.is_dir():
                    subject_label = sub_dir.name.replace("sub-", "")
                    subjects_to_process.append(subject_label)
            log_debug(f"Auto-discovered subjects: {', '.join(subjects_to_process)}")
            print(f">>> Auto-discovered {len(subjects_to_process)} subjects")

        # Validate SPACE availability before processing
        if not validate_space_availability(config, subjects_to_process, task):
            print(f"⚠️  Skipping task '{task}' due to SPACE validation failure")
            continue

        # Process each subject
        for subject_label in subjects_to_process:
            # Check if subject directory exists in fmriprep derivatives
            subject_dir = config.FMRIPREP_DIR / f"sub-{subject_label}"
            if not subject_dir.is_dir():
                print(f">>> WARNING: Subject directory not found for {subject_label}, skipping...")
                log_debug(f"Subject directory not found: {subject_dir}")
                continue
            log_debug(f"Processing subject: {subject_label}, task: {task}")


            if config.SMOOTH:
                print(f">>> Smoothing for subject: {subject_label}, task: {task}")
                smooth_args = [
                    "/derivatives/fmriprep", "/derivatives", "subject", "smooth",
                    "--participant_label", subject_label,
                    "--task", task,
                    "--space", config.SPACE,
                    "--fwhm", str(config.FWHM),
                    "--verbosity", str(config.VERBOSITY)
                ]
                cmd = build_container_command(container_config, config, smooth_args, model_file_path)
                log_debug(f"Full container command: {' '.join(cmd)}")
                success = run_command(cmd)
                if not success:
                    print(f"⚠️  Smoothing failed for subject {subject_label}, task {task}. Continuing with next step.")
                    log_error_non_fatal(f"Smoothing failed for subject {subject_label}, task {task}")
                else:
                    print(f"✅ Smoothing completed for subject {subject_label}, task {task}")

            if config.STATS:
                print(f">>> Running stats for subject: {subject_label}, task: {task}")
                container_model_path = get_container_model_path(model_file_path, config.DERIVATIVES_DIR)
                stats_args = [
                    "/raw", "/derivatives", "subject", "stats",
                    "--preproc_dir", "/derivatives/bidspm-preproc",
                    "--model_file", container_model_path,
                    "--participant_label", subject_label,
                    "--task", task,
                    "--space", config.SPACE,
                    "--fwhm", str(config.FWHM),
                    "--verbosity", str(config.VERBOSITY)
                ]
                cmd = build_container_command(container_config, config, stats_args, model_file_path)
                success = run_command(cmd)
                if not success:
                    print(f"⚠️  Stats failed for subject {subject_label}, task {task}. Continuing with next step.")
                    log_error_non_fatal(f"Stats failed for subject {subject_label}, task {task}")
                else:
                    print(f"✅ Stats completed for subject {subject_label}, task {task}")

        if config.DATASET:
            print(f">>> Running stats on dataset: task: {task}")
            container_model_path = get_container_model_path(model_file_path, config.DERIVATIVES_DIR)
            dataset_args = [
                "/raw", "/derivatives", "dataset", "stats",
                "--preproc_dir", "/derivatives/bidspm-preproc",
                "--model_file", container_model_path,
                "--task", task,
                "--space", config.SPACE,
                "--fwhm", str(config.FWHM),
                "--verbosity", str(config.VERBOSITY)
            ]
            cmd = build_container_command(container_config, config, dataset_args, model_file_path)
            success = run_command(cmd)
            if not success:
                print(f"⚠️  Dataset stats failed for task {task}. Check logs for details.")
                log_error_non_fatal(f"Dataset stats failed for task {task}")
            else:
                print(f"✅ Dataset stats completed for task {task}")

    # Clean up old temporary directories
    cleanup_tmp_directories(config)

    print(f">>> All processing complete. Logs saved to {LOG_FILE}")


if __name__ == "__main__":
    main()
