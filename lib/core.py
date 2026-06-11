"""
Core BIDSPM business logic - shared between CLI and web interface.

This module contains all pipeline logic to avoid code duplication.
The web interface should only handle visual/API concerns, not execution logic.
"""

import json
import os
import re
import random
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable, Tuple

from .config import Config, ContainerConfig, load_config, load_container_config
from .utils import (
    log, log_debug, log_error, log_error_non_fatal,
    generate_log_filename, check_command, check_docker_availability,
    run_command, validate_space_availability,
    ensure_derivatives_dataset_description, cleanup_tmp_directories
)


# =============================================================================
# MATLAB Environment Detection
# =============================================================================

class MatlabEnvironment(Enum):
    """Types of MATLAB execution environments."""
    MATLAB_LICENSED = "matlab_licensed"      # Full MATLAB with license
    MATLAB_STANDALONE = "matlab_standalone"  # SPM12 standalone (compiled)
    OCTAVE = "octave"                        # GNU Octave
    CONTAINER = "container"                  # Runs inside container
    NONE = "none"                            # No MATLAB environment


@dataclass
class MatlabCapabilities:
    """Describes what features are available in the detected MATLAB environment."""
    environment: MatlabEnvironment
    path: Optional[str] = None
    version: Optional[str] = None
    
    # Feature availability - standalone has limitations
    can_run_arbitrary_scripts: bool = True
    can_compile_mex: bool = False
    can_use_toolboxes: bool = False
    can_use_parallel: bool = False
    has_statistics_toolbox: bool = False
    has_image_processing_toolbox: bool = False
    
    # Limitations for user feedback
    limitations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "environment": self.environment.value,
            "path": self.path,
            "version": self.version,
            "can_run_arbitrary_scripts": self.can_run_arbitrary_scripts,
            "can_compile_mex": self.can_compile_mex,
            "can_use_toolboxes": self.can_use_toolboxes,
            "can_use_parallel": self.can_use_parallel,
            "has_statistics_toolbox": self.has_statistics_toolbox,
            "has_image_processing_toolbox": self.has_image_processing_toolbox,
            "limitations": self.limitations
        }


def detect_matlab_environment() -> MatlabCapabilities:
    """
    Detect available MATLAB/Octave environment and its capabilities.
    Returns MatlabCapabilities describing what's available.
    """
    # Check for full MATLAB first (most capable)
    matlab_path = shutil.which("matlab")
    if matlab_path:
        caps = _detect_matlab_licensed(matlab_path)
        if caps:
            return caps
    
    # Check for local Octave installation
    local_octave_paths = [
        Path("external/octave/bin/octave-cli"),
        Path("external/octave/bin/octave"),
    ]
    for octave_path in local_octave_paths:
        if octave_path.exists():
            return _detect_octave(str(octave_path.absolute()))
    
    # Check system Octave
    octave_path = shutil.which("octave") or shutil.which("octave-cli")
    if octave_path:
        return _detect_octave(octave_path)
    
    # Check for SPM12 standalone (MCR-based)
    spm_standalone = Path("external/spm12_standalone/run_spm12.sh")
    if spm_standalone.exists():
        return _detect_spm_standalone(str(spm_standalone))
    
    # Check MCR installations
    mcr_paths = [
        Path("/usr/local/MATLAB/MATLAB_Runtime"),
        Path("/opt/mcr"),
        Path(os.path.expanduser("~/MATLAB_Runtime")),
    ]
    for mcr_base in mcr_paths:
        if mcr_base.exists():
            return MatlabCapabilities(
                environment=MatlabEnvironment.MATLAB_STANDALONE,
                path=str(mcr_base),
                can_run_arbitrary_scripts=False,
                can_compile_mex=False,
                can_use_toolboxes=False,
                limitations=[
                    "SPM12 standalone mode - limited to pre-compiled functions",
                    "Cannot run custom MATLAB scripts",
                    "Some advanced BIDSPM features unavailable",
                    "ROI analysis may be limited"
                ]
            )
    
    return MatlabCapabilities(
        environment=MatlabEnvironment.NONE,
        limitations=[
            "No MATLAB, Octave, or MCR found",
            "Local execution not available",
            "Use container execution instead"
        ]
    )


