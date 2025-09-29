#!/usr/bin/env python3

from json_validator import JSONValidator
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
    MODELS_FILE: str
    TASKS: List[str]
    FMRIPREP_DIR: Path
    VERBOSITY: int
    SUBJECTS: Optional[List[str]] = None
    ROI: Optional[bool] = None
    ROI_CONFIG: Optional[dict] = None


def load_config(config_file: str) -> Config:
    """Load configuration from JSON file."""
    if not Path(config_file).exists():
        log_error(f"Config file '{config_file}' not found.")

    with open(config_file) as f:
        data = json.load(f)

    # SESSION support: if present, generate selection.json
    session = data.get("SESSION")
    if session:
        selection = {
            "bold": {
                "datatype": "func",
                "suffix": "bold",
                "ses": session
            }
        }
        # Optional: additional restrictions (e.g. run) from config
        # Example: if RUNS in config is present
        runs = data.get("RUNS")
        if runs:
            selection["bold"]["run"] = runs
        # Write selection.json to working directory
        try:
            with open("selection.json", "w") as sel_f:
                json.dump(selection, sel_f, indent=2)
            print(f"✅ selection.json generated for session {session}.")
        except Exception as e:
            print(f"⚠️  Could not write selection.json: {e}")

    # Derive paths
    wd = Path(data["WD"])
    bids_dir = Path(data["BIDS_DIR"])
    derivatives_dir = Path(data["DERIVATIVES_DIR"])
    fmriprep_dir = Path(data["FMRIPREP_DIR"])
    verbosity = data.get("VERBOSITY", 3)

    return Config(
        WD=wd,
        BIDS_DIR=bids_dir,
        DERIVATIVES_DIR=derivatives_dir,
        SPACE=data["SPACE"],
        FWHM=data["FWHM"],
        MODELS_FILE=data.get("MODELS_FILE", None),
        TASKS=data["TASKS"],
        FMRIPREP_DIR=fmriprep_dir,
        VERBOSITY=verbosity,
        SUBJECTS=data.get("SUBJECTS"),  # Optional field, defaults to None
        ROI=data.get("ROI"),
        ROI_CONFIG=data.get("ROI_CONFIG")
    )


@dataclass
class ContainerConfig:
    container_type: str  # "docker" or "apptainer"
    docker_image: str = ""
    apptainer_image: str = ""


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


