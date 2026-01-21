#!/usr/bin/env python3

from docs.json_validator import JSONValidator
from lib.config import Config, ContainerConfig, load_config, load_container_config
from lib.config import detect_platform_and_suggest_container, auto_select_container_config
from lib.utils import (
    log, log_debug, log_error, log_error_non_fatal,
    generate_log_filename, check_command, check_docker_availability,
    run_command, validate_space_availability,
    ensure_derivatives_dataset_description, cleanup_tmp_directories,
    get_container_model_path
)
import json
import os
import subprocess
import sys
import shutil
import argparse
import random
import re
import shlex
from pathlib import Path
from datetime import datetime
from typing import List, Optional


# ------------------------------
# Configuration
# ------------------------------

CONTAINER_CONFIG_FILE = "containers/container.json"
DEBUG = False  # Set to False to suppress debug output


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
    local_bidspm_dir = Path("local_src/bidspm_local")
    if local_bidspm_dir.exists():
        print("✅ Local BIDSPM directory found")
        return True
    
    print("❌ Local BIDSPM installation not found")
    print("   Run: ./setup.sh --local-install")
    return False


def get_local_execution_env():
    """Get environment variables for local MATLAB/Octave execution"""
    env = os.environ.copy()
    project_root = Path.cwd().absolute()
    
    # BIDSPM environment
    env["BIDSPM_PROJECT_ROOT"] = str(project_root)
    env["SPM12_PATH"] = str(project_root / "external" / "spm12_standalone")
    env["BIDSPM_PATH"] = str(project_root / "local_src" / "bidspm_local")
    env["SPM_HOME"] = env["SPM12_PATH"]
    env["SPM_STANDALONE_HOME"] = env["SPM12_PATH"]
    
    # Virtualenv bin (if it exists) to provide tools like validate_model
    venv_bin = project_root / ".bidspm" / "bin"
    if venv_bin.exists():
        env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
    
    # Octave environment
    local_octave_root = project_root / "external" / "octave"
    local_octave_bin_dir = local_octave_root / "bin"
    if local_octave_bin_dir.exists():
        env["OCTAVE_HOME"] = str(local_octave_root)
        env["PATH"] = f"{local_octave_bin_dir}:{env.get('PATH', '')}"
        
        # Library path
        local_octave_lib = local_octave_root / "lib"
        if local_octave_lib.exists():
            ld_paths = [str(local_octave_lib)]
            # Find version specific lib dir
            octave_lib_dir = local_octave_lib / "octave"
            if octave_lib_dir.exists():
                try:
                    for sub in octave_lib_dir.iterdir():
                        if sub.is_dir() and re.match(r'[0-9].*', sub.name):
                            ld_paths.append(str(sub))
                            break
                except Exception:
                    pass
            
            existing_ld_path = env.get("LD_LIBRARY_PATH", "")
            if existing_ld_path:
                env["LD_LIBRARY_PATH"] = f"{':'.join(ld_paths)}:{existing_ld_path}"
            else:
                env["LD_LIBRARY_PATH"] = ":".join(ld_paths)
    
    # Ensure Octave Forge can install if needed (or follows user preference)
    # We default to allowing it if not set, but respect existing environment
    if "BIDSPM_SKIP_OCTAVE_FORGE" not in env:
        env["BIDSPM_SKIP_OCTAVE_FORGE"] = "0"
        
    return env


def run_local_bidspm(config: Config, action: str, subjects: List[str], task: str, model_file_path: Path):
    """Execute BIDSPM locally using MATLAB/Octave directly"""
    print(f"🔧 Running BIDSPM locally for action: {action}")
    
    # Check if local installation is available
    if not check_local_bidspm_installation():
        log_error("Local BIDSPM installation not found. Use containers or run: ./setup.sh --local-install")
        return False
    
    # Use direct MATLAB/Octave execution (more reliable)
    return run_local_bidspm_direct(config, action, subjects, task, model_file_path)