def _detect_matlab_licensed(matlab_path: str) -> Optional[MatlabCapabilities]:
    """Detect full MATLAB installation and check license/toolboxes."""
    try:
        # Quick check if MATLAB runs
        result = subprocess.run(
            [matlab_path, "-batch", "disp('ok')"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            # License issue or other problem
            if "license" in result.stderr.lower():
                return MatlabCapabilities(
                    environment=MatlabEnvironment.MATLAB_LICENSED,
                    path=matlab_path,
                    can_run_arbitrary_scripts=False,
                    limitations=[
                        "MATLAB found but license unavailable",
                        "Use container execution or Octave"
                    ]
                )
            return None
        
        # Check for toolboxes
        toolbox_check = subprocess.run(
            [matlab_path, "-batch", 
             "disp(license('test','Statistics_Toolbox'));disp(license('test','Image_Toolbox'));disp(license('test','Distrib_Computing_Toolbox'))"],
            capture_output=True, text=True, timeout=30
        )
        
        lines = toolbox_check.stdout.strip().split('\n')
        has_stats = len(lines) > 0 and lines[0].strip() == '1'
        has_image = len(lines) > 1 and lines[1].strip() == '1'
        has_parallel = len(lines) > 2 and lines[2].strip() == '1'
        
        limitations = []
        if not has_stats:
            limitations.append("Statistics Toolbox not available - some contrasts may fail")
        if not has_image:
            limitations.append("Image Processing Toolbox not available")
        
        return MatlabCapabilities(
            environment=MatlabEnvironment.MATLAB_LICENSED,
            path=matlab_path,
            can_run_arbitrary_scripts=True,
            can_compile_mex=True,
            can_use_toolboxes=True,
            can_use_parallel=has_parallel,
            has_statistics_toolbox=has_stats,
            has_image_processing_toolbox=has_image,
            limitations=limitations
        )
    except subprocess.TimeoutExpired:
        return MatlabCapabilities(
            environment=MatlabEnvironment.MATLAB_LICENSED,
            path=matlab_path,
            can_run_arbitrary_scripts=True,
            limitations=["MATLAB detected but slow to respond - license server may be slow"]
        )
    except Exception:
        return None


def _detect_octave(octave_path: str) -> MatlabCapabilities:
    """Detect Octave installation and version."""
    try:
        result = subprocess.run(
            [octave_path, "--version"],
            capture_output=True, text=True, timeout=10
        )
        version_match = re.search(r'GNU Octave.*?(\d+\.\d+\.\d+)', result.stdout)
        version = version_match.group(1) if version_match else "unknown"
        
        # Check for required packages
        pkg_check = subprocess.run(
            [octave_path, "--eval", "pkg list"],
            capture_output=True, text=True, timeout=30
        )
        
        limitations = [
            "Octave mode - some MATLAB-specific functions may behave differently",
            "Parallel processing not available"
        ]
        
        # Statistics package is optional — SPM12 bundles its own stats routines.
        # Only warn if running an Octave-native stats workflow (not SPM GLM).
        
        return MatlabCapabilities(
            environment=MatlabEnvironment.OCTAVE,
            path=octave_path,
            version=version,
            can_run_arbitrary_scripts=True,
            can_compile_mex=False,
            can_use_toolboxes=False,
            can_use_parallel=False,
            limitations=limitations
        )
    except Exception as e:
        return MatlabCapabilities(
            environment=MatlabEnvironment.OCTAVE,
            path=octave_path,
            limitations=[f"Octave found but error detecting capabilities: {e}"]
        )


def _detect_spm_standalone(spm_path: str) -> MatlabCapabilities:
    """Detect SPM12 standalone installation."""
    return MatlabCapabilities(
        environment=MatlabEnvironment.MATLAB_STANDALONE,
        path=spm_path,
        can_run_arbitrary_scripts=False,
        can_compile_mex=False,
        can_use_toolboxes=False,
        can_use_parallel=False,
        limitations=[
            "SPM12 standalone mode - pre-compiled functions only",
            "Custom BIDSPM scripts cannot be modified",
            "ROI analysis may require full MATLAB/Octave",
            "Some statistical models may not be supported"
        ]
    )


# =============================================================================
# Feature Gating Based on Environment
# =============================================================================

@dataclass
class FeatureAvailability:
    """Which pipeline features are available given the current environment."""
    smooth: bool = True
    stats_subject: bool = True
    stats_dataset: bool = True
    roi_analysis: bool = True
    custom_contrasts: bool = True
    
    # Reasons for unavailability
    unavailable_reasons: Dict[str, str] = field(default_factory=dict)


def check_feature_availability(
    matlab_caps: MatlabCapabilities,
    using_container: bool = False
) -> FeatureAvailability:
    """
    Determine which features are available based on MATLAB environment.
    Container execution bypasses most limitations.
    """
    if using_container:
        return FeatureAvailability()  # All features available in container
    
    features = FeatureAvailability()
    
    if matlab_caps.environment == MatlabEnvironment.NONE:
        features.smooth = False
        features.stats_subject = False
        features.stats_dataset = False
        features.roi_analysis = False
        features.custom_contrasts = False
        features.unavailable_reasons = {
            "all": "No MATLAB/Octave environment detected. Use container execution."
        }
        return features
    
    if matlab_caps.environment == MatlabEnvironment.MATLAB_STANDALONE:
        features.roi_analysis = False
        features.custom_contrasts = False
        features.unavailable_reasons = {
            "roi_analysis": "ROI analysis requires full MATLAB or Octave (standalone limitation)",
            "custom_contrasts": "Custom contrast scripts require full MATLAB or Octave"
        }
    
    if matlab_caps.environment == MatlabEnvironment.MATLAB_LICENSED:
        if not matlab_caps.has_statistics_toolbox:
            features.unavailable_reasons["stats_warning"] = (
                "Statistics Toolbox not detected - some statistical functions may fail"
            )
    
    return features


# =============================================================================
# Container Command Building (Split by Type)
# =============================================================================

def build_docker_command(
    container_config: ContainerConfig,
    config: Config,
    args: List[str],
    model_file_path: Optional[Path]
) -> Tuple[List[str], Optional[str]]:
    """Build Docker container command."""
    if not container_config.docker_image:
        raise ValueError("Docker image not specified in container configuration.")
    
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{config.BIDS_DIR}:/raw",
        "-v", f"{config.BIDS_DIR}:{config.BIDS_DIR}",
        "-v", f"{config.DERIVATIVES_DIR}:/derivatives"
    ]
    
    # Create tmp directory for this run
    run_tmp_dir = config.WD / "tmp" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"
    run_tmp_dir.mkdir(parents=True, exist_ok=True)
    cmd.extend(["-v", f"{run_tmp_dir}:/tmp"])
    
    # Handle model file path
    model_container_path = None
    if model_file_path:
        try:
            rel_path = model_file_path.relative_to(config.DERIVATIVES_DIR)
            model_container_path = f"/derivatives/{rel_path}"
        except ValueError:
            cmd.extend(["-v", f"{model_file_path}:/models/smdl.json"])
            model_container_path = "/models/smdl.json"
    
    # Environment variables
    cmd.extend([
        "-e", "HOME=/tmp",
        "-e", "TMPDIR=/tmp",
        "-e", "TMP=/tmp",
        "-e", "SPM_HTML_BROWSER=0",
        "-e", "BIDSPM_IGNORE_FIELDMAPS=1",
        "-e", "BIDSPM_IGNORE_FIGURES=1",
        "-e", "BIDSPM_SKIP_INTENDEDFOR_CHECK=1"
    ])

    cmd.append(container_config.docker_image)
    cmd.extend(args)
    return cmd, model_container_path


def build_apptainer_command(
    container_config: ContainerConfig,
    config: Config,
    args: List[str],
    model_file_path: Optional[Path]
) -> Tuple[List[str], Optional[str]]:
    """Build Apptainer/Singularity container command."""
    if not container_config.apptainer_image:
        raise ValueError("Apptainer image not specified in container configuration.")
    
    # Check image exists
    if not container_config.apptainer_image.startswith("docker://"):
        if not Path(container_config.apptainer_image).exists():
            raise ValueError(f"Apptainer image file '{container_config.apptainer_image}' not found.")
    
    cmd = [
        "apptainer", "exec",
        "--writable-tmpfs",
        "--no-home",
        "--bind", f"{config.BIDS_DIR}:/raw",
        "--bind", f"{config.BIDS_DIR}:{config.BIDS_DIR}",
        "--bind", f"{config.DERIVATIVES_DIR}:/derivatives"
    ]
    
    # Handle model file path
    model_container_path = None
    if model_file_path:
        try:
            rel_path = model_file_path.relative_to(config.DERIVATIVES_DIR)
            model_container_path = f"/derivatives/{rel_path}"
        except ValueError:
            cmd.extend(["--bind", f"{model_file_path}:/models/smdl.json"])
            model_container_path = "/models/smdl.json"
    
    # Create runtime directory
    run_tmp_dir = config.WD / "tmp" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"
    run_tmp_dir.mkdir(parents=True, exist_ok=True)
    runtime_bind_path = "/opt/bidspm_runtime"
    
    # Create Octave wrapper
    _create_octave_wrapper(run_tmp_dir)
    
    cmd.extend(["--bind", f"{run_tmp_dir}:{runtime_bind_path}"])
    
    # Make host bids-validator available inside the container.
    # The container has no Node.js, so we write a small wrapper script into
    # the runtime tmp dir that calls the host node binary directly with the
    # pre-bundled CommonJS CLI entry of bids-validator v1.x.
    _host_node = Path("/usr/bin/node")
    _bids_cli = Path("/usr/lib/node_modules/bids-validator/dist/commonjs/cli.js")
    if _host_node.exists() and _bids_cli.exists():
        # Write a tiny Node.js runner that loads the bundled CLI module and
        # calls its exported function (the module is not a runnable script).
        _runner = run_tmp_dir / "bids-validator-runner.js"
        _runner.write_text(
            f"const {{ default: cli }} = require({repr(str(_bids_cli))});\n"
            "cli(process.argv.slice(2)).catch(code => process.exit(code || 1));\n"
        )
        _wrapper = run_tmp_dir / "bids-validator"
        _wrapper.write_text(
            f"#!/bin/sh\nexec {_host_node} {_runner} \"$@\"\n"
        )
        _wrapper.chmod(0o755)
        cmd.extend([
            "--bind", f"{_host_node}:/usr/bin/node",
            "--bind", f"{_wrapper}:/usr/bin/bids-validator",
        ])

    # Override container source files with patched local versions.
    # Factor.m: adds cross-product support for multi-column input.
    # validateContrasts.m: adds missing cell-array guard (container v4.0.0 bug).
    # setBatchSubjectLevelContrasts.m: coerces cell→struct before validate call.
    # return_file_index.m: suppresses benign warnings for fMRIPrep 'figures' QC files.
    # Filter.m / get_input.m / check_field.m / identify_rows.m: ensure the full
    #   transformer chain uses our local versions so Filter + Factor work end-to-end.
    # BidsModel.m: fixes cellfun crash in validateConstrasts — Octave cannot use
    #   `x == 1` to test for the intercept when x is a multi-char string.
    _ov = Path(__file__).parent.parent / "bidspm_overrides"
    _tl = _ov / "lib" / "bids-matlab" / "+bids" / "+transformers_list"
    _file_overrides = [
        (
            _tl / "Factor.m",
            "/home/neuro/bidspm/lib/bids-matlab/+bids/+transformers_list/Factor.m",
        ),
        (
            _tl / "Filter.m",
            "/home/neuro/bidspm/lib/bids-matlab/+bids/+transformers_list/Filter.m",
        ),
        (
            _tl / "get_input.m",
            "/home/neuro/bidspm/lib/bids-matlab/+bids/+transformers_list/get_input.m",
        ),
        (
            _tl / "check_field.m",
            "/home/neuro/bidspm/lib/bids-matlab/+bids/+transformers_list/check_field.m",
        ),
        (
            _tl / "identify_rows.m",
            "/home/neuro/bidspm/lib/bids-matlab/+bids/+transformers_list/identify_rows.m",
        ),
        (
            _ov / "src" / "stats" / "utils" / "validateContrasts.m",
            "/home/neuro/bidspm/src/stats/utils/validateContrasts.m",
        ),
        (
            _ov / "src" / "batches" / "stats" / "setBatchSubjectLevelContrasts.m",
            "/home/neuro/bidspm/src/batches/stats/setBatchSubjectLevelContrasts.m",
        ),
        (
            _ov / "lib" / "bids-matlab" / "+bids" / "+internal" / "return_file_index.m",
            "/home/neuro/bidspm/lib/bids-matlab/+bids/+internal/return_file_index.m",
        ),
        (
            _ov / "src" / "bids_model" / "BidsModel.m",
            "/home/neuro/bidspm/src/bids_model/BidsModel.m",
        ),
        (
            _ov / "src" / "stats" / "subject_level" / "convertOnsetTsvToMat.m",
            "/home/neuro/bidspm/src/stats/subject_level/convertOnsetTsvToMat.m",
        ),
        (
            _ov / "src" / "stats" / "subject_level" / "specifySubLvlContrasts.m",
            "/home/neuro/bidspm/src/stats/subject_level/specifySubLvlContrasts.m",
        ),
        (
            _ov / "src" / "workflows" / "stats" / "bidsResults.m",
            "/home/neuro/bidspm/src/workflows/stats/bidsResults.m",
        ),
    ]
    for local_path, container_path in _file_overrides:
        if local_path.exists():
            cmd.extend(["--bind", f"{local_path}:{container_path}"])

    # Additional bind mounts for writable directories.
    # IMPORTANT: do not shadow CPP_ROI atlas code with an empty directory, or
    # functions like returnAtlasDir.m become unavailable at runtime.
    local_cpp_roi_atlas = Path(__file__).parent.parent / "local_src" / "bidspm_local" / "lib" / "CPP_ROI" / "atlas"
    if local_cpp_roi_atlas.exists():
        cmd.extend(["--bind", f"{local_cpp_roi_atlas}:/home/neuro/bidspm/lib/CPP_ROI/atlas"])
    else:
        fallback_cpp_roi_atlas = config.WD / "cpp_roi_atlas"
        fallback_cpp_roi_atlas.mkdir(exist_ok=True)
        cmd.extend(["--bind", f"{fallback_cpp_roi_atlas}:/home/neuro/bidspm/lib/CPP_ROI/atlas"])

    for dir_name, container_path in [
        ("atlas", "/opt/spm12/atlas"),
        ("error_logs", "/home/neuro/bidspm/error_logs"),
        ("spm", "/home/neuro/spm"),
        ("matlab_cache", "/home/neuro/.matlab"),
    ]:
        local_dir = config.WD / dir_name
        local_dir.mkdir(exist_ok=True)
        cmd.extend(["--bind", f"{local_dir}:{container_path}"])
    
    # Environment variables
    cmd.extend([
        "--env", "TMPDIR=/tmp",
        "--env", "TMP=/tmp",
        "--env", "MATLAB_LOG_DIR=/tmp",
        "--env", "SPM_HTML_BROWSER=0",
        "--env", "BIDSPM_SKIP_ATLAS_INIT=1",
        "--env", f"OCTAVE_EXECUTABLE={runtime_bind_path}/octave",
        "--env", "MATLABPATH=/home/neuro/bidspm:/home/neuro/bidspm/lib/CPP_ROI:/home/neuro/bidspm/lib/CPP_ROI/atlas:/home/neuro/bidspm/lib/CPP_ROI/src:/home/neuro/bidspm/lib/CPP_ROI/src/atlas:/opt/spm12",
        "--env", "BIDSPM_IGNORE_FIELDMAPS=1",
        "--env", "BIDSPM_IGNORE_FIGURES=1",
        "--env", "BIDSPM_SKIP_INTENDEDFOR_CHECK=1"
    ])

    cmd.append(container_config.apptainer_image)
    
    # Wrap in shell to set PATH
    quoted_args = " ".join(shlex.quote(str(arg)) for arg in args)
    shell_cmd = f"export PATH={runtime_bind_path}:/usr/local/bin:/usr/bin:/bin; exec bidspm {quoted_args}"
    cmd.extend(["sh", "-c", shell_cmd])
    
    # Prepend env command for PATH
    cmd = ["env", f"APPTAINERENV_PREPEND_PATH={runtime_bind_path}"] + cmd
    
    return cmd, model_container_path


def _create_octave_wrapper(run_tmp_dir: Path):
    """Create Octave wrapper script with proper paths."""
    octave_wrapper = run_tmp_dir / "octave"
    content = '''#!/bin/bash
export MATLABPATH="/home/neuro/bidspm:/home/neuro/bidspm/lib/CPP_ROI:/home/neuro/bidspm/lib/CPP_ROI/atlas:/home/neuro/bidspm/lib/CPP_ROI/src:/home/neuro/bidspm/lib/CPP_ROI/src/atlas:/opt/spm12:$MATLABPATH"
if [ -f /usr/bin/octave ]; then REAL_OCTAVE=/usr/bin/octave
elif [ -f /usr/local/bin/octave ]; then REAL_OCTAVE=/usr/local/bin/octave
elif [ -f /usr/bin/octave-cli ]; then REAL_OCTAVE=/usr/bin/octave-cli
else REAL_OCTAVE=octave; fi
OCTAVE_INIT="/tmp/octave_init_$$.m"
echo "addpath(genpath('/home/neuro/bidspm'));" > "$OCTAVE_INIT"
exec "$REAL_OCTAVE" --eval "run('$OCTAVE_INIT');" "$@"
'''
    octave_wrapper.write_text(content)
    octave_wrapper.chmod(0o755)


def build_container_command(
    container_config: ContainerConfig,
    config: Config,
    args: List[str],
    model_file_path: Optional[Path]
) -> Tuple[List[str], Optional[str]]:
    """Build container command based on type (dispatches to specific builder)."""
    if container_config.container_type == "docker":
        return build_docker_command(container_config, config, args, model_file_path)
    elif container_config.container_type == "apptainer":
        return build_apptainer_command(container_config, config, args, model_file_path)
    else:
        raise ValueError(f"Unsupported container type: {container_config.container_type}")


# =============================================================================
# Subject/Task Discovery
# =============================================================================

def discover_subjects(config: Config) -> List[str]:
    """Discover all subjects in fMRIPrep derivatives."""
    subjects = []
    for sub_dir in config.FMRIPREP_DIR.glob("sub-*"):
        if sub_dir.is_dir():
            subject_label = sub_dir.name.replace("sub-", "")
            subjects.append(subject_label)
    return sorted(subjects)


def discover_tasks(bids_dir: Path) -> List[str]:
    """Discover tasks from BIDS directory."""
    tasks = set()
    for root, dirs, files in os.walk(bids_dir):
        if 'func' in root:
            for f in files:
                if '_task-' in f:
                    parts = f.split('_task-')
                    if len(parts) > 1:
                        task = parts[1].split('_')[0].split('.')[0]
                        tasks.add(task)
    return sorted(list(tasks))


def discover_spaces(fmriprep_dir: Path, tasks: Optional[List[str]] = None) -> List[str]:
    """Discover available spaces from fMRIPrep derivatives."""
    spaces = set()
    for root, dirs, files in os.walk(fmriprep_dir):
        if 'func' in root:
            for f in files:
                if '_desc-preproc_bold.nii.gz' in f:
                    task_match = True
                    if tasks:
                        task_match = any(f'_task-{t}_' in f for t in tasks)
                    
                    if task_match and '_space-' in f:
                        parts = f.split('_space-')
                        if len(parts) > 1:
                            space = parts[1].split('_')[0]
                            spaces.add(space)
    return sorted(list(spaces))


def check_subject_processed(config: Config, subject_label: str, task: str, action: str) -> bool:
    """Check if a subject has already been processed for the given action."""
    if action == "smooth":
        preproc_dir = config.DERIVATIVES_DIR / "bidspm-preproc" / f"sub-{subject_label}"
        if not preproc_dir.exists():
            return False
        pattern = f"*task-{task}*space-{config.SPACE}*desc-preproc_bold.nii*"
        return len(list(preproc_dir.rglob(pattern))) > 0
    
    elif action == "stats":
        stats_dir = config.DERIVATIVES_DIR / "bidspm-stats" / f"sub-{subject_label}"
        if not stats_dir.exists():
            return False
        pattern = f"task-{task}_space-{config.SPACE}_FWHM-{config.FWHM}_node-subjectLevel"
        for stats_subdir in stats_dir.glob(pattern):
            if list(stats_subdir.glob("beta_*.nii*")):
                return True
        return False
    
    return False


def estimate_processing_time(
    subjects: List[str],
    actions: List[str],
    tasks: List[str]
) -> Dict[str, Any]:
    """Estimate processing time based on subject count and actions."""
    # Average times per subject per task (in minutes)
    time_estimates = {
        "smooth": 5,
        "stats": 15,
        "dataset": 30,  # Per task, not per subject
    }
    
    total_minutes = 0
    breakdown = {}
    
    for action in actions:
        if action == "dataset":
            action_time = time_estimates[action] * len(tasks)
        else:
            action_time = time_estimates[action] * len(subjects) * len(tasks)
        breakdown[action] = action_time
        total_minutes += action_time
    
    hours = total_minutes // 60
    minutes = total_minutes % 60
    
    return {
        "total_minutes": total_minutes,
        "formatted": f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m",
        "breakdown": breakdown,
        "subjects": len(subjects),
        "tasks": len(tasks),
        "note": "Estimates based on average HPC performance. Actual time may vary."
    }


# =============================================================================
# Model Validation
# =============================================================================

_schema_cache: Dict[str, Any] = {}


def validate_bids_model(model_path: Path, skip_cache: bool = False) -> Dict[str, Any]:
    """
    Validate BIDS stats model against schema.
    Returns dict with 'valid' bool, optional 'error' or 'warning'.
    """
    global _schema_cache
    
    try:
        with open(model_path, 'r') as f:
            model_content = json.load(f)
    except json.JSONDecodeError as e:
        return {"valid": False, "error": f"Invalid JSON: {e}"}
    except FileNotFoundError:
        return {"valid": False, "error": f"Model file not found: {model_path}"}

    warnings = []
    compatibility_changes = _prepare_model_content_for_execution(model_content)
    if compatibility_changes:
        warnings.append(
            f"Normalized model for BIDS schema compatibility: {'; '.join(compatibility_changes)}"
        )
    
    # Check for empty contrasts (semantic validation)
    contrast_issues = _check_empty_contrasts(model_content)
    if contrast_issues:
        return {"valid": False, "error": f"Empty contrast issues: {'; '.join(contrast_issues)}"}
    
    # Schema validation
    try:
        import requests
        from jsonschema import validate, ValidationError
        
        schema_url = "https://bids-standard.github.io/stats-models/BIDSStatsModel.json"
        
        if schema_url not in _schema_cache or skip_cache:
            schema = requests.get(schema_url, timeout=10).json()
            _schema_cache[schema_url] = schema
        else:
            schema = _schema_cache[schema_url]
        
        validate(instance=model_content, schema=schema)
        if warnings:
            return {"valid": True, "warning": "; ".join(warnings)}
        return {"valid": True}
        
    except ValidationError as e:
        # bidspm uses "Transformer": "bidspm" which diverges from the official
        # spec value "pybids-transforms-v1". This is expected and harmless —
        # suppress the noise rather than show it on every model.
        if "'pybids-transforms-v1' was expected" in e.message or "transformer" in e.message.lower():
            return {"valid": True, "warning": "; ".join(warnings)} if warnings else {"valid": True}
        return {"valid": False, "error": f"Validation error: {e.message}"}
    except ImportError:
        return {"valid": True, "warning": "jsonschema not installed - schema validation skipped"}
    except Exception as e:
        return {"valid": False, "error": f"Validation error: {e}"}


def _check_empty_contrasts(model: Dict) -> List[str]:
    """Check for empty or missing contrast definitions."""
    issues = []
    
    if 'Steps' not in model:
        return issues
    
    for step_idx, step in enumerate(model.get('Steps', [])):
        if 'Level' not in step:
            continue
            
        for contrast in step.get('Contrasts', []):
            if 'Name' not in contrast or not contrast.get('Name', '').strip():
                issues.append(f"Step {step_idx}: Contrast missing 'Name'")
            
            if 'ConditionList' not in contrast or not contrast.get('ConditionList'):
                name = contrast.get('Name', 'unnamed')
                issues.append(f"Step {step_idx}: Contrast '{name}' has empty 'ConditionList'")
            
            if 'Weights' in contrast and not contrast.get('Weights'):
                name = contrast.get('Name', 'unnamed')
                issues.append(f"Step {step_idx}: Contrast '{name}' has empty 'Weights'")
    
    return issues


def _normalize_legacy_model_keys(node: Any) -> int:
    """Normalize legacy BIDS model keys in-place for compatibility."""
    fixes = 0

    if isinstance(node, dict):
        is_contrast = 'ConditionList' in node and 'Weights' in node
        if is_contrast and 'Type' in node and 'Test' not in node and node['Type'] in {'t', 'F', 'pass'}:
            node['Test'] = node.pop('Type')
            fixes += 1

        is_dummy_contrast = 'Contrasts' in node and 'ConditionList' not in node and 'Weights' not in node
        if is_dummy_contrast and 'Type' in node and 'Test' not in node and node['Type'] in {'t', 'F', 'pass'}:
            node['Test'] = node.pop('Type')
            fixes += 1

        is_model = 'X' in node and 'ConditionList' not in node and 'Weights' not in node
        if is_model and 'Type' not in node:
            node['Type'] = 'glm'
            fixes += 1

        for value in node.values():
            fixes += _normalize_legacy_model_keys(value)

    elif isinstance(node, list):
        for item in node:
            fixes += _normalize_legacy_model_keys(item)

    return fixes

def _strip_empty_transformations(node: Any) -> int:
    """Remove empty Transformations blocks that break local bids-matlab execution."""
    fixes = 0

    if isinstance(node, dict):
        transformations = node.get('Transformations')
        if isinstance(transformations, dict):
            instructions = transformations.get('Instructions')
            if not instructions:
                node.pop('Transformations', None)
                fixes += 1

        for value in node.values():
            fixes += _strip_empty_transformations(value)

    elif isinstance(node, list):
        for item in node:
            fixes += _strip_empty_transformations(item)

    return fixes

def _normalize_software_blocks(node: Any) -> int:
    """Normalize legacy Software fields to the schema-valid object form."""
    fixes = 0

    if isinstance(node, dict):
        software = node.get('Software')
        if 'Software' in node:
            normalized_software = None

            if isinstance(software, list):
                if not software:
                    normalized_software = None
                elif all(isinstance(item, str) for item in software):
                    normalized_software = {item: {} for item in software}
                elif all(isinstance(item, dict) and 'Name' in item for item in software):
                    normalized_software = {
                        item['Name']: {key: value for key, value in item.items() if key != 'Name'}
                        for item in software
                    }

            elif isinstance(software, str):
                normalized_software = {software: {}}

            if normalized_software is not None or isinstance(software, list):
                node['Software'] = normalized_software
                fixes += 1

        for value in node.values():
            fixes += _normalize_software_blocks(value)

    elif isinstance(node, list):
        for item in node:
            fixes += _normalize_software_blocks(item)

    return fixes

def _prepare_model_content_for_execution(model_content: Dict[str, Any]) -> List[str]:
    """Normalize model content for execution and return applied changes."""
    changes = []

    legacy_key_count = _normalize_legacy_model_keys(model_content)
    if legacy_key_count:
        changes.append(f"normalized {legacy_key_count} legacy model field(s)")

    empty_transformations_count = _strip_empty_transformations(model_content)
    if empty_transformations_count:
        changes.append(f"removed {empty_transformations_count} empty transformation block(s)")

    software_fix_count = _normalize_software_blocks(model_content)
    if software_fix_count:
        changes.append(f"normalized {software_fix_count} Software field(s)")

    return changes


# =============================================================================
# Pipeline Execution
# =============================================================================

@dataclass
class PipelineOptions:
    """Options controlling pipeline execution."""
    actions: List[str]
    config_file: str = "config/config.json"
    container_config_file: Optional[str] = None
    model_file: Optional[str] = None
    node_name: Optional[str] = None
    pilot: bool = False
    skip_validation: bool = False
    local: bool = False
    force: bool = False
    dry_run: bool = False
    debug: bool = False
    
    # Callbacks for progress reporting
    on_progress: Optional[Callable[[str], None]] = None
    on_error: Optional[Callable[[str], None]] = None


@dataclass
class PipelineResult:
    """Result of pipeline execution."""
    success: bool
    subjects_processed: List[str]
    subjects_failed: List[str]
    actions_completed: List[str]
    log_file: str
    errors: List[str]
    warnings: List[str]
    dry_run_commands: Optional[List[str]] = None
    environment_notes: Optional[List[str]] = None


class Pipeline:
    """
    Main pipeline executor - handles all BIDSPM operations.
    
    This class contains all execution logic, shared between CLI and web interface.
    """
    
    def __init__(self, options: PipelineOptions):
        self.options = options
        self.config: Optional[Config] = None
        self.container_config: Optional[ContainerConfig] = None
        self.model_file_path: Optional[Path] = None
        self.execution_model_temp_path: Optional[Path] = None
        self.matlab_caps: Optional[MatlabCapabilities] = None
        self.log_file: str = ""
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.dry_run_commands: List[str] = []
        
    def _log(self, msg: str):
        """Log message via callback or default."""
        if self.options.on_progress:
            self.options.on_progress(msg)
        else:
            print(msg)
    
    def _log_error(self, msg: str):
        """Log error via callback or default."""
        self.errors.append(msg)
        if self.options.on_error:
            self.options.on_error(msg)
        else:
            print(f"❌ {msg}")

    def _cleanup_execution_model_file(self):
        """Remove temporary sanitized model file created for execution."""
        if self.execution_model_temp_path and self.execution_model_temp_path.exists():
            self.execution_model_temp_path.unlink()
        self.execution_model_temp_path = None
    
    def validate_config(self) -> bool:
        """Validate configuration files and return True if valid."""
        from docs.json_validator import JSONValidator
        
        config_file = self.options.config_file
        
        # Check config exists and is valid JSON
        if not Path(config_file).exists():
            self._log_error(f"Config file not found: {config_file}")
            return False
        
        if not JSONValidator.is_valid_json(config_file):
            self._log_error(f"Invalid JSON in config file: {config_file}")
            return False
        
        # Schema validation
        try:
            if not JSONValidator.validate_with_schema(config_file, "config/config_schema.json"):
                self._log_error(f"Config does not match schema")
                return False
        except ImportError:
            self.warnings.append("jsonschema not installed - schema validation skipped")
        
        return True
    
    def setup(self) -> bool:
        """Initialize pipeline: load configs, detect environment, validate."""
        # Validate config
        if not self.validate_config():
            return False
        
        # Load config
        self.config = load_config(self.options.config_file)
        
        # Only auto-enable local mode from config when no explicit container config is provided.
        if (
            not self.options.local
            and not self.options.container_config_file
            and self.config.CONTAINER_TYPE == "local"
        ):
            self.options.local = True
        
        # Detect MATLAB environment for local execution
        if self.options.local:
            self.matlab_caps = detect_matlab_environment()
            self._log(f"🔍 MATLAB environment: {self.matlab_caps.environment.value}")
            
            if self.matlab_caps.limitations:
                for limit in self.matlab_caps.limitations:
                    self.warnings.append(limit)
                    self._log(f"⚠️  {limit}")
            
            # Check feature availability
            features = check_feature_availability(self.matlab_caps, using_container=False)
            for action in self.options.actions:
                if action in features.unavailable_reasons:
                    self._log_error(features.unavailable_reasons[action])
                    return False
        else:
            # Load container config
            container_file = self.options.container_config_file
            if not container_file:
                from .config import auto_select_container_config
                container_file = auto_select_container_config()
            
            if container_file and Path(container_file).exists():
                self.container_config = load_container_config(container_file)
            else:
                self._log_error("No container configuration found")
                return False
            
            # Verify container runtime
            if self.container_config.container_type == "docker":
                check_docker_availability()
            elif self.container_config.container_type == "apptainer":
                check_command("apptainer")
        
        # Handle model file
        if self._needs_model():
            if not self._resolve_model_file():
                return False
        
        # Generate log filename
        model_name = self.model_file_path.stem if self.model_file_path else "pipeline"
        self.log_file = generate_log_filename(model_name)
        
        return True
    
    def _needs_model(self) -> bool:
        """Check if current actions require a model file."""
        return 'stats' in self.options.actions or 'dataset' in self.options.actions
    
    def _resolve_model_file(self) -> bool:
        """Resolve model file path from options or config."""
        if self.options.model_file:
            cli_model_path = Path(self.options.model_file).expanduser()
            if cli_model_path.is_absolute():
                self.model_file_path = cli_model_path
            else:
                # CLI-provided relative paths should resolve from the current working directory first.
                cwd_candidate = (Path.cwd() / cli_model_path).resolve()
                derivatives_candidate = self.config.DERIVATIVES_DIR / "models" / cli_model_path
                self.model_file_path = cwd_candidate if cwd_candidate.exists() else derivatives_candidate
        elif self.config.MODELS_FILE:
            cfg_model_path = Path(self.config.MODELS_FILE).expanduser()
            if cfg_model_path.is_absolute():
                self.model_file_path = cfg_model_path
            else:
                # Keep existing behavior for config values (derivatives/models), with cwd fallback.
                derivatives_candidate = self.config.DERIVATIVES_DIR / "models" / cfg_model_path
                cwd_candidate = (Path.cwd() / cfg_model_path).resolve()
                self.model_file_path = derivatives_candidate if derivatives_candidate.exists() else cwd_candidate
        else:
            if self._needs_model():
                self._log_error("No model file specified for stats action")
                return False
            return True
        
        if not self.model_file_path.exists():
            self._log_error(f"Model file not found: {self.model_file_path}")
            return False

        try:
            with open(self.model_file_path, 'r', encoding='utf-8') as f:
                model_content = json.load(f)
        except Exception as e:
            self._log_error(f"Failed to read model file: {e}")
            return False

        execution_fixes = _prepare_model_content_for_execution(model_content)
        if execution_fixes:
            temp_path = Path("config") / f"temp_exec_model_{self.model_file_path.stem}_{random.randint(1000, 9999)}.json"
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(model_content, f, indent=2)
                f.write('\n')
            self.execution_model_temp_path = temp_path
            self.model_file_path = temp_path
            self.warnings.append(f"Execution model sanitized: {'; '.join(execution_fixes)}")
        
        # Validate model
        if not self.options.skip_validation:
            result = validate_bids_model(self.model_file_path)
            if not result["valid"]:
                self._log_error(f"Model validation failed: {result.get('error', 'Unknown error')}")
                return False
            if result.get("warning"):
                self.warnings.append(result["warning"])
        
        return True
    
    def get_subjects_to_process(self) -> List[str]:
        """Determine which subjects to process."""
        if self.options.pilot:
            all_subjects = self.config.SUBJECTS or discover_subjects(self.config)
            if not all_subjects:
                return []
            return [random.choice(all_subjects)]
        
        if self.config.SUBJECTS:
            return self.config.SUBJECTS
        
        return discover_subjects(self.config)
    
    def run(self) -> PipelineResult:
        """Execute the pipeline and return results."""
        try:
            if not self.setup():
                return PipelineResult(
                    success=False,
                    subjects_processed=[],
                    subjects_failed=[],
                    actions_completed=[],
                    log_file=self.log_file,
                    errors=self.errors,
                    warnings=self.warnings
                )

            subjects = self.get_subjects_to_process()
            if not subjects:
                self._log_error("No subjects found to process")
                return PipelineResult(
                    success=False,
                    subjects_processed=[],
                    subjects_failed=[],
                    actions_completed=[],
                    log_file=self.log_file,
                    errors=self.errors,
                    warnings=self.warnings
                )

            # Ensure derivatives has dataset_description.json
            ensure_derivatives_dataset_description(self.config.DERIVATIVES_DIR)

            subjects_processed = []
            subjects_failed = []
            actions_completed = set()

            for task in self.config.TASKS:
                self._log(f">>> Processing task: {task}")

                for subject in subjects:
                    # Validate space availability
                    if not validate_space_availability(self.config, [subject], task):
                        subjects_failed.append(subject)
                        continue

                    # Check if already processed
                    if not self.options.force:
                        if self._skip_if_processed(subject, task):
                            continue

                    # Run actions
                    success = self._process_subject(subject, task)
                    if success:
                        subjects_processed.append(subject)
                        actions_completed.update(self.options.actions)
                    else:
                        subjects_failed.append(subject)

                # Dataset-level stats
                if 'dataset' in self.options.actions:
                    self._run_dataset_stats(task)
                    actions_completed.add('dataset')

            return PipelineResult(
                success=len(subjects_failed) == 0,
                subjects_processed=list(set(subjects_processed)),
                subjects_failed=list(set(subjects_failed)),
                actions_completed=list(actions_completed),
                log_file=self.log_file,
                errors=self.errors,
                warnings=self.warnings,
                dry_run_commands=self.dry_run_commands if self.options.dry_run else None
            )
        finally:
            if self.config is not None:
                cleanup_tmp_directories(self.config)
            self._cleanup_execution_model_file()
    
    def _skip_if_processed(self, subject: str, task: str) -> bool:
        """Check if subject should be skipped (already processed)."""
        smooth_done = 'smooth' in self.options.actions and check_subject_processed(
            self.config, subject, task, "smooth"
        )
        stats_done = 'stats' in self.options.actions and check_subject_processed(
            self.config, subject, task, "stats"
        )
        
        if smooth_done and stats_done:
            self._log(f"⏭️  Subject {subject} already processed. Use --force to reprocess.")
            return True
        elif smooth_done and 'smooth' in self.options.actions and 'stats' not in self.options.actions:
            self._log(f"⏭️  Subject {subject} already smoothed.")
            return True
        elif stats_done and 'stats' in self.options.actions and 'smooth' not in self.options.actions:
            self._log(f"⏭️  Subject {subject} stats already done.")
            return True
        
        return False
    
    def _process_subject(self, subject: str, task: str) -> bool:
        """Process a single subject for the given task."""
        success = True
        
        if 'smooth' in self.options.actions:
            self._log(f">>> Smoothing: subject {subject}, task {task}")
            if not self._run_smooth(subject, task):
                success = False
        
        if 'stats' in self.options.actions:
            self._log(f">>> Stats: subject {subject}, task {task}")
            if not self._run_stats(subject, task):
                success = False
        
        return success
    
    def _run_smooth(self, subject: str, task: str) -> bool:
        """Run smoothing for a subject."""
        if self.options.local:
            return self._run_local_action("smooth", subject, task)
        else:
            return self._run_container_action("smooth", subject, task)
    
    def _run_stats(self, subject: str, task: str) -> bool:
        """Run stats for a subject."""
        if self.options.local:
            return self._run_local_action("stats", subject, task)
        else:
            return self._run_container_action("stats", subject, task)
    
    def _run_dataset_stats(self, task: str) -> bool:
        """Run dataset-level stats."""
        self._log(f">>> Dataset stats: task {task}")
        if self.options.local:
            return self._run_local_action("dataset", None, task)
        else:
            return self._run_container_dataset_action(task)
    
    def _run_container_action(self, action: str, subject: str, task: str) -> bool:
        """Run action via container."""
        if action == "smooth":
            try:
                fmriprep_rel = self.config.FMRIPREP_DIR.relative_to(self.config.DERIVATIVES_DIR)
                fmriprep_container_path = f"/derivatives/{fmriprep_rel}"
            except ValueError:
                fmriprep_container_path = "/derivatives/fmriprep"
            args = [
                fmriprep_container_path, "/derivatives", "subject", "smooth",
                "--participant_label", subject,
                "--task", task,
                "--space", self.config.SPACE,
                "--fwhm", str(self.config.FWHM),
                "--verbosity", str(max(0, self.config.VERBOSITY - 1))
            ]
        elif action == "stats":
            args = [
                "/raw", "/derivatives", "subject", "stats",
                "--preproc_dir", "/derivatives/bidspm-preproc",
                "--participant_label", subject,
                "--task", task,
                "--space", self.config.SPACE,
                "--fwhm", str(self.config.FWHM),
                "--verbosity", str(self.config.VERBOSITY)
            ]
            if self.options.node_name:
                args.extend(["--node_name", self.options.node_name])
        else:
            return False
        
        cmd, model_path = build_container_command(
            self.container_config, self.config, args, self.model_file_path
        )
        
        # Add model file for stats
        if action == "stats" and model_path:
            args_with_model = args + ["--model_file", model_path]
            cmd, _ = build_container_command(
                self.container_config, self.config, args_with_model, self.model_file_path
            )
        
        if self.options.dry_run:
            self.dry_run_commands.append(' '.join(cmd))
            self._log(f"[DRY RUN] Would execute: {' '.join(cmd[:5])}...")
            return True
        
        return run_command(cmd)
    
    def _run_container_dataset_action(self, task: str) -> bool:
        """Run dataset-level stats via container."""
        args = [
            "/raw", "/derivatives", "dataset", "stats",
            "--preproc_dir", "/derivatives/bidspm-preproc",
            "--task", task,
            "--space", self.config.SPACE,
            "--fwhm", str(self.config.FWHM),
            "--verbosity", str(self.config.VERBOSITY)
        ]
        if self.options.node_name:
            args.extend(["--node_name", self.options.node_name])
        
        cmd, model_path = build_container_command(
            self.container_config, self.config, args, self.model_file_path
        )
        
        if model_path:
            args_with_model = args + ["--model_file", model_path]
            cmd, _ = build_container_command(
                self.container_config, self.config, args_with_model, self.model_file_path
            )
        
        if self.options.dry_run:
            self.dry_run_commands.append(' '.join(cmd))
            self._log(f"[DRY RUN] Would execute dataset stats")
            return True
        
        return run_command(cmd)
    
    def _run_local_action(self, action: str, subject: Optional[str], task: str) -> bool:
        """Run action locally via MATLAB/Octave."""
        if self.matlab_caps.environment == MatlabEnvironment.NONE:
            self._log_error("No MATLAB/Octave environment available for local execution")
            return False
        
        # For standalone, check if feature is supported
        if self.matlab_caps.environment == MatlabEnvironment.MATLAB_STANDALONE:
            features = check_feature_availability(self.matlab_caps, using_container=False)
            action_key = f"{action}_subject" if action in ["smooth", "stats"] else action
            if action_key in features.unavailable_reasons:
                self._log_error(features.unavailable_reasons[action_key])
                return False
        
        # Generate and execute MATLAB script
        script = self._generate_matlab_script(action, subject, task)
        return self._execute_matlab_script(script, action, subject or "dataset", task)
    
    def _generate_matlab_script(self, action: str, subject: Optional[str], task: str) -> str:
        """Generate MATLAB/Octave script for local execution."""
        local_bidspm_dir = Path("local_src/bidspm_local").absolute()
        
        header = f"""
% BIDSPM Local Execution Script - {action}
warning('off', 'all');

% Add paths
spm12_path = fullfile(pwd, 'external/spm12_standalone');
if exist(spm12_path, 'dir')
    addpath(spm12_path);
end

bidspm_path = '{local_bidspm_dir}';
if exist(bidspm_path, 'dir')
    addpath(bidspm_path);
    if exist('bidspm', 'file')
        bidspm('init');
    end
end

try
    if exist('spm', 'file')
        spm('defaults', 'fmri');
        spm_jobman('initcfg');
    end
catch
end

try
"""
        
        if action == "smooth":
            body = f"""
    bidspm('{self.config.FMRIPREP_DIR}', ...
           '{self.config.DERIVATIVES_DIR}', ...
           'subject', ...
           'action', 'smooth', ...
           'participant_label', {{'{subject}'}}, ...
           'task', {{'{task}'}}, ...
           'space', {{'{self.config.SPACE}'}}, ...
           'fwhm', {self.config.FWHM}, ...
           'verbosity', {self.config.VERBOSITY});
    fprintf('Smoothing completed successfully\\n');
    exit(0);
"""
        elif action == "stats":
            preproc = self.config.FMRIPREP_DIR
            node_name_clause = ""
            if self.options.node_name:
                node_name_clause = f"           'node_name', '{self.options.node_name}', ...\n"
            body = f"""
    preproc_dir = '{preproc}';
    bidspm('{self.config.BIDS_DIR}', ...
           '{self.config.DERIVATIVES_DIR}', ...
           'subject', ...
           'action', 'stats', ...
           'participant_label', {{'{subject}'}}, ...
           'task', {{'{task}'}}, ...
           'space', {{'{self.config.SPACE}'}}, ...
           'fwhm', {self.config.FWHM}, ...
           'model_file', '{self.model_file_path.absolute()}', ...
           'preproc_dir', preproc_dir, ...
{node_name_clause}           'verbosity', {self.config.VERBOSITY});
    fprintf('Stats completed successfully\\n');
    exit(0);
"""
        elif action == "dataset":
            node_name_clause = ""
            if self.options.node_name:
                node_name_clause = f"           'node_name', '{self.options.node_name}', ...\n"
            body = f"""
    bidspm('{self.config.BIDS_DIR}', ...
           '{self.config.DERIVATIVES_DIR}', ...
           'dataset', ...
           'action', 'stats', ...
           'task', {{'{task}'}}, ...
           'space', {{'{self.config.SPACE}'}}, ...
           'fwhm', {self.config.FWHM}, ...
           'model_file', '{self.model_file_path.absolute()}', ...
{node_name_clause}           'verbosity', {self.config.VERBOSITY});
    fprintf('Dataset stats completed successfully\\n');
    exit(0);
"""
        else:
            body = "    error('Unsupported action');\n"
        
        footer = """
catch ME
    fprintf('Error: %s\\n', ME.message);
    exit(1);
end
"""
        
        return header + body + footer
    
    def _execute_matlab_script(self, script: str, action: str, subject: str, task: str) -> bool:
        """Execute generated MATLAB script."""
        script_file = Path(f"bidspm_local_{action}_{subject}_{task}.m")
        script_file.write_text(script)
        _timeout_map = {
            "smooth": int(getattr(self.config, "SMOOTH_TIMEOUT_SECONDS", 900) or 900),
            "stats": int(getattr(self.config, "STATS_TIMEOUT_SECONDS", 300) or 300),
            "dataset": int(getattr(self.config, "DATASET_TIMEOUT_SECONDS", 300) or 300),
        }
        timeout_seconds = max(1, _timeout_map.get(action, int(getattr(self.config, "LOCAL_ACTION_TIMEOUT_SECONDS", 900) or 900)))
        
        try:
            matlab_path = self.matlab_caps.path
            
            if self.matlab_caps.environment == MatlabEnvironment.MATLAB_LICENSED:
                cmd = [matlab_path, "-nodisplay", "-nosplash", "-nodesktop", "-r", f"run('{script_file.stem}')"]
            else:  # Octave
                cmd = [matlab_path, "--no-gui", "--eval", f"run('{script_file.stem}')"]
            
            if self.options.dry_run:
                self.dry_run_commands.append(' '.join(cmd))
                self._log(f"[DRY RUN] Would execute: {' '.join(cmd)}")
                return True
            
            bidspm_error_seen = False
            proc = subprocess.Popen(
                cmd, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=self._get_local_env(),
            )
            output_lines = []
            try:
                for line in proc.stdout:
                    line_stripped = line.rstrip()
                    self._log(line_stripped)
                    output_lines.append(line_stripped)
                    if "bidspm - ERROR" in line_stripped:
                        bidspm_error_seen = True
                proc.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                self._log_error(f"{action} timed out for {subject} after {timeout_seconds} seconds")
                return False

            if proc.returncode != 0:
                self._log_error(f"{action} failed for {subject} (exit code {proc.returncode})")
                return False

            if bidspm_error_seen:
                self._log_error(f"{action} failed for {subject}: bidspm reported an ERROR (exit code was 0)")
                return False

            self._log(f"✅ {action} completed for {subject}")
            return True

        except Exception as e:
            self._log_error(f"{action} failed for {subject}: {e}")
            return False
        finally:
            if script_file.exists():
                script_file.unlink()
    
    def _get_local_env(self) -> Dict[str, str]:
        """Get environment for local execution."""
        env = os.environ.copy()
        project_root = Path.cwd().absolute()
        
        env["BIDSPM_PROJECT_ROOT"] = str(project_root)
        env["SPM12_PATH"] = str(project_root / "external" / "spm12_standalone")
        env["BIDSPM_PATH"] = str(project_root / "local_src" / "bidspm_local")
        env["SPM_HOME"] = env["SPM12_PATH"]
        
        # Octave paths
        local_octave = project_root / "external" / "octave"
        if local_octave.exists():
            env["OCTAVE_HOME"] = str(local_octave)
            env["PATH"] = f"{local_octave / 'bin'}:{env.get('PATH', '')}"
            
            # Local Octave binaries need their bundled shared libs on LD_LIBRARY_PATH.
            octave_lib_root = local_octave / "lib" / "octave"
            if octave_lib_root.exists():
                version_dirs = [
                    p for p in octave_lib_root.iterdir()
                    if p.is_dir() and re.match(r"^\d+(\.\d+)*$", p.name)
                ]
                if version_dirs:
                    octave_lib_dir = str(sorted(version_dirs, key=lambda p: p.name)[-1])
                    existing_ld = env.get("LD_LIBRARY_PATH", "")
                    env["LD_LIBRARY_PATH"] = f"{octave_lib_dir}:{existing_ld}" if existing_ld else octave_lib_dir
        
        return env