def check_docker_availability():
    """Check if Docker is installed and running."""
    # First check if docker command exists
    if not shutil.which("docker"):
        log_error("Docker is required but not installed or in PATH.")
    
    # Check if Docker daemon is running
    try:
        result = subprocess.run(["docker", "info"], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            log_error("Docker is installed but not running. Please start Docker and try again.")
    except subprocess.TimeoutExpired:
        log_error("Docker command timed out. Docker daemon may not be running.")
    except Exception as e:
        log_error(f"Failed to check Docker status: {e}")


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


def check_local_bidspm_installation():
    """Check if local BIDSPM installation is available"""
    try:
        # Check if bidspm command is available
        result = subprocess.run(["bidspm", "--help"], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("✅ Local BIDSPM CLI found")
            return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    # Check if local BIDSPM directory exists
    local_bidspm_dir = Path("bidspm_local")
    if local_bidspm_dir.exists():
        print("✅ Local BIDSPM directory found")
        return True
    
    print("❌ Local BIDSPM installation not found")
    print("   Run: ./setup.sh --local-install")
    return False


def run_local_bidspm(config: Config, action: str, subjects: List[str], task: str, model_file_path: Path):
    """Execute BIDSPM locally using the CLI or direct Python call"""
    print(f"🔧 Running BIDSPM locally for action: {action}")
    
    # Check if local installation is available
    if not check_local_bidspm_installation():
        log_error("Local BIDSPM installation not found. Use containers or run: ./setup.sh --local-install")
        return False
    
    # For now, use direct MATLAB/Octave approach since CLI has issues
    return run_local_bidspm_direct(config, action, subjects, task, model_file_path)


def run_local_bidspm_direct(config: Config, action: str, subjects: List[str], task: str, model_file_path: Path):
    """Execute BIDSPM directly using MATLAB/Octave"""
    print(f"🔧 Running BIDSPM directly using MATLAB/Octave for action: {action}")
    
    # Check if MATLAB or Octave is available
    matlab_cmd = None
    if shutil.which("matlab"):
        matlab_cmd = "matlab"
    elif shutil.which("octave"):
        matlab_cmd = "octave"
    else:
        print("❌ Neither MATLAB nor Octave found in PATH")
        print("   Local BIDSPM requires MATLAB or Octave to be installed and available")
        print("   Alternatives:")
        print("   1. Install MATLAB or Octave and add to PATH")
        print("   2. Use container execution (remove --local flag)")
        print("   3. If MATLAB/Octave is installed elsewhere, create symlinks in PATH")
        return False
    
    success = True
    local_bidspm_dir = Path("bidspm_local")
    
    for subject in subjects:
        try:
            print(f">>> Local {action} for subject: {subject}, task: {task}")
            
            if action == "smooth":
                # Create MATLAB/Octave script for smoothing
                script_content = f"""
% BIDSPM Local Execution Script for Smoothing
% HPC-compatible setup with SPM12 and BIDSPM paths

% Configure local package installation directory to avoid disk space issues
if exist('pkg', 'builtin')
    pkg('prefix', fullfile(pwd, 'octave_packages'), fullfile(pwd, 'octave_packages'));
    fprintf('Octave package directory set to local folder\\n');
end

% Add SPM12 standalone if available
spm12_path = fullfile(pwd, 'spm12_standalone');
if exist(spm12_path, 'dir')
    addpath(spm12_path);
    fprintf('SPM12 standalone added to path\\n');
end

% Add BIDSPM to path and initialize
addpath('{local_bidspm_dir.absolute()}');
bidspm('init');

try
    bidspm('{config.FMRIPREP_DIR}', ...
           '{config.DERIVATIVES_DIR}', ...
           'subject', ...
           'action', 'smooth', ...
           'participant_label', {{'{subject}'}}, ...
           'task', {{'{task}'}}, ...
           'space', {{'{config.SPACE}'}}, ...
           'fwhm', {config.FWHM}, ...
           'verbosity', {config.VERBOSITY});
    fprintf('✅ Smoothing completed successfully\\n');
    exit(0);
catch ME
    fprintf('❌ Error during smoothing: %s\\n', ME.message);
    exit(1);
end
"""
            elif action == "stats":
                # Create MATLAB/Octave script for stats
                script_content = f"""
% BIDSPM Local Execution Script for Stats
% HPC-compatible setup with SPM12 and BIDSPM paths

% Configure local package installation directory to avoid disk space issues
if exist('pkg', 'builtin')
    pkg('prefix', fullfile(pwd, 'octave_packages'), fullfile(pwd, 'octave_packages'));
    fprintf('Octave package directory set to local folder\\n');
end

% Add SPM12 standalone if available
spm12_path = fullfile(pwd, 'spm12_standalone');
if exist(spm12_path, 'dir')
    addpath(spm12_path);
    fprintf('SPM12 standalone added to path\\n');
end

% Add BIDSPM to path and initialize
addpath('{local_bidspm_dir.absolute()}');
bidspm('init');

try
    bidspm('{config.BIDS_DIR}', ...
           '{config.DERIVATIVES_DIR}', ...
           'subject', ...
           'action', 'stats', ...
           'participant_label', {{'{subject}'}}, ...
           'task', {{'{task}'}}, ...
           'space', {{'{config.SPACE}'}}, ...
           'fwhm', {config.FWHM}, ...
           'model_file', '{model_file_path.absolute()}', ...
           'verbosity', {config.VERBOSITY});
    fprintf('✅ Stats completed successfully\\n');
    exit(0);
catch ME
    fprintf('❌ Error during stats: %s\\n', ME.message);
    exit(1);
end
"""
            elif action == "dataset":
                # Create MATLAB/Octave script for dataset level stats
                script_content = f"""
% BIDSPM Local Execution Script for Dataset Stats
% HPC-compatible setup with SPM12 and BIDSPM paths

% Configure local package installation directory to avoid disk space issues
if exist('pkg', 'builtin')
    pkg('prefix', fullfile(pwd, 'octave_packages'), fullfile(pwd, 'octave_packages'));
    fprintf('Octave package directory set to local folder\\n');
end

% Add SPM12 standalone if available
spm12_path = fullfile(pwd, 'spm12_standalone');
if exist(spm12_path, 'dir')
    addpath(spm12_path);
    fprintf('SPM12 standalone added to path\\n');
end

% Add BIDSPM to path and initialize
addpath('{local_bidspm_dir.absolute()}');
bidspm('init');

try
    bidspm('{config.BIDS_DIR}', ...
           '{config.DERIVATIVES_DIR}', ...
           'dataset', ...
           'action', 'stats', ...
           'task', {{'{task}'}}, ...
           'space', {{'{config.SPACE}'}}, ...
           'fwhm', {config.FWHM}, ...
           'model_file', '{model_file_path.absolute()}', ...
           'verbosity', {config.VERBOSITY});
    fprintf('✅ Dataset stats completed successfully\\n');
    exit(0);
catch ME
    fprintf('❌ Error during dataset stats: %s\\n', ME.message);
    exit(1);
end
"""
            else:
                print(f"❌ Unsupported action: {action}")
                success = False
                continue
            
            # Write script to temporary file
            script_file = Path(f"bidspm_local_{action}_{subject}_{task}.m")
            script_file.write_text(script_content)
            
            try:
                # Execute MATLAB/Octave script
                if matlab_cmd == "matlab":
                    cmd = ["matlab", "-nodisplay", "-nosplash", "-nodesktop", "-r", f"run('{script_file.stem}')"]
                else:  # octave
                    cmd = ["octave", "--no-gui", "--eval", f"run('{script_file.stem}')"]
                
                log_debug(f"Local BIDSPM command: {' '.join(cmd)}")
                
                result = subprocess.run(cmd, check=True, text=True, 
                                      capture_output=True, timeout=1800)  # 30 minute timeout
                
                print(f"✅ Local {action} completed successfully for subject {subject}")
                
            finally:
                # Clean up script file
                if script_file.exists():
                    script_file.unlink()
                
        except subprocess.CalledProcessError as e:
            log_error_non_fatal(f"Local {action} failed for subject {subject}: {e}")
            if e.stdout:
                print(f"STDOUT: {e.stdout}")
            if e.stderr:
                print(f"STDERR: {e.stderr}")
            success = False
        except subprocess.TimeoutExpired:
            log_error_non_fatal(f"Local {action} timed out for subject {subject}")
            success = False
        except Exception as e:
            log_error_non_fatal(f"Error running local {action} for subject {subject}: {e}")
            success = False
    
    return success


def setup_local_environment():
    """Setup environment for local BIDSPM execution"""
    print("🔧 Setting up local BIDSPM environment...")
    
    # Check for MATLAB/Octave
    matlab_available = shutil.which("matlab") is not None
    octave_available = shutil.which("octave") is not None
    mcr_available = Path("/usr/local/freesurfer/MCRv97").exists()
    
    if matlab_available:
        print("✅ MATLAB found in PATH")
    elif octave_available:
        print("✅ Octave found in PATH")
    elif mcr_available:
        print("✅ MATLAB Compiler Runtime found")
        print("   (Advanced: Compiled MATLAB applications can run with MCR)")
    else:
        print("⚠️  No MATLAB, Octave, or MCR found")
        print("   Local BIDSPM execution options:")
        print("   1. Install Octave: sudo apt-get install octave (recommended)")
        print("   2. Load Octave module if on HPC: module load octave")
        print("   3. Use container execution instead (remove --local flag)")
        
        # Check if this might be an HPC environment
        if Path("/etc/modulefiles").exists() or Path("/usr/share/modules").exists():
            print("   HPC detected: Try 'module avail octave' or 'module avail matlab'")
        
        return False
    
    # Check for SPM12 standalone
    spm12_dir = Path("spm12_standalone")
    if spm12_dir.exists():
        print(f"✅ SPM12 standalone found at {spm12_dir}")
    else:
        print("⚠️  SPM12 standalone not found (will be downloaded if needed)")
    
    # Check if local BIDSPM is properly installed
    return check_local_bidspm_installation()


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

    # Create the octave_init.m file that is referenced by OCTAVE_INIT_FILE
    cat > /tmp/octave_init.m << 'EOF'
% Custom Octave initialization file for BIDSPM
warning('off', 'all');

% Add BIDSPM paths
addpath('/home/neuro/bidspm');
addpath('/home/neuro/bidspm/lib/CPP_ROI');
addpath('/home/neuro/bidspm/lib/CPP_ROI/atlas');
addpath('/opt/spm12');

% Try to initialize bidspm if the function exists
if exist('/home/neuro/bidspm/bidspm.m', 'file')
    fprintf('Initializing BIDSPM...\\n');
    try
        bidspm_init = true;
    catch
        fprintf('Warning: Could not initialize BIDSPM\\n');
        bidspm_init = false;
    end
else
    fprintf('Warning: bidspm.m not found in expected location\\n');
    bidspm_init = false;
end

fprintf('🔧 Octave init completed\\n');
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


def build_container_command(container_config: ContainerConfig, config: Config, args: List[str], model_file_path: Path) -> tuple[List[str], str]:
    """Build container command based on container type (docker or apptainer)
    
    Returns:
        tuple: (container_command, model_file_container_path)
    """
    
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
            rel_path = model_file_path.relative_to(config.DERIVATIVES_DIR)
            # Model file is inside derivatives, use relative path - no additional volume mount needed
            model_container_path = f"/derivatives/{rel_path}"
        except ValueError:
            # Model file is outside derivatives, mount it separately
            cmd.extend(["-v", f"{model_file_path}:/models/smdl.json"])
            model_container_path = "/models/smdl.json"
        
        # Set environment variables for better container isolation
        cmd.extend([
            "-e", "HOME=/tmp",
            "-e", "TMPDIR=/tmp",
            "-e", "TMP=/tmp",
            "-e", "SPM_HTML_BROWSER=0",   # Disable SPM browser for headless operation
            "-e", "BIDSPM_IGNORE_FIELDMAPS=1",  # Skip fieldmap processing (not needed for smoothing)
            "-e", "BIDSPM_IGNORE_FIGURES=1",   # Skip HTML/SVG files processing
            "-e", "BIDSPM_SKIP_INTENDEDFOR_CHECK=1"  # Skip IntendedFor validation (irrelevant post-fMRIPrep)
        ])

        cmd.append(container_config.docker_image)
        cmd.extend(args)
        return cmd, model_container_path
    
    elif container_config.container_type == "apptainer":
        if not container_config.apptainer_image:
            log_error("Apptainer image not specified in container configuration.")
        
        # Check if it's a docker:// URL or local .sif file
        if not container_config.apptainer_image.startswith("docker://") and not Path(container_config.apptainer_image).exists():
            log_error(f"Apptainer image file '{container_config.apptainer_image}' not found.")
        
        cmd = [
            "apptainer", "run",
            "--writable-tmpfs",  # Allow writing to /tmp and other temp locations
            "--bind", f"{config.BIDS_DIR}:/raw",
            "--bind", f"{config.DERIVATIVES_DIR}:/derivatives"
        ]
        
        # Check if model file is inside derivatives directory
        try:
            rel_path = model_file_path.relative_to(config.DERIVATIVES_DIR)
            # Model file is inside derivatives, use relative path - no additional bind needed
            model_container_path = f"/derivatives/{rel_path}"
        except ValueError:
            # Model file is outside derivatives, mount it separately
            cmd.extend(["--bind", f"{model_file_path}:/models/smdl.json"])
            model_container_path = "/models/smdl.json"
        
        # Create and mount a dedicated tmp directory for this run
        run_tmp_dir = config.WD / "tmp" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"
        run_tmp_dir.mkdir(parents=True, exist_ok=True)
        
        # Create a custom Octave wrapper script in the tmp directory
        octave_wrapper = run_tmp_dir / "octave_wrapper.sh"
        octave_wrapper_content = f"""#!/bin/bash
# Octave wrapper to ensure BIDSPM paths are available
export MATLABPATH="/home/neuro/bidspm:/home/neuro/bidspm/lib/CPP_ROI:/home/neuro/bidspm/lib/CPP_ROI/atlas:/opt/spm12:$MATLABPATH"

# Copy ALL the atlas-related functions to tmp to fix path resolution issues
mkdir -p /tmp/atlas_functions
cp /home/neuro/bidspm/lib/CPP_ROI/atlas/*.m /tmp/atlas_functions/ 2>/dev/null || true
cp /home/neuro/bidspm/lib/CPP_ROI/src/atlas/*.m /tmp/atlas_functions/ 2>/dev/null || true

# Create init file to add paths and fix function resolution
cat > /tmp/octave_init_runtime.m << 'EOF'
% Runtime Octave initialization for BIDSPM
warning('off', 'all');
addpath('/tmp/atlas_functions');  % Add copied functions first
addpath('/tmp');  
addpath('/home/neuro/bidspm');
addpath('/home/neuro/bidspm/lib/CPP_ROI');
addpath('/home/neuro/bidspm/lib/CPP_ROI/atlas');
addpath('/home/neuro/bidspm/lib/CPP_ROI/src');
addpath('/home/neuro/bidspm/lib/CPP_ROI/src/atlas');
addpath('/opt/spm12');
fprintf('Runtime paths added with atlas functions copied\\n');
EOF

# Run octave with the init file
exec /usr/bin/octave --init-file /tmp/octave_init_runtime.m "$@"
"""
        
        with open(octave_wrapper, 'w') as f:
            f.write(octave_wrapper_content)
        octave_wrapper.chmod(0o755)
        
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
            "--env", "OCTAVE_EXECUTABLE=/tmp/octave_wrapper.sh",  # Use our custom Octave wrapper
            "--env", "MATLABPATH=/home/neuro/bidspm:/home/neuro/bidspm/lib/CPP_ROI:/home/neuro/bidspm/lib/CPP_ROI/atlas:/opt/spm12",  # Explicit MATLAB path with atlas directory
            "--env", "CPP_ROI_SKIP_ATLAS=1",  # Skip CPP_ROI atlas operations if supported
            "--env", "CPP_ROI_SKIP_ATLAS_INIT=1",  # Additional skip flag
            "--env", "CPP_ROI_ATLAS_SKIP=1",  # Another possible skip flag
            "--env", "SKIP_ATLAS_INIT=1",  # General skip flag
            "--env", "BIDSPM_IGNORE_FIELDMAPS=1",  # Skip fieldmap processing (not needed for smoothing)
            "--env", "BIDSPM_IGNORE_FIGURES=1",   # Skip HTML/SVG files processing
            "--env", "BIDSPM_SKIP_INTENDEDFOR_CHECK=1"  # Skip IntendedFor validation (irrelevant post-fMRIPrep)
        ])

        cmd.append(container_config.apptainer_image)
        cmd.extend(args)
        return cmd, model_container_path
    
    else:
        log_error(f"Unsupported container type: {container_config.container_type}")


