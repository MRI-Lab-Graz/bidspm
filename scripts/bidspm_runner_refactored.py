#!/usr/bin/env python3
"""
BIDSPM Runner - Refactored Main Script
A Python wrapper for running BIDS-StatsModel statistical pipelines using containerized BIDSPM.
"""

import argparse
import random
import sys
from pathlib import Path

# Add repo root to path for imports
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import validation module first (used by config)
from docs.json_validator import JSONValidator

# Import all refactored modules
from modules.config import (
    Config, ContainerConfig, 
    load_config, load_container_config, auto_select_container_config
)
from modules.logging_utils import (
    log, log_debug, log_error, log_error_non_fatal, 
    generate_log_filename, set_log_file
)
from modules.validation import (
    validate_space_availability, ensure_derivatives_dataset_description
)
from modules.environment import (
    check_command, check_docker_availability, setup_local_environment, 
    setup_octave_compatibility
)
from modules.local_runner import run_local_bidspm
from modules.container_runner import build_container_command
from modules.runner_utils import run_command, cleanup_tmp_directories

# Configuration constants
CONFIG_FILE = "config/config.json"
CONTAINER_CONFIG_FILE = "containers/container.json"


def show_help():
    """Display help information for BIDSPM Runner"""
    help_text = """
🧠 BIDSPM Runner - BIDS-StatsModel Pipeline Tool

DESCRIPTION:
    A Python wrapper for running BIDS-StatsModel statistical pipelines using 
    containerized BIDSPM. This tool manages the entire pipeline from smoothing 
    preprocessed data to running statistical analyses at subject and group levels.

USAGE:
    python bidspm_runner.py [OPTIONS] --action ACTION [ACTION ...]

REQUIRED ARGUMENTS:
    --action {smooth,stats,dataset}
                          Actions to perform (specify one or more):
                          • smooth  : Smooth preprocessed fMRI data
                          • stats   : Run subject-level statistical analysis
                          • dataset : Run group-level statistical analysis

OPTIONAL ARGUMENTS:
    -h, --help           Show this help message and exit
    -s, --settings       Path to configuration JSON file (default: config/config.json)
    -c, --container      Path to container config file (default: auto-detect)
    -m, --model          Path to BIDS-StatsModel JSON file (overrides config)
    --pilot              Test mode: process only one random subject
    --skip-modelvalidation
                         Skip validation of BIDS-StatsModel JSON
    --local              Use local BIDSPM installation instead of containers

EXAMPLES:
    # Get help and usage information
    python bidspm_runner.py -h
    
    # Run complete pipeline (smoothing + stats + group analysis)
    python bidspm_runner.py --action smooth stats dataset
    
    # Run only smoothing for testing
    python bidspm_runner.py --action smooth --pilot
    
    # Use custom config and model files
    python bidspm_runner.py -s config/my_config.json -m my_model.json --action smooth stats
    
    # Skip model validation (faster startup)
    python bidspm_runner.py --action stats --skip-modelvalidation
    
    # Use local BIDSPM installation (no containers)
    python bidspm_runner.py --local --action smooth --pilot

WORKFLOW:
    1. Validates configuration files and dependencies
    2. Auto-detects available container system (Docker/Apptainer)
    3. For each task in your config:
       • Smooth preprocessed data (if --action smooth specified)
       • Run subject-level stats (if --action stats specified)  
       • Run group-level analysis (if --action dataset specified)
    4. Cleans up temporary files and generates log reports

CONFIGURATION FILES:
    • config/config.json: Main settings (paths, tasks, subjects, etc.)
    • containers/container.json: Container configuration (auto-detected if missing)
    • BIDS-StatsModel JSON: Statistical model specification

REQUIREMENTS:
    • Python 3.7+
    • Docker OR Apptainer/Singularity
    • BIDS-formatted dataset with fMRIPrep derivatives
    • Valid BIDS-StatsModel JSON file

MORE INFORMATION:
    • GitHub: https://github.com/MRI-Lab-Graz/bidspm
    • BIDS-StatsModel: https://bids-standard.github.io/stats-models/
    • Documentation: Check README.md for detailed setup instructions
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
    parser.add_argument('--skip-modelvalidation', action='store_true',
                       help='Skip BIDS-StatsModel JSON validation')
    parser.add_argument('--local', action='store_true',
                       help='Use local BIDSPM installation instead of containers')
    parser.add_argument('--action', nargs='+', choices=['smooth', 'stats', 'dataset'],
                       help='Actions to perform: smooth, stats, dataset (at least one required)')
    return parser.parse_args()


def main():
    """Main orchestration function"""
    # Parse command line arguments
    args = parse_arguments()
    
    # Show help if requested or if no arguments provided
    if args.help or len(sys.argv) == 1:
        show_help()
        sys.exit(0)
    
    # Check if action is provided
    if not args.action:
        print("❌ Error: --action argument is required")
        print("   Please specify at least one action: smooth, stats, dataset")
        print("\nUse --help for more information\n")
        show_help()
        sys.exit(1)
    
    # Use specified config files or look for defaults
    config_file = args.settings if args.settings else CONFIG_FILE

    # Auto-select container config if not specified (only needed for container execution)
    if not args.local:
        if args.container:
            container_config_file = args.container
        else:
            auto_selected = auto_select_container_config()
            container_config_file = auto_selected if auto_selected else CONTAINER_CONFIG_FILE
    else:
        container_config_file = None

    # Check if configuration files exist and are valid JSON
    missing_files = []
    invalid_json_files = []
    
    if not Path(config_file).exists():
        missing_files.append(config_file)
    elif not JSONValidator.is_valid_json(config_file):
        invalid_json_files.append(config_file)
    
    # Only check container config if not using local execution
    if not args.local and container_config_file:
        if not Path(container_config_file).exists():
            missing_files.append(container_config_file)
        elif not JSONValidator.is_valid_json(container_config_file):
            invalid_json_files.append(container_config_file)
    
    if missing_files:
        print("❌ Configuration files not found!")
        for f in missing_files:
            print(f"   Missing: {f}")
        print("\nPlease specify configuration files using -s and -c options, or ensure default files exist.")
        sys.exit(1)
    
    if invalid_json_files:
        print("❌ The following configuration files are not valid JSON:")
        for f in invalid_json_files:
            print(f"   Invalid JSON: {f}")
        print("\nPlease check and fix the JSON syntax errors.")
        sys.exit(1)

    # Validate config file against schema
    try:
        if not JSONValidator.validate_with_schema(config_file, "config/config_schema.json"):
            print(f"❌ {config_file} does not match the required schema!")
            sys.exit(1)
    except ImportError:
        print("⚠️  Skipping schema validation: jsonschema package is not installed.")

    # Dependency Checks
    check_command("python3")

    # Load configurations
    config = load_config(config_file)
    
    # Only load container config if not using local execution
    if not args.local:
        container_config = load_container_config(container_config_file)
    else:
        container_config = None

    # Handle local vs container execution setup
    if args.local:
        print("🔧 Using local BIDSPM installation...")
        if not setup_local_environment():
            log_error("Local BIDSPM environment setup failed. Use containers or run: ./setup.sh --local-install")
    else:
        # Check container runtime availability
        if container_config.container_type == "docker":
            check_docker_availability()
            log_debug(f"Using Docker with image: {container_config.docker_image}")
        elif container_config.container_type == "apptainer":
            check_command("apptainer")
            log_debug(f"Using Apptainer with image: {container_config.apptainer_image}")
        
        # Setup Octave compatibility for containers
        log("🔧 Setting up Octave compatibility...")
        setup_octave_compatibility(container_config)

    # Determine model file path
    model_file_path = None
    models_file_name = "unknown"
    needs_model = 'stats' in args.action or 'dataset' in args.action
    
    if args.model or config.MODELS_FILE:
        if args.model:
            model_file_path = Path(args.model)
            if not model_file_path.is_absolute():
                model_file_path = config.DERIVATIVES_DIR / "models" / model_file_path
            models_file_name = model_file_path.name
        elif config.MODELS_FILE:
            if Path(config.MODELS_FILE).is_absolute():
                model_file_path = Path(config.MODELS_FILE)
            else:
                model_file_path = config.DERIVATIVES_DIR / "models" / config.MODELS_FILE
            models_file_name = model_file_path.name
    
    if needs_model and not model_file_path:
        log_error("No model file specified! Please provide MODELS_FILE in config or use -m for 'stats' action.")

    # Set up log file with model name and timestamp
    log_file = generate_log_filename(models_file_name)
    set_log_file(log_file)

    log_debug(f"Using configuration file: {config_file}")
    if not args.local:
        log_debug(f"Using container configuration: {container_config_file}")
    else:
        log_debug("Using local BIDSPM execution (no container)")
    
    if model_file_path:
        log_debug(f"Using model file: {model_file_path}")
    log_debug(f"Log file: {log_file}")
    
    # Validate model file exists if we need it
    if needs_model:
        if not model_file_path.exists():
            log_error(f"Model file '{models_file_name}' not found at '{model_file_path}'.")

        if not args.skip_modelvalidation:
            log_debug("Validating model JSON against BIDS Stats Model schema")
            venv_python = Path(".bidspm/bin/python")
            python_cmd = str(venv_python) if venv_python.exists() else "python3"
            run_command([python_cmd, "docs/validate_bids_model.py", str(model_file_path)], capture_output=True)
        else:
            print("⚠️  Skipping BIDS-StatsModel JSON validation (--skip-modelvalidation flag used)")

    # Path validations
    if not config.WD.is_dir():
        log_error(f"Working directory '{config.WD}' does not exist.")
    if not config.BIDS_DIR.is_dir():
        log_error(f"BIDS directory '{config.BIDS_DIR}' does not exist.")
    if not config.DERIVATIVES_DIR.is_dir():
        log_error(f"Derivatives directory '{config.DERIVATIVES_DIR}' does not exist.")

    # Ensure derivatives directory has dataset_description.json
    ensure_derivatives_dataset_description(config.DERIVATIVES_DIR)

    try:
        # Determine subjects to process
        subjects_to_process = _determine_subjects(config, args.pilot)
        
        if not subjects_to_process:
            print("❌ No subjects found to process.")
            return

        # Process each task
        for task in config.TASKS:
            print("---------------------------------------------------")
            print(f">>> Processing task: {task}")
            print("---------------------------------------------------")

            # Validate SPACE availability before processing
            if not validate_space_availability(config, subjects_to_process, task):
                print(f"⚠️  Skipping task '{task}' due to SPACE validation failure")
                continue

            # Process each subject for this task
            _process_subjects_for_task(config, container_config, args, subjects_to_process, 
                                      task, model_file_path)
            
            # Run dataset-level analysis if requested
            if 'dataset' in args.action:
                _process_dataset_level(config, container_config, args, task, model_file_path)

    except KeyboardInterrupt:
        print("\n\n🛑 Process interrupted by user. Exiting...")
        sys.exit(1)

    # Clean up old temporary directories
    cleanup_tmp_directories(config)

    print(f">>> All processing complete. Logs saved to {log_file}")


def _determine_subjects(config: Config, pilot_mode: bool):
    """Determine which subjects to process"""
    subjects_to_process = []
    
    if pilot_mode:
        # Pilot mode: use one random subject
        all_subjects = []
        if config.SUBJECTS:
            all_subjects = config.SUBJECTS
        else:
            # Auto-discover subjects
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
        print(f">>> PILOT MODE: Selected random subject: {pilot_subject}")
        
    elif config.SUBJECTS:
        # Use specific subjects from config
        subjects_to_process = config.SUBJECTS
        log_debug(f"Processing specific subjects: {', '.join(subjects_to_process)}")
        print(f">>> Processing specific subjects: {', '.join(subjects_to_process)}")
        
    else:
        # Auto-discover all subjects from fmriprep derivatives
        for sub_dir in config.FMRIPREP_DIR.glob("sub-*"):
            if sub_dir.is_dir():
                subject_label = sub_dir.name.replace("sub-", "")
                subjects_to_process.append(subject_label)
        log_debug(f"Auto-discovered subjects: {', '.join(subjects_to_process)}")
        print(f">>> Auto-discovered {len(subjects_to_process)} subjects")
    
    return subjects_to_process


def _process_subjects_for_task(config, container_config, args, subjects, task, model_file_path):
    """Process all subjects for a given task"""
    for subject_label in subjects:
        # Check if subject directory exists
        subject_dir = config.FMRIPREP_DIR / f"sub-{subject_label}"
        if not subject_dir.is_dir():
            print(f">>> WARNING: Subject directory not found for {subject_label}, skipping...")
            log_debug(f"Subject directory not found: {subject_dir}")
            continue
        
        log_debug(f"Processing subject: {subject_label}, task: {task}")

        # 1. Smoothing (if requested)
        if 'smooth' in args.action:
            _run_smoothing(config, container_config, args.local, subject_label, task, model_file_path)

        # 2. ROI analysis (if configured)
        if hasattr(config, "ROI") and config.ROI:
            _run_roi_analysis(config, container_config, subject_label, task, model_file_path)

        # 3. Stats (if requested)
        if 'stats' in args.action:
            _run_stats(config, container_config, args.local, subject_label, task, model_file_path)


def _run_smoothing(config, container_config, use_local, subject, task, model_file_path):
    """Run smoothing for a subject"""
    print(f">>> Smoothing for subject: {subject}, task: {task}")
    
    if use_local:
        success = run_local_bidspm(config, "smooth", [subject], task, model_file_path)
    else:
        # Container execution
        try:
            fmriprep_rel = config.FMRIPREP_DIR.relative_to(config.DERIVATIVES_DIR)
            fmriprep_container_path = f"/derivatives/{fmriprep_rel}"
        except ValueError:
            fmriprep_container_path = "/derivatives/fmriprep"
        
        smooth_args = [
            fmriprep_container_path, "/derivatives", "subject", "smooth",
            "--participant_label", subject,
            "--task", task,
            "--space", config.SPACE,
            "--fwhm", str(config.FWHM),
            "--verbosity", str(max(0, config.VERBOSITY - 1))
        ]
        cmd, _ = build_container_command(container_config, config, smooth_args, model_file_path)
        log_debug(f"Full container command: {' '.join(cmd)}")
        success = run_command(cmd)
    
    if not success:
        print(f"⚠️  Smoothing failed for subject {subject}, task {task}.")
        log_error_non_fatal(f"Smoothing failed for subject {subject}, task {task}")
    else:
        print(f"✅ Smoothing completed for subject {subject}, task {task}")


def _run_stats(config, container_config, use_local, subject, task, model_file_path):
    """Run stats for a subject"""
    # Check for smoothed data
    main_space = config.SPACE
    found = False
    preproc_dir = config.DERIVATIVES_DIR / "bidspm-preproc"
    
    for ses_dir in (preproc_dir.glob(f"sub-{subject}/ses-*/func") if (preproc_dir / f"sub-{subject}").exists() else []):
        if any(ses_dir.glob(f"*_space-{main_space}*.nii*")):
            found = True
            break
    
    if not found:
        print(f"❌ Smoothed data for SPACE '{main_space}' not found. Run smoothing first!")
        return
    
    print(f">>> Running stats for subject: {subject}, task: {task}")
    
    if use_local:
        success = run_local_bidspm(config, "stats", [subject], task, model_file_path)
    else:
        # Container execution
        temp_args = []
        _, model_container_path = build_container_command(container_config, config, temp_args, model_file_path)
        
        stats_args = [
            "/raw", "/derivatives", "subject", "stats",
            "--participant_label", subject,
            "--task", task,
            "--space", config.SPACE,
            "--preproc_dir", "/derivatives/bidspm-preproc",
            "--model_file", model_container_path,
            "--fwhm", str(config.FWHM),
            "--verbosity", str(config.VERBOSITY)
        ]
        cmd, _ = build_container_command(container_config, config, stats_args, model_file_path)
        success = run_command(cmd)
    
    if not success:
        print(f"⚠️  Stats failed for subject {subject}, task {task}.")
        log_error_non_fatal(f"Stats failed for subject {subject}, task {task}")
    else:
        print(f"✅ Stats completed for subject {subject}, task {task}")


def _run_roi_analysis(config, container_config, subject, task, model_file_path):
    """Run ROI analysis for a subject (container only for now)"""
    roi_config = config.ROI_CONFIG
    preproc_dir = config.DERIVATIVES_DIR / "bidspm-preproc"
    
    if not preproc_dir.exists():
        print(f"❌ Preprocessing directory not found: {preproc_dir}")
        return
    
    # Create ROI and run stats (implementation depends on container execution)
    print(f">>> Running ROI analysis for subject: {subject}, task: {task}")
    # ... ROI analysis implementation ...


def _process_dataset_level(config, container_config, args, task, model_file_path):
    """Process dataset-level analysis"""
    print(f">>> Running stats on dataset: task: {task}")
    
    if args.local:
        # Local execution - determine all subjects
        all_subjects = []
        if config.SUBJECTS:
            all_subjects = config.SUBJECTS
        else:
            for sub_dir in config.FMRIPREP_DIR.glob("sub-*"):
                if sub_dir.is_dir():
                    subject_label = sub_dir.name.replace("sub-", "")
                    all_subjects.append(subject_label)
        
        success = run_local_bidspm(config, "dataset", all_subjects, task, model_file_path)
    else:
        # Container execution
        temp_args = []
        _, model_container_path = build_container_command(container_config, config, temp_args, model_file_path)
        
        dataset_args = [
            "/raw", "/derivatives", "dataset", "stats",
            "--preproc_dir", "/derivatives/bidspm-preproc",
            "--model_file", model_container_path,
            "--task", task,
            "--space", config.SPACE,
            "--fwhm", str(config.FWHM),
            "--verbosity", str(config.VERBOSITY)
        ]
        cmd, _ = build_container_command(container_config, config, dataset_args, model_file_path)
        success = run_command(cmd)
    
    if not success:
        print(f"⚠️  Dataset stats failed for task {task}.")
        log_error_non_fatal(f"Dataset stats failed for task {task}")
    else:
        print(f"✅ Dataset stats completed for task {task}")


if __name__ == "__main__":
    main()
