#!/usr/bin/env python3

import json
import subprocess
import sys
import shutil
import argparse
import random
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


# ------------------------------
# Logging & Utilities
# ------------------------------

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
    except subprocess.CalledProcessError as e:
        log_error(f"Command failed: {e}")
        sys.exit(1)


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
        
        # Check if model file is inside derivatives directory
        try:
            model_file_path.relative_to(config.DERIVATIVES_DIR)
            # Model file is inside derivatives, use relative path
            relative_model_path = model_file_path.relative_to(config.DERIVATIVES_DIR)
            model_container_path = f"/derivatives/{relative_model_path}"
        except ValueError:
            # Model file is outside derivatives, mount it separately
            cmd.extend(["-v", f"{model_file_path}:/models/smdl.json"])
            model_container_path = "/models/smdl.json"
        
        cmd.append(container_config.docker_image)
        cmd.extend(args)
        return cmd
    
    elif container_config.container_type == "apptainer":
        if not container_config.apptainer_image:
            log_error("Apptainer image not specified in container configuration.")
        
        if not Path(container_config.apptainer_image).exists():
            log_error(f"Apptainer image file '{container_config.apptainer_image}' not found.")
        
        cmd = [
            "apptainer", "run",
            "--bind", f"{config.BIDS_DIR}:/raw",
            "--bind", f"{config.DERIVATIVES_DIR}:/derivatives"
        ]
        
        # Check if model file is inside derivatives directory
        try:
            model_file_path.relative_to(config.DERIVATIVES_DIR)
            # Model file is inside derivatives, use relative path
            relative_model_path = model_file_path.relative_to(config.DERIVATIVES_DIR)
            model_container_path = f"/derivatives/{relative_model_path}"
        except ValueError:
            # Model file is outside derivatives, mount it separately
            cmd.extend(["--bind", f"{model_file_path}:/models/smdl.json"])
            model_container_path = "/models/smdl.json"
        
        cmd.append(container_config.apptainer_image)
        cmd.extend(args)
        return cmd
    
    else:
        log_error(f"Unsupported container type: {container_config.container_type}")


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
        "SUBJECTS": ["01", "02", "03"]
    }
    
    Note: SUBJECTS is optional - if omitted, all subjects found will be processed

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
    container_config_file = args.container if args.container else CONTAINER_CONFIG_FILE

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
                    "--verbosity", "0"
                ]
                cmd = build_container_command(container_config, config, smooth_args, model_file_path)
                # Debug: Show the exact command being executed
                log_debug(f"Full container command: {' '.join(cmd)}")
                run_command(cmd)

            if config.STATS:
                print(f">>> Running stats for subject: {subject_label}, task: {task}")
                stats_args = [
                    "/raw", "/derivatives", "subject", "stats",
                    "--preproc_dir", "/derivatives/bidspm-preproc",
                    "--model_file", "/models/smdl.json",
                    "--participant_label", subject_label,
                    "--task", task,
                    "--space", config.SPACE,
                    "--fwhm", str(config.FWHM),
                    "--verbosity", "0"
                ]
                cmd = build_container_command(container_config, config, stats_args, model_file_path)
                run_command(cmd)

        if config.DATASET:
            print(f">>> Running stats on dataset: task: {task}")
            dataset_args = [
                "/raw", "/derivatives", "dataset", "stats",
                "--preproc_dir", "/derivatives/bidspm-preproc",
                "--model_file", "/models/smdl.json",
                "--task", task,
                "--space", config.SPACE,
                "--fwhm", str(config.FWHM),
                "--verbosity", "0"
            ]
            cmd = build_container_command(container_config, config, dataset_args, model_file_path)
            run_command(cmd)

    print(f">>> All processing complete. Logs saved to {LOG_FILE}")


if __name__ == "__main__":
    main()
