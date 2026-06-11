#!/usr/bin/env python3
"""Container execution functions for BIDSPM Runner"""

import random
from datetime import datetime
from pathlib import Path
from typing import List

from .config import Config, ContainerConfig
from .logging_utils import log_error

# Repo root is two levels above this file: scripts/modules -> scripts -> bidspm
_REPO_ROOT = Path(__file__).parent.parent.parent
_LOCAL_SRC = _REPO_ROOT / "local_src" / "bidspm_local"
_CONTAINER_BIDSPM = "/home/neuro/bidspm"


def _local_patch_binds() -> List[str]:
    """Return --bind args for every file in local_src/bidspm_local/ that
    should override the corresponding file inside the container."""
    binds = []
    if not _LOCAL_SRC.exists():
        return binds
    for local_file in _LOCAL_SRC.rglob("*"):
        if local_file.is_file():
            rel = local_file.relative_to(_LOCAL_SRC)
            container_path = f"{_CONTAINER_BIDSPM}/{rel}"
            binds.extend(["--bind", f"{local_file}:{container_path}"])
    return binds


def build_container_command(container_config: ContainerConfig, config: Config, args: List[str], model_file_path: Path) -> tuple:
    """Build container command based on container type (docker or apptainer)
    
    Returns:
        tuple: (container_command, model_file_container_path)
    """
    
    if container_config.container_type == "docker":
        return _build_docker_command(container_config, config, args, model_file_path)
    elif container_config.container_type == "apptainer":
        return _build_apptainer_command(container_config, config, args, model_file_path)
    else:
        log_error(f"Unsupported container type: {container_config.container_type}")


def _build_docker_command(container_config: ContainerConfig, config: Config, args: List[str], model_file_path: Path) -> tuple:
    """Build Docker container command"""
    if not container_config.docker_image:
        log_error("Docker image not specified in container configuration.")
    
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{config.BIDS_DIR}:/raw",
        "-v", f"{config.BIDS_DIR}:{config.BIDS_DIR}",
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
        "-e", "BIDSPM_IGNORE_FIELDMAPS=1",  # Skip fieldmap processing
        "-e", "BIDSPM_IGNORE_FIGURES=1",   # Skip HTML/SVG files processing
        "-e", "BIDSPM_SKIP_INTENDEDFOR_CHECK=1"  # Skip IntendedFor validation
    ])

    cmd.append(container_config.docker_image)
    cmd.extend(args)
    return cmd, model_container_path