def run_local_bidspm_direct(config: Config, action: str, subjects: List[str], task: str, model_file_path: Path):
    """Execute BIDSPM directly using MATLAB/Octave"""
    print(f"🔧 Running BIDSPM directly using MATLAB/Octave for action: {action}")
    
    # Get local execution environment
    local_env = get_local_execution_env()
    
    # Check if MATLAB or Octave is available
    matlab_cmd = None
    local_octave_bin = Path("external/octave/bin")
    
    # Prefer local octave-cli if it exists
    local_cli = local_octave_bin / "octave-cli"
    local_octave_wrap = local_octave_bin / "octave"
    
    if shutil.which("matlab"):
        matlab_cmd = "matlab"
    elif local_cli.exists():
        matlab_cmd = str(local_cli.absolute())
    elif local_octave_wrap.exists():
        matlab_cmd = str(local_octave_wrap.absolute())
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
    local_bidspm_dir = Path("local_src/bidspm_local")
    
    for subject in subjects:
        try:
            print(f">>> Local {action} for subject: {subject}, task: {task}")
            
            if action == "smooth":
                # Create MATLAB/Octave script for smoothing
                script_content = f"""
% BIDSPM Local Execution Script for Smoothing
% HPC-compatible setup with SPM12 and BIDSPM paths

% Set warning level to reduce verbose output
warning('off', 'all');

% Add SPM12 standalone if available
spm12_path = fullfile(pwd, 'external/spm12_standalone');
if exist(spm12_path, 'dir')
    addpath(spm12_path);
    fprintf('SPM12 standalone added to path\\n');
end

% Add BIDSPM to path and initialize
bidspm_path = '{local_bidspm_dir.absolute()}';
if exist(bidspm_path, 'dir')
    addpath(bidspm_path);
    fprintf('Initializing BIDSPM from: %s\\n', bidspm_path);
    % Initialize BIDSPM (this will load necessary packages like statistics, datatypes)
    if exist('bidspm', 'file')
        bidspm('init');
    end
end

% Try to initialize SPM if available
try
    if exist('spm', 'file')
        spm('defaults', 'fmri');
        spm_jobman('initcfg');
        fprintf('SPM initialized successfully\\n');
    end
catch
    fprintf('SPM initialization skipped\\n');
end

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

% Set warning level to reduce verbose output
warning('off', 'all');

% Add SPM12 standalone if available
spm12_path = fullfile(pwd, 'external/spm12_standalone');
if exist(spm12_path, 'dir')
    addpath(spm12_path);
    fprintf('SPM12 standalone added to path\\n');
end

% Add BIDSPM to path and initialize
bidspm_path = '{local_bidspm_dir.absolute()}';
if exist(bidspm_path, 'dir')
    addpath(bidspm_path);
    fprintf('Initializing BIDSPM from: %s\\n', bidspm_path);
    % Initialize BIDSPM (this will load necessary packages like statistics, datatypes)
    if exist('bidspm', 'file')
        bidspm('init');
    end
end

% Try to initialize SPM if available
try
    if exist('spm', 'file')
        spm('defaults', 'fmri');
        spm_jobman('initcfg');
        fprintf('SPM initialized successfully\\n');
    end
catch
    fprintf('SPM initialization skipped\\n');
end

try
    % Check for preproc dir
    preproc_dir = '{config.FMRIPREP_DIR}';
    bidspm_preproc = fullfile('{config.DERIVATIVES_DIR}', 'bidspm-preproc');
    if exist(bidspm_preproc, 'dir')
        preproc_dir = bidspm_preproc;
        fprintf('Using preproc_dir: %s\\n', preproc_dir);
    else
        fprintf('Using fallback preproc_dir: %s\\n', preproc_dir);
    end

    bidspm('{config.BIDS_DIR}', ...
           '{config.DERIVATIVES_DIR}', ...
           'subject', ...
           'action', 'stats', ...
           'participant_label', {{'{subject}'}}, ...
           'task', {{'{task}'}}, ...
           'space', {{'{config.SPACE}'}}, ...
           'fwhm', {config.FWHM}, ...
           'model_file', '{model_file_path.absolute()}', ...
           'preproc_dir', preproc_dir, ...
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

% Set warning level to reduce verbose output
warning('off', 'all');

% Add SPM12 standalone if available
spm12_path = fullfile(pwd, 'external/spm12_standalone');
if exist(spm12_path, 'dir')
    addpath(spm12_path);
    fprintf('SPM12 standalone added to path\\n');
end

% Add BIDSPM to path and initialize
bidspm_path = '{local_bidspm_dir.absolute()}';
if exist(bidspm_path, 'dir')
    addpath(bidspm_path);
    fprintf('Initializing BIDSPM from: %s\\n', bidspm_path);
    % Initialize BIDSPM (this will load necessary packages like statistics, datatypes)
    if exist('bidspm', 'file')
        bidspm('init');
    end
end

% Try to initialize SPM if available
try
    if exist('spm', 'file')
        spm('defaults', 'fmri');
        spm_jobman('initcfg');
        fprintf('SPM initialized successfully\\n');
    end
catch
    fprintf('SPM initialization skipped\\n');
end

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
                    cmd = [matlab_cmd, "--no-gui", "--eval", f"run('{script_file.stem}')"]
                
                log_debug(f"Local BIDSPM command: {' '.join(cmd)}")
                
                result = subprocess.run(cmd, check=True, text=True, 
                                      capture_output=True, timeout=1800,
                                      env=local_env)  # 30 minute timeout
                
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
    local_octave_bin = Path("external/octave/bin")
    local_octave = local_octave_bin / "octave"
    local_cli = local_octave_bin / "octave-cli"
    
    octave_available = (shutil.which("octave") is not None) or local_octave.exists() or local_cli.exists()
    mcr_available = Path("/usr/local/freesurfer/MCRv97").exists()
    
    if matlab_available:
        print("✅ MATLAB found in PATH")
    elif local_cli.exists():
        print(f"✅ Local Octave-CLI found at {local_cli}")
    elif local_octave.exists():
        print(f"✅ Local Octave found at {local_octave}")
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
    spm12_dir = Path("external/spm12_standalone")
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
            "apptainer", "exec",
            "--writable-tmpfs",  # Allow writing to /tmp and other temp locations
            "--no-home",  # Don't bind home directory (avoid permission issues)
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
        # Named 'octave' so it can be picked up if /tmp is in PATH
        octave_wrapper = run_tmp_dir / "octave"
        
        # We bind the wrapper to a dedicated path in the container to avoid binding /tmp
        # This allows --writable-tmpfs to function correctly
        runtime_bind_path = "/opt/bidspm_runtime"
        
        octave_wrapper_content = f"""#!/bin/bash