def ensure_derivatives_dataset_description(derivatives_dir: Path):
    """Create a minimal dataset_description.json in derivatives directory to suppress BIDSPM warnings."""
    dataset_desc_file = derivatives_dir / "dataset_description.json"
    
    if not dataset_desc_file.exists():
        minimal_description = {
            "Name": "Derivatives",
            "BIDSVersion": "1.8.0",
            "DatasetType": "derivative",
            "GeneratedBy": [
                {
                    "Name": "bidspm-runner",
                    "Version": "1.0.0",
                    "Description": "Minimal dataset description to satisfy BIDS validation"
                }
            ]
        }
        
        try:
            with open(dataset_desc_file, 'w') as f:
                json.dump(minimal_description, f, indent=2)
            log_debug(f"Created minimal dataset_description.json in {derivatives_dir}")
        except Exception as e:
            log_debug(f"Could not create dataset_description.json: {e}")


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
🧠 BIDSPM Runner - BIDS-StatsModel Pipeline Tool

DESCRIPTION:
    A Python wrapper for running BIDS-StatsModel statistical pipelines using 
    containerized BIDSPM. This tool manages the entire pipeline from smoothing 
    preprocessed data to running statistical analyses at subject and group levels.

USAGE:
    python bidspm.py [OPTIONS] --action ACTION [ACTION ...]