def _build_apptainer_command(container_config: ContainerConfig, config: Config, args: List[str], model_file_path: Path) -> tuple:
    """Build Apptainer container command"""
    if not container_config.apptainer_image:
        log_error("Apptainer image not specified in container configuration.")
    
    # Check if it's a docker:// URL or local .sif file
    if not container_config.apptainer_image.startswith("docker://") and not Path(container_config.apptainer_image).exists():
        log_error(f"Apptainer image file '{container_config.apptainer_image}' not found.")
    
    cmd = [
        "apptainer", "run",
        "--writable-tmpfs",  # Allow writing to /tmp and other temp locations
        "--bind", f"{config.BIDS_DIR}:/raw",
        "--bind", f"{config.BIDS_DIR}:{config.BIDS_DIR}",
        "--bind", f"{config.DERIVATIVES_DIR}:/derivatives"
    ]
    
    # Check if model file is inside derivatives directory
    try:
        rel_path = model_file_path.relative_to(config.DERIVATIVES_DIR)
        model_container_path = f"/derivatives/{rel_path}"
    except ValueError:
        # Model file is outside derivatives, mount it separately
        cmd.extend(["--bind", f"{model_file_path}:/models/smdl.json"])
        model_container_path = "/models/smdl.json"
    
    # Create and mount a dedicated tmp directory for this run
    run_tmp_dir = config.WD / "tmp" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"
    run_tmp_dir.mkdir(parents=True, exist_ok=True)
    
    # Create a custom Octave wrapper script
    octave_wrapper = run_tmp_dir / "octave"
    runtime_bind_path = "/opt/bidspm_runtime"
    
    octave_wrapper_content = f"""#!/bin/bash
# Octave wrapper to ensure BIDSPM paths are available
export MATLABPATH="/home/neuro/bidspm:/home/neuro/bidspm/lib/CPP_ROI:/home/neuro/bidspm/lib/CPP_ROI/atlas:/opt/spm12:$MATLABPATH"

# Copy atlas-related functions to tmp
mkdir -p /tmp/atlas_functions
cp /home/neuro/bidspm/lib/CPP_ROI/atlas/*.m /tmp/atlas_functions/ 2>/dev/null || true
cp /home/neuro/bidspm/lib/CPP_ROI/src/atlas/*.m /tmp/atlas_functions/ 2>/dev/null || true

# Create init file to add paths
cat > /tmp/octave_init_runtime.m << 'EOF'
warning('off', 'all');
addpath('/tmp/atlas_functions');
addpath('/tmp');
addpath('{runtime_bind_path}');
addpath('/home/neuro/bidspm');
addpath('/home/neuro/bidspm/lib/CPP_ROI');
addpath('/home/neuro/bidspm/lib/CPP_ROI/atlas');
addpath('/home/neuro/bidspm/lib/CPP_ROI/src');
addpath('/home/neuro/bidspm/lib/CPP_ROI/src/atlas');
addpath('/opt/spm12');
fprintf('Runtime paths added\\n');
EOF

# Find the real octave executable
REAL_OCTAVE=$(which octave 2>/dev/null)
if [[ "$REAL_OCTAVE" == "{runtime_bind_path}/octave" ]] || [[ "$REAL_OCTAVE" == "/tmp/octave" ]] || [[ -z "$REAL_OCTAVE" ]]; then
    if [ -f /usr/bin/octave ]; then REAL_OCTAVE=/usr/bin/octave;
    elif [ -f /usr/local/bin/octave ]; then REAL_OCTAVE=/usr/local/bin/octave;
    else REAL_OCTAVE=octave; fi
fi

# Run octave with the init file
exec "$REAL_OCTAVE" --init-file /tmp/octave_init_runtime.m "$@"
"""
    
    with open(octave_wrapper, 'w') as f:
        f.write(octave_wrapper_content)
    octave_wrapper.chmod(0o755)
    
    # Bind the runtime directory
    cmd.extend(["--bind", f"{run_tmp_dir}:{runtime_bind_path}"])
    
    # Add additional bind mounts for writable directories
    for dir_name, container_path in [
        ("atlas", "/opt/spm12/atlas"),
        ("cpp_roi_atlas", "/home/neuro/bidspm/lib/CPP_ROI/atlas"),
        ("error_logs", "/home/neuro/bidspm/error_logs"),
        ("spm", "/home/neuro/spm"),
        ("matlab_cache", "/home/neuro/.matlab")
    ]:
        local_dir = config.WD / dir_name
        local_dir.mkdir(exist_ok=True)
        cmd.extend(["--bind", f"{local_dir}:{container_path}"])
    
    # Set environment variables
    prefix_cmd = ["env", f"APPTAINERENV_PREPEND_PATH={runtime_bind_path}"]
    
    cmd.extend([
        "--env", "HOME=/tmp",
        "--env", "TMPDIR=/tmp",
        "--env", "TMP=/tmp",
        "--env", "MATLAB_LOG_DIR=/tmp",
        "--env", "SPM_HTML_BROWSER=0",
        "--env", "BIDSPM_SKIP_ATLAS_INIT=1",
        "--env", f"OCTAVE_EXECUTABLE={runtime_bind_path}/octave",
        "--env", "MATLABPATH=/home/neuro/bidspm:/home/neuro/bidspm/lib/CPP_ROI:/home/neuro/bidspm/lib/CPP_ROI/atlas:/opt/spm12",
        "--env", "CPP_ROI_SKIP_ATLAS=1",
        "--env", "BIDSPM_IGNORE_FIELDMAPS=1",
        "--env", "BIDSPM_IGNORE_FIGURES=1",
        "--env", "BIDSPM_SKIP_INTENDEDFOR_CHECK=1"
    ])

    # Bind-mount local patches (local_src/bidspm_local/) over container files
    cmd.extend(_local_patch_binds())

    cmd.append(container_config.apptainer_image)
    cmd.extend(args)
    
    # Prepend the env command
    cmd = prefix_cmd + cmd

    return cmd, model_container_path
