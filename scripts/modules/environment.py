#!/usr/bin/env python3
"""Environment setup and checking utilities for BIDSPM Runner"""

import shutil
import subprocess
from pathlib import Path

from .config import ContainerConfig
from .logging_utils import log_error, log_error_non_fatal, log, log_debug


def check_command(cmd):
    """Check if a command is available in PATH."""
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