REQUIRED ARGUMENTS:
    --action {smooth,stats,dataset}
                          Actions to perform (specify one or more):
                          • smooth  : Smooth preprocessed fMRI data
                          • stats   : Run subject-level statistical analysis
                          • dataset : Run group-level statistical analysis

OPTIONAL ARGUMENTS:
    -h, --help           Show this help message and exit
    -s, --settings       Path to configuration JSON file (default: config.json)
    -c, --container      Path to container config file (default: auto-detect)
    -m, --model          Path to BIDS-StatsModel JSON file (overrides config)
    --pilot              Test mode: process only one random subject
    --skip-modelvalidation
                         Skip validation of BIDS-StatsModel JSON
    --local              Use local BIDSPM installation instead of containers

EXAMPLES:
    # Get help and usage information
    python bidspm.py -h
    
    # Run complete pipeline (smoothing + stats + group analysis)
    python bidspm.py --action smooth stats dataset
    
    # Run only smoothing for testing
    python bidspm.py --action smooth --pilot
    
    # Use custom config and model files
    python bidspm.py -s my_config.json -m my_model.json --action smooth stats
    
    # Skip model validation (faster startup)
    python bidspm.py --action stats --skip-modelvalidation
    
    # Use local BIDSPM installation (no containers)
    python bidspm.py --local --action smooth --pilot