# Octave wrapper to ensure BIDSPM paths are available before any octave execution
export MATLABPATH="/home/neuro/bidspm:/home/neuro/bidspm/lib/CPP_ROI:/home/neuro/bidspm/lib/CPP_ROI/atlas:/opt/spm12:$MATLABPATH"

# Find the real octave executable (prefer octave over octave-cli)
if [ -f /usr/bin/octave ]; then 
    REAL_OCTAVE=/usr/bin/octave
elif [ -f /usr/local/bin/octave ]; then 
    REAL_OCTAVE=/usr/local/bin/octave
elif [ -f /usr/bin/octave-cli ]; then 
    REAL_OCTAVE=/usr/bin/octave-cli
else 
    REAL_OCTAVE=octave
fi

# Create a startup file that adds all bidspm paths
OCTAVE_INIT="/tmp/octave_init_$$.m"
cat > "$OCTAVE_INIT" << 'EOF'
addpath(genpath('/home/neuro/bidspm'));
EOF

# Execute octave with the initialization file prepended to any user commands
exec "$REAL_OCTAVE" --eval "run('$OCTAVE_INIT');" "$@"
"""
        
        with open(octave_wrapper, 'w') as f:
            f.write(octave_wrapper_content)
        octave_wrapper.chmod(0o755)
        
        # Bind the runtime directory to a distinct location, NOT /tmp
        cmd.extend(["--bind", f"{run_tmp_dir}:{runtime_bind_path}"])
        
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
        
        # Prepend the runtime path to PATH using APPTAINERENV_PREPEND_PATH
        # We do this by prefixing the command with 'env' instead of using --env inside the command,
        # because --env PATH=...:$PATH creates a literal mess with variable expansion.
        prefix_cmd = ["env", f"APPTAINERENV_PREPEND_PATH={runtime_bind_path}"]
        
        # Set important environment variables for the container
        cmd.extend([
            "--env", "TMPDIR=/tmp",  # Set TMPDIR
            "--env", "TMP=/tmp",     # Set TMP
            "--env", "MATLAB_LOG_DIR=/tmp",  # MATLAB logs to tmp
            "--env", "SPM_HTML_BROWSER=0",   # Disable SPM browser for headless operation
            "--env", "BIDSPM_SKIP_ATLAS_INIT=1",  # Try to skip problematic atlas initialization
            "--env", f"OCTAVE_EXECUTABLE={runtime_bind_path}/octave",  # Use our custom Octave wrapper
            "--env", "MATLABPATH=/home/neuro/bidspm:/home/neuro/bidspm/lib/CPP_ROI:/home/neuro/bidspm/lib/CPP_ROI/src:/home/neuro/bidspm/lib/CPP_ROI/atlas:/home/neuro/bidspm/lib/CPP_ROI/src/atlas:/opt/spm12",  # Include src and src/atlas directories
            "--env", "CPP_ROI_SKIP_ATLAS=1",  # Skip CPP_ROI atlas operations if supported
            "--env", "CPP_ROI_SKIP_ATLAS_INIT=1",  # Additional skip flag
            "--env", "CPP_ROI_ATLAS_SKIP=1",  # Another possible skip flag
            "--env", "SKIP_ATLAS_INIT=1",  # General skip flag
            "--env", "BIDSPM_IGNORE_FIELDMAPS=1",  # Skip fieldmap processing (not needed for smoothing)
            "--env", "BIDSPM_IGNORE_FIGURES=1",   # Skip HTML/SVG files processing
            "--env", "BIDSPM_SKIP_INTENDEDFOR_CHECK=1"  # Skip IntendedFor validation (irrelevant post-fMRIPrep)
        ])

        cmd.append(container_config.apptainer_image)
        
        # Reconstruct the command to enforce a clean PATH inside the container
        # We wrap the execution in a shell to manually force a clean PATH, avoiding host contamination
        quoted_args = " ".join(shlex.quote(str(arg)) for arg in args)
        
        # PATH must include:
        # 1. runtime_bind_path (for our custom 'octave' wrapper with path pre-init)
        # 2. /usr/local/bin (where 'bidspm' executable lives)
        # 3. /usr/bin, /bin (standard system tools)
        shell_cmd = f"export PATH={runtime_bind_path}:/usr/local/bin:/usr/bin:/bin; exec bidspm {quoted_args}"
        
        cmd.extend(["sh", "-c", shell_cmd])
        
        # Prepend the env command
        cmd = prefix_cmd + cmd
        
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
    -s, --settings       Path to configuration JSON file (default: config/config.json)
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
    python bidspm.py -s config/my_config.json -m my_model.json --action smooth stats
    
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
    • config/config.json: Main settings (paths, tasks, subjects, etc.)
    • containers/container.json: Container configuration (auto-detected if missing)
    • BIDS-StatsModel JSON: Statistical model specification

REQUIREMENTS:
    • Python 3.7+
    • Docker OR Apptainer/Singularity
    • BIDS-formatted dataset with fMRIPrep derivatives
    • Valid BIDS-StatsModel JSON file

CONFIGURATION VALIDATION:
    Your config/config.json is automatically validated against config/config_schema.json.
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
            # First traverse checks:
            # 1. Check if the main config file ALSO contains container settings
            if Path(config_file).exists():
                try:
                    with open(config_file, 'r') as f:
                        data = json.load(f)
                        # Honor any explicit container_type in the main config (even if images are empty)
                        if "container_type" in data:
                            log_debug(f"Detected container settings in main config file: {config_file}")
                            container_config_file = config_file
                        else:
                            # 2. Fall back to detection
                            auto_selected = auto_select_container_config()
                            container_config_file = auto_selected if auto_selected else CONTAINER_CONFIG_FILE
                except Exception:
                    # If main config is invalid (will be caught later), just fallback
                    auto_selected = auto_select_container_config()
                    container_config_file = auto_selected if auto_selected else CONTAINER_CONFIG_FILE
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

    # Validate config file against schema (if jsonschema is available)
    try:
        if not JSONValidator.validate_with_schema(config_file, "config/config_schema.json"):
            print(f"❌ {config_file} does not match the required schema (config/config_schema.json)!")
            print(f"   Please check your {config_file} and compare it to config/config_schema.json.")
            sys.exit(1)
    except ImportError:
        print("⚠️  Skipping schema validation: jsonschema package is not installed.")

    # Dependency Checks
    check_command("python3")

    # Load configurations
    config = load_config(config_file)
    print(f"📦 container_type from {config_file}: {config.CONTAINER_TYPE}")
    
    # Respect container_type from config if not overridden by args
    if not args.local and config.CONTAINER_TYPE == "local":
        print(f"🔧 Using local execution as specified in {config_file}")
        args.local = True
    
    # Only load container config if not using local execution
    if not args.local:
        container_config = load_container_config(container_config_file)

        # If apptainer is requested but no image was set, fall back to the default apptainer config file
        if container_config.container_type == "apptainer" and not container_config.apptainer_image:
            fallback_cfg = Path("containers/container_apptainer.json")
            if fallback_cfg.exists() and str(fallback_cfg) != str(container_config_file):
                log_debug(f"Apptainer image missing in {container_config_file}, falling back to {fallback_cfg}")
                container_config = load_container_config(str(fallback_cfg))
                container_config_file = str(fallback_cfg)
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

    # Model file is only strictly required if 'stats' is being performed
    needs_model = 'stats' in args.action
    
    # Validate MODELS_FILE or -m
    if needs_model and not args.model and not config.MODELS_FILE:
        log_error("No model file specified! Please provide MODELS_FILE in config or use -m for 'stats' action.")

    # Determine model file path - command line argument overrides config
    model_file_path = None
    models_file_name = "unknown"
    
    if args.model or config.MODELS_FILE:
        if args.model:
            model_file_path = Path(args.model)
            if not model_file_path.is_absolute():
                # If relative path, make it relative to derivatives directory
                model_file_path = config.DERIVATIVES_DIR / "models" / model_file_path
            models_file_name = model_file_path.name
        elif config.MODELS_FILE:
            # If MODELS_FILE is absolute path, use it directly
            if Path(config.MODELS_FILE).is_absolute():
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
    
    if model_file_path:
        log_debug(f"Using model file: {model_file_path}")
    log_debug(f"Log file: {LOG_FILE}")
    
    # Check model file exists if we need it
    if needs_model:
        if not model_file_path:
             log_error("Model file path could not be determined.")
        if not model_file_path.exists():
            log_error(f"Model file '{models_file_name}' not found at '{model_file_path}'.")

        if not args.skip_modelvalidation:
            log_debug("Validating model JSON against BIDS Stats Model schema")
            venv_python = Path(".bidspm/bin/python")
            python_cmd = str(venv_python) if venv_python.exists() else "python3"
            run_command([python_cmd, "docs/validate_bids_model.py", str(model_file_path)], capture_output=True)
        else:
            print("⚠️  Skipping BIDS-StatsModel JSON validation (--skip-modelvalidation flag used)")
    elif model_file_path and model_file_path.exists():
        # Even if not strict, validate if it exists and we're not skipping
        if not args.skip_modelvalidation:
            log_debug("Validating model JSON against BIDS Stats Model schema (optional)")
            venv_python = Path(".bidspm/bin/python")
            python_cmd = str(venv_python) if venv_python.exists() else "python3"
            run_command([python_cmd, "docs/validate_bids_model.py", str(model_file_path)], capture_output=True)
    else:
        log_debug("Skipping model validation (not performing 'stats' action)")

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

    try:
        # ---------------------------------------------------
        # Determine subjects to process (once for all tasks)
        # ---------------------------------------------------
        subjects_to_process = []
        
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
                return 
                
            # Select random subject (fixed for all tasks)
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
            subjects_to_process = []
            for sub_dir in config.FMRIPREP_DIR.glob("sub-*"):
                if sub_dir.is_dir():
                    subject_label = sub_dir.name.replace("sub-", "")
                    subjects_to_process.append(subject_label)
            log_debug(f"Auto-discovered subjects: {', '.join(subjects_to_process)}")
            print(f">>> Auto-discovered {len(subjects_to_process)} subjects")
            
        if not subjects_to_process:
            print("❌ No subjects found to process.")
            return

        # Processing loop
        for task in config.TASKS:
            print("---------------------------------------------------")
            print(f">>> Processing task: {task}")
            print("---------------------------------------------------")

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

                # 1. First, smoothing (if requested)
                if 'smooth' in args.action:
                    print(f">>> Smoothing for subject: {subject_label}, task: {task}")
                    
                    if args.local:
                        # Local execution
                        success = run_local_bidspm(config, "smooth", [subject_label], task, model_file_path)
                    else:
                        # Container execution
                        # Calculate the container path for fmriprep
                        # If FMRIPREP_DIR is inside DERIVATIVES_DIR, we can use the /derivatives mapping
                        try:
                            fmriprep_rel = config.FMRIPREP_DIR.relative_to(config.DERIVATIVES_DIR)
                            fmriprep_container_path = f"/derivatives/{fmriprep_rel}"
                        except ValueError:
                            # Fallback to standard location if not relative
                            fmriprep_container_path = "/derivatives/fmriprep"
                            print(f"⚠️  FMRIPREP_DIR ({config.FMRIPREP_DIR}) is not within DERIVATIVES_DIR ({config.DERIVATIVES_DIR})")
                            print(f"   Using default container path: {fmriprep_container_path}")
                        
                        smooth_args = [
                            fmriprep_container_path, "/derivatives", "subject", "smooth",
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

                # 2. ROI analysis block
                if hasattr(config, "ROI") and config.ROI:
                    roi_config = config.ROI_CONFIG
                    preproc_dir = config.DERIVATIVES_DIR / "bidspm-preproc"
                    
                    # Check if preproc directory exists
                    if not preproc_dir.exists():
                        print(f"❌ Preprocessing directory not found: {preproc_dir}")
                        print("   ROI analysis requires smoothed data. Please run smoothing first using the --action smooth option.")
                    else:
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
                        else:
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
                            else:
                                # Run ROI-based GLM
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

                # 3. Check for smoothed data for main SPACE before stats
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
                        log(f"Smoothed data for main SPACE '{main_space}' not found in {preproc_dir}. Run smoothing first!", error=True)
                    else:
                        print(f">>> Running stats for subject: {subject_label}, task: {task}")
                        log(f"Running stats for subject: {subject_label}, task: {task}")
                        
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

    except KeyboardInterrupt:
        print("\n\n🛑 Process interrupted by user. Exiting...")
        sys.exit(1)

    # Clean up old temporary directories
    cleanup_tmp_directories(config)

    print(f">>> All processing complete. Logs saved to {LOG_FILE}")


if __name__ == "__main__":
    main()