WORKFLOW:
    1. Validates configuration files and dependencies
    2. Auto-detects available container system (Docker/Apptainer)
    3. For each task in your config:
       • Smooth preprocessed data (if --action smooth specified)
       • Run subject-level stats (if --action stats specified)  
       • Run group-level analysis (if --action dataset specified)
    4. Cleans up temporary files and generates log reports

CONFIGURATION FILES:
    • config.json: Main settings (paths, tasks, subjects, etc.)
    • container.json: Container configuration (auto-detected if missing)
    • BIDS-StatsModel JSON: Statistical model specification

REQUIREMENTS:
    • Python 3.7+
    • Docker OR Apptainer/Singularity
    • BIDS-formatted dataset with fMRIPrep derivatives
    • Valid BIDS-StatsModel JSON file

CONFIGURATION VALIDATION:
    Your config.json is automatically validated against config_schema.json.
    If validation fails, you'll get clear error messages to fix the issues.

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


# ------------------------------
# Main Script
# ------------------------------

def main():
    # Parse command line arguments
    args = parse_arguments()
    
    # Show help if requested or if no arguments provided
    if args.help or len(sys.argv) == 1:
        show_help()
        sys.exit(0)
    
    # Check if action is provided (now that it's not required in argparse)
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
        # For local execution, container config is not required
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
        print("\n" + "="*60)
        show_help()
        sys.exit(1)
    if invalid_json_files:
        print("❌ The following configuration files are not valid JSON:")
        for f in invalid_json_files:
            print(f"   Invalid JSON: {f}")
        print("\nPlease check and fix the JSON syntax errors.")
        sys.exit(1)

    # Validate config.json against schema (if jsonschema is available)
    try:
        if not JSONValidator.validate_with_schema(config_file, "config_schema.json"):
            print("❌ config.json does not match the required schema (config_schema.json)!")
            print("   Please check your config.json and compare it to config_schema.json.")
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

    # Handle local execution
    if args.local:
        print("🔧 Using local BIDSPM installation...")
        if not setup_local_environment():
            log_error("Local BIDSPM environment setup failed. Use containers or run: ./setup.sh --local-install")
        # Skip container checks for local execution
    else:
        # Check container runtime availability
        if container_config.container_type == "docker":
            check_docker_availability()
            log_debug(f"Using Docker with image: {container_config.docker_image}")
        elif container_config.container_type == "apptainer":
            check_command("apptainer")
            log_debug(f"Using Apptainer with image: {container_config.apptainer_image}")
        
        # Setup Octave compatibility for older containers (only for container execution)
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
    if not args.local:
        log_debug(f"Using container configuration: {container_config_file}")
    else:
        log_debug("Using local BIDSPM execution (no container)")
    log_debug(f"Using model file: {model_file_path}")
    log_debug(f"Log file: {LOG_FILE}")
    
    # Handle local execution
    if args.local:
        print("🔧 Using local BIDSPM installation...")
        if not setup_local_environment():
            log_error("Local BIDSPM environment setup failed. Use containers or run: ./setup.sh --local-install")
        # Skip container checks for local execution
    else:
        # Check container runtime availability
        if container_config.container_type == "docker":
            check_docker_availability()
            log_debug(f"Using Docker with image: {container_config.docker_image}")
        elif container_config.container_type == "apptainer":
            check_command("apptainer")
            log_debug(f"Using Apptainer with image: {container_config.apptainer_image}")
        
        # Setup Octave compatibility for older containers (only for container execution)
        log("🔧 Setting up Octave compatibility...")
        setup_octave_compatibility(container_config)

    if not model_file_path.exists():
        log_error(f"Model file '{models_file_name}' not found at '{model_file_path}'.")

    if not args.skip_modelvalidation:
        log_debug("Validating model JSON against BIDS Stats Model schema")
        venv_python = Path(".bidspm/bin/python")
        python_cmd = str(venv_python) if venv_python.exists() else "python3"
        run_command([python_cmd, "validate_bids_model.py", str(model_file_path)], capture_output=True)
    else:
        print("⚠️  Skipping BIDS-StatsModel JSON validation (--skip-modelvalidation flag used)")

    # Path validations
    if not config.WD.is_dir():
        log_error(f"Working directory '{config.WD}' does not exist.")
    if not config.BIDS_DIR.is_dir():
        log_error(f"BIDS directory '{config.BIDS_DIR}' does not exist.")
    if not config.DERIVATIVES_DIR.is_dir():
        log_error(f"Derivatives directory '{config.DERIVATIVES_DIR}' does not exist.")

    # Validate that FMRIPREP_DIR is within DERIVATIVES_DIR (only relevant for containers)
    if not args.local and not str(config.FMRIPREP_DIR).startswith(str(config.DERIVATIVES_DIR)):
        print(f"⚠️  WARNING: FMRIPREP_DIR ({config.FMRIPREP_DIR}) is not within DERIVATIVES_DIR ({config.DERIVATIVES_DIR})")
        print("   Container expects fmriprep at /derivatives/fmriprep inside container")

    # Ensure derivatives directory has dataset_description.json to suppress BIDSPM warnings
    ensure_derivatives_dataset_description(config.DERIVATIVES_DIR)

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


            # ROI analysis block
            if hasattr(config, "ROI") and config.ROI:
                roi_config = config.ROI_CONFIG
                preproc_dir = config.DERIVATIVES_DIR / "bidspm-preproc"
                
                # Check if preproc directory exists
                if not preproc_dir.exists():
                    print(f"❌ Preprocessing directory not found: {preproc_dir}")
                    print("   ROI analysis requires smoothed data. Please run smoothing first using the --action smooth option.")
                    continue
                
                # Check for smoothed data for each required space
                missing_spaces = []
                for roi_space in roi_config["space"]:
                    found = False
                    for ses_dir in (preproc_dir.glob(f"sub-{subject_label}/ses-*/func") if (preproc_dir / f"sub-{subject_label}").exists() else []):
                        if any(ses_dir.glob(f"*_space-{roi_space}*.nii*")):
                            found = True
                            break
                    if not found:
                        missing_spaces.append(roi_space)
                if missing_spaces:
                    print(f"❌ Smoothed data for ROI space(s) {missing_spaces} not found in {preproc_dir}.")
                    print(f"   Please run smoothing for space(s) {missing_spaces} first using the --action smooth option and update 'SPACE' in config if needed.")
                    continue

                # Create ROI
                roi_args = [
                    "/raw", "/derivatives", "subject", "create_roi",
                    "--participant_label", subject_label,
                    "--preproc_dir", "/derivatives/bidspm-preproc",
                    "--roi_atlas", roi_config["roi_atlas"],
                    "--roi_name"
                ]
                # Add each ROI name as a separate argument
                roi_args.extend(roi_config["roi_name"])
                roi_args.extend(["--space", ",".join(roi_config["space"])])
                cmd, _ = build_container_command(container_config, config, roi_args, model_file_path)
                success = run_command(cmd)
                if not success:
                    print(f"⚠️  ROI creation failed for subject {subject_label}, task {task}.")
                    continue

                # Run ROI-based GLM
                # roi_dir is no longer needed
                temp_args = []
                _, model_container_path = build_container_command(container_config, config, temp_args, model_file_path)
                stats_args = [
                    "/raw", "/derivatives", "subject", "stats",
                    "--participant_label", subject_label,
                    "--preproc_dir", "/derivatives/bidspm-preproc",
                    "--model_file", model_container_path,
                    "--roi_based",
                    "--roi_name"
                ]
                # Add each ROI name as a separate argument  
                stats_args.extend(roi_config["roi_name"])
                stats_args.extend([
                    "--roi_dir", "/derivatives/bidspm-roi",
                    "--space", ",".join(roi_config["space"]),
                    "--fwhm", "0"
                ])
                cmd, _ = build_container_command(container_config, config, stats_args, model_file_path)
                success = run_command(cmd)
                if not success:
                    print(f"⚠️  ROI stats failed for subject {subject_label}, task {task}.")
                else:
                    print(f"✅ ROI stats completed for subject {subject_label}, task {task}")

            # Check for smoothed data for main SPACE before stats
            if 'stats' in args.action:
                main_space = config.SPACE
                found = False
                preproc_dir = config.DERIVATIVES_DIR / "bidspm-preproc"
                for ses_dir in (preproc_dir.glob(f"sub-{subject_label}/ses-*/func") if (preproc_dir / f"sub-{subject_label}").exists() else []):
                    if any(ses_dir.glob(f"*_space-{main_space}*.nii*")):
                        found = True
                        break
                if not found:
                    print(f"❌ Smoothed data for main SPACE '{main_space}' not found in {preproc_dir}. Run smoothing first!")
                    continue

            if 'smooth' in args.action:
                print(f">>> Smoothing for subject: {subject_label}, task: {task}")
                
                if args.local:
                    # Local execution
                    success = run_local_bidspm(config, "smooth", [subject_label], task, model_file_path)
                else:
                    # Container execution
                    # For smoothing, use the original fMRIPrep directory, not bidspm-preproc
                    # BIDSPM needs access to the raw fMRIPrep output for smoothing
                    fmriprep_source = config.DERIVATIVES_DIR / "fmriprep"
                    if not fmriprep_source.exists():
                        print(f"⚠️  fMRIPrep directory not found at {fmriprep_source}")
                        print(f"   Current FMRIPREP_DIR setting: {config.FMRIPREP_DIR}")
                        print("   For smoothing, BIDSPM needs the original fMRIPrep output")
                    
                    smooth_args = [
                        "/derivatives/fmriprep", "/derivatives", "subject", "smooth",
                        "--participant_label", subject_label,
                        "--task", task,
                        "--space", config.SPACE,
                        "--fwhm", str(config.FWHM),
                        "--verbosity", str(max(0, config.VERBOSITY - 1))  # Reduce verbosity to minimize warnings
                    ]
                    cmd, _ = build_container_command(container_config, config, smooth_args, model_file_path)
                    log_debug(f"Full container command: {' '.join(cmd)}")
                    success = run_command(cmd)
                
                if not success:
                    print(f"⚠️  Smoothing failed for subject {subject_label}, task {task}. Continuing with next step.")
                    log_error_non_fatal(f"Smoothing failed for subject {subject_label}, task {task}")
                else:
                    print(f"✅ Smoothing completed for subject {subject_label}, task {task}")

            if 'stats' in args.action:
                print(f">>> Running stats for subject: {subject_label}, task: {task}")
                
                if args.local:
                    # Local execution
                    success = run_local_bidspm(config, "stats", [subject_label], task, model_file_path)
                else:
                    # Container execution
                    # First build container command to get the correct model file path
                    temp_args = []
                    cmd, model_container_path = build_container_command(container_config, config, temp_args, model_file_path)
                    stats_args = [
                        "/raw", "/derivatives", "subject", "stats",
                        "--preproc_dir", "/derivatives/bidspm-preproc",
                        "--model_file", model_container_path,
                        "--participant_label", subject_label,
                        "--task", task,
                        "--space", config.SPACE,
                        "--fwhm", str(config.FWHM),
                        "--verbosity", str(config.VERBOSITY)
                    ]
                    cmd, _ = build_container_command(container_config, config, stats_args, model_file_path)
                    success = run_command(cmd)
                
                if not success:
                    print(f"⚠️  Stats failed for subject {subject_label}, task {task}. Continuing with next step.")
                    log_error_non_fatal(f"Stats failed for subject {subject_label}, task {task}")
                else:
                    print(f"✅ Stats completed for subject {subject_label}, task {task}")

        if 'dataset' in args.action:
            print(f">>> Running stats on dataset: task: {task}")
            
            if args.local:
                # Local execution - run for all subjects at dataset level
                all_subjects = []
                if config.SUBJECTS:
                    all_subjects = config.SUBJECTS
                else:
                    # Auto-discover all subjects
                    for sub_dir in config.FMRIPREP_DIR.glob("sub-*"):
                        if sub_dir.is_dir():
                            subject_label = sub_dir.name.replace("sub-", "")
                            all_subjects.append(subject_label)
                
                success = run_local_bidspm(config, "dataset", all_subjects, task, model_file_path)
            else:
                # Container execution
                # First build container command to get the correct model file path
                temp_args = []
                cmd, model_container_path = build_container_command(container_config, config, temp_args, model_file_path)
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
                print(f"⚠️  Dataset stats failed for task {task}. Check logs for details.")
                log_error_non_fatal(f"Dataset stats failed for task {task}")
            else:
                print(f"✅ Dataset stats completed for task {task}")

    # Clean up old temporary directories
    cleanup_tmp_directories(config)

    print(f">>> All processing complete. Logs saved to {LOG_FILE}")


if __name__ == "__main__":
    main()
