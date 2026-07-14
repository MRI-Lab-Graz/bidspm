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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable, Tuple

from .config import Config, ContainerConfig, load_config, load_container_config
from .fast_smooth import smooth_subjects_parallel
from .utils import (
    log, log_debug, log_error, log_error_non_fatal,
    generate_log_filename, check_command, check_docker_availability,
    run_command, validate_space_availability, validate_events_availability,
    ensure_derivatives_dataset_description, cleanup_tmp_directories
)


# =============================================================================
# Container Command Building (Split by Type)
# =============================================================================

def _get_cpp_roi_atlas_cache_dir(config: Config) -> Path:
    """Return (creating if needed) the persistent CPP_ROI atlas cache dir.

    The image's own (patched) copyAtlasToSpmDir.m populates this lazily on
    first use per atlas, so neither the repo nor the image needs to ship the
    underlying atlas data (300+MB).
    """
    atlas_cache_dir = config.WD / "cpp_roi_atlas"
    atlas_cache_dir.mkdir(parents=True, exist_ok=True)
    return atlas_cache_dir


def build_docker_command(
    container_config: ContainerConfig,
    config: Config,
    args: List[str],
    model_file_path: Optional[Path],
    override_entrypoint: Optional[List[str]] = None
) -> Tuple[List[str], Optional[str]]:
    """Build Docker container command.

    ``override_entrypoint``, when given, replaces the normal ``bidspm <args>``
    call with an arbitrary command (e.g. a direct ``octave --eval ...`` call)
    while still setting up all the same binds/overrides -- used by BMS, whose
    action the bidspm Python CLI does not implement yet (see run_bms()).
    """
    if not container_config.docker_image:
        raise ValueError("Docker image not specified in container configuration.")
    
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{config.BIDS_DIR}:/raw",
        "-v", f"{config.BIDS_DIR}:{config.BIDS_DIR}",
        "-v", f"{config.DERIVATIVES_DIR}:/derivatives",
        "-v", f"{config.FMRIPREP_DIR}:/fmriprep"
    ]
    
    # Create tmp directory for this run
    run_tmp_dir = config.WD / "tmp" / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"
    run_tmp_dir.mkdir(parents=True, exist_ok=True)
    cmd.extend(["-v", f"{run_tmp_dir}:/tmp"])
    
    # Handle model file/dir path (a directory is used for BMS's --models_dir,
    # which needs a folder of competing smdl.json files, not a single file).
    model_container_path = None
    if model_file_path:
        try:
            rel_path = model_file_path.relative_to(config.DERIVATIVES_DIR)
            model_container_path = f"/derivatives/{rel_path}"
        except ValueError:
            if model_file_path.is_dir():
                cmd.extend(["-v", f"{model_file_path}:/models/bms_models:ro"])
                model_container_path = "/models/bms_models"
            else:
                cmd.extend(["-v", f"{model_file_path}:/models/smdl.json"])
                model_container_path = "/models/smdl.json"

    # Lazily-populated atlas cache: the image's own copyAtlasToSpmDir.m fills
    # this in on first use per atlas, so it persists across runs without
    # needing to ship or bake in the (300+MB) atlas data itself.
    atlas_cache_dir = _get_cpp_roi_atlas_cache_dir(config)
    cmd.extend(["-v", f"{atlas_cache_dir}:/home/neuro/bidspm/lib/CPP_ROI/atlas"])

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
    cmd.extend(override_entrypoint if override_entrypoint is not None else args)
    return cmd, model_container_path


def build_apptainer_command(
    container_config: ContainerConfig,
    config: Config,
    args: List[str],
    model_file_path: Optional[Path],
    override_entrypoint: Optional[List[str]] = None
) -> Tuple[List[str], Optional[str]]:
    """Build Apptainer/Singularity container command.

    ``override_entrypoint``, when given, replaces the normal ``bidspm <args>``
    call with an arbitrary command (e.g. a direct ``octave --eval ...`` call)
    while still setting up all the same binds/overrides -- used by BMS, whose
    action the bidspm Python CLI does not implement yet (see run_bms()).
    """
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
        "--bind", f"{config.DERIVATIVES_DIR}:/derivatives",
        "--bind", f"{config.FMRIPREP_DIR}:/fmriprep"
    ]
    
    # Handle model file/dir path (a directory is used for BMS's --models_dir,
    # which needs a folder of competing smdl.json files, not a single file).
    model_container_path = None
    if model_file_path:
        try:
            rel_path = model_file_path.relative_to(config.DERIVATIVES_DIR)
            model_container_path = f"/derivatives/{rel_path}"
        except ValueError:
            if model_file_path.is_dir():
                cmd.extend(["--bind", f"{model_file_path}:/models/bms_models:ro"])
                model_container_path = "/models/bms_models"
            else:
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
        # Use the container-side mount path, not the host path —
        # inside the container the tmp dir is at runtime_bind_path, not _runner.parent
        _runner_container = f"{runtime_bind_path}/bids-validator-runner.js"
        _wrapper.write_text(
            f"#!/bin/sh\nexec {_host_node} {_runner_container} \"$@\"\n"
        )
        _wrapper.chmod(0o755)
        cmd.extend([
            "--bind", f"{_host_node}:/usr/bin/node",
            "--bind", f"{_bids_cli}:/usr/lib/node_modules/bids-validator/dist/commonjs/cli.js",
            "--bind", f"{_wrapper}:/usr/bin/bids-validator",
        ])

    # Lazily-populated atlas cache: the image's own copyAtlasToSpmDir.m fills
    # this in on first use per atlas, so it persists across runs without
    # needing to ship or bake in the (300+MB) atlas data itself.
    atlas_cache_dir = _get_cpp_roi_atlas_cache_dir(config)
    cmd.extend(["--bind", f"{atlas_cache_dir}:/home/neuro/bidspm/lib/CPP_ROI/atlas"])

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
    entrypoint = override_entrypoint if override_entrypoint is not None else ["bidspm"] + args
    quoted_entrypoint = " ".join(shlex.quote(str(arg)) for arg in entrypoint)
    shell_cmd = f"export PATH={runtime_bind_path}:/usr/local/bin:/usr/bin:/bin; exec {quoted_entrypoint}"
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
    model_file_path: Optional[Path],
    override_entrypoint: Optional[List[str]] = None
) -> Tuple[List[str], Optional[str]]:
    """Build container command based on type (dispatches to specific builder)."""
    if container_config.container_type == "docker":
        return build_docker_command(container_config, config, args, model_file_path, override_entrypoint)
    elif container_config.container_type == "apptainer":
        return build_apptainer_command(container_config, config, args, model_file_path, override_entrypoint)
    else:
        raise ValueError(f"Unsupported container type: {container_config.container_type}")


# =============================================================================
# Bayesian Model Selection (BMS)
# =============================================================================
#
# bidspm (v4.0.0) already ships first-level Bayesian Model Selection via the
# bundled MACS toolbox (src/workflows/stats/bidsModelSelection.m), reachable
# from the MATLAB function as bidspm(..., 'action', 'bms', 'models_dir', DIR).
# However the container's own Python CLI entrypoint (`bidspm` on PATH) has
# 'bms' hardcoded into a NOT_IMPLEMENTED set (bidspm/src/bidspm/cli.py) even
# though the command-builder and MATLAB dispatch both work -- confirmed by
# calling the MATLAB function directly. So this calls octave directly inside
# the container instead of going through the `bidspm` CLI entrypoint, mirroring
# how this wrapper's local (non-container) execution mode already invokes
# bidspm() directly for smooth/stats/dataset.
#
# It globs every *_smdl.json in --models_dir as the competing models
# (src/defaults/getOptionsFromModel.m -- note the required _smdl.json suffix,
# not just any .json), so that directory must contain only the models being
# compared, named accordingly. Each competing model's Input must include the
# same `space` and `task` (src/workflows/stats/bidsModelSelection.m: checks()),
# and `stats` must already have been run for every competing model (BMS
# compares their already-estimated SPM.mat files, it does not estimate
# anything itself).

def resolve_models_dir(models_dir: str) -> Path:
    """Validate a directory of competing BIDS Stats Model files for BMS.

    bidspm globs every ``*_smdl.json`` in this directory as a competing
    model, so it must be dedicated to exactly the models being compared,
    named with that suffix.
    """
    path = Path(models_dir).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"Models directory not found: {path}")
    json_files = sorted(path.glob("*_smdl.json"))
    if len(json_files) < 2:
        raise ValueError(
            f"BMS needs at least 2 competing model files matching "
            f"*_smdl.json in {path}, found {len(json_files)}. bidspm globs "
            "exactly that pattern as competing models (src/defaults/"
            "getOptionsFromModel.m) -- keep this directory dedicated to the "
            "models being compared, named with the _smdl.json suffix."
        )
    return path


def run_bms(
    config_file: str,
    container_config_file: Optional[str],
    models_dir: str,
    fwhm: Optional[float] = None,
    participant_label: Optional[List[str]] = None,
    dry_run: bool = False,
    skip_validation: bool = False,
    on_progress: Optional[Callable[[str], None]] = None,
    bms_action: str = "bms",
) -> Dict[str, Any]:
    """Run Bayesian Model Selection across a directory of competing models.

    Container execution only -- BMS needs the MACS toolbox, which ships
    inside the bidspm container image. Local/Octave execution is not wired
    up for this action.

    ``bms_action`` mirrors bidsModelSelection.m's own split-friendly actions
    (see cliBayesModel.m): 'bms' runs all steps (model space, cvLME,
    posterior, BMS group); 'bms-cvlme' runs just model space + cvLME for
    ``participant_label`` -- safe to run as several parallel calls on
    disjoint subject subsets, since it only ever writes into each subject's
    own stats directory; 'bms-posterior' and 'bms-bms' run the remaining
    group-level steps and must be run once, after every subject's cvLME
    step has completed, with the full participant list.
    """
    def _log(msg: str):
        if on_progress:
            on_progress(msg)
        else:
            print(msg)

    errors: List[str] = []

    try:
        resolved_models_dir = resolve_models_dir(models_dir)
    except ValueError as e:
        errors.append(str(e))
        return {"success": False, "errors": errors, "dry_run_commands": []}

    config = load_config(config_file)

    container_file = container_config_file
    if not container_file:
        from .config import auto_select_container_config
        container_file = auto_select_container_config()

    if not container_file or not Path(container_file).exists():
        errors.append("No container configuration found (BMS requires container execution).")
        return {"success": False, "errors": errors, "dry_run_commands": []}

    container_config = load_container_config(container_file)

    if container_config.container_type == "docker":
        check_docker_availability()
    elif container_config.container_type == "apptainer":
        check_command("apptainer")

    effective_fwhm = fwhm if fwhm is not None else config.FWHM

    # First pass just to learn where the models dir gets mounted -- the mount
    # path doesn't depend on the entrypoint, so args/entrypoint are dummies.
    _, models_dir_container_path = build_container_command(
        container_config, config, [], resolved_models_dir
    )

    matlab_args = [
        "'/raw'", "'/derivatives'", "'subject'",
        "'action'", f"'{bms_action}'",
        "'fwhm'", str(effective_fwhm),
        "'verbosity'", str(config.VERBOSITY),
        "'models_dir'", f"'{models_dir_container_path}'",
    ]
    if participant_label:
        labels = ",".join(f"'{p}'" for p in participant_label)
        matlab_args.extend(["'participant_label'", f"{{{labels}}}"])
    if dry_run:
        matlab_args.extend(["'dry_run'", "true"])
    if skip_validation:
        matlab_args.extend(["'skip_validation'", "true"])

    matlab_call = f"bidspm({', '.join(matlab_args)})"
    octave_eval = (
        "bidspm('init'); try; "
        f"{matlab_call}; "
        "catch ME; fprintf('bidspm - ERROR - %s\\n', ME.message); exit(1); end; "
        "exit(0);"
    )
    override_entrypoint = ["octave", "--no-gui", "--no-window-system", "--silent", "--eval", octave_eval]

    cmd, _ = build_container_command(
        container_config, config, [], resolved_models_dir, override_entrypoint=override_entrypoint
    )

    if dry_run:
        _log(f"[DRY RUN] Would execute: {' '.join(cmd)}")
        return {"success": True, "errors": errors, "dry_run_commands": [' '.join(cmd)]}

    _log(f">>> Running BMS across models in {resolved_models_dir}")
    success = run_command(cmd)
    if not success:
        errors.append("BMS run failed -- see log output above.")
    return {"success": success, "errors": errors, "dry_run_commands": []}


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


def _normalize_node_label(name: Optional[str]) -> str:
    """Strip non-alphanumerics and lowercase, for tolerant node-name matching."""
    return re.sub(r'[^a-zA-Z0-9]', '', name or '').lower()


# Node names that getFFXdir.m omits the _node- suffix for entirely (after the
# same stripping it applies: regexprep(nodeName, '[ -_]', '')).
_FFX_UNNAMED_NODE_LABELS = {'run', 'runlevel'}


# Files bidspm's CPP_ROI/copyAtlasToSpmDir.m populates into the shared
# host atlas cache dir (config.WD / "atlas", bind-mounted read/write into
# every concurrent container as /opt/spm12/atlas). When this cache is empty,
# multiple concurrent stats-workers can each see it as empty at the same
# time and race on the Wang-atlas merge-then-delete step in a *separate*
# shared source dir (CPP_ROI's own atlas/ tree) -- confirmed live: this
# caused sporadic "delete: no such file" / copyfile crashes for ~4% of
# subjects in a 12-way-parallel batch. Once the target cache dir already has
# these files, copyAtlasToSpmDir.m's own atlasPresent check short-circuits
# before touching the shared source dir at all, so pre-warming it with one
# sequential run eliminates the race entirely (see _atlas_cache_is_warm()).
_ATLAS_CACHE_FILES = [
    "AAL3v1_1mm.nii", "AAL3v1_1mm.xml",
    "HCPex.nii", "HCPex.xml",
    "space-MNI152ICBM2009anlin_seg-glasser_dseg.nii",
    "space-MNI152ICBM2009anlin_seg-glasser_dseg.xml",
    "space-MNI_seg-visfAtlas_dseg.nii", "space-MNI_seg-visfAtlas_dseg.xml",
    "space-MNI_seg-wang_dseg.nii", "space-MNI_seg-wang_dseg.xml",
]


def _atlas_cache_is_warm(config: Config) -> bool:
    atlas_dir = config.WD / "atlas"
    return all((atlas_dir / f).exists() for f in _ATLAS_CACHE_FILES)


def check_subject_processed(
    config: Config, subject_label: str, task: str, action: str,
    node_name: Optional[str] = None
) -> bool:
    """Check if a subject has already been processed for the given action.

    ``node_name`` (for ``action="stats"``) is the current model's Run-level
    node Name (see _get_run_node_name()). Different competing models produce
    separate `_node-<Name>` output folders (see A1 in
    docs/roadmap-model-variants-bms.md) -- without checking the specific
    node, this would report "already processed" as soon as *any* model's
    output exists for this subject/task/space/fwhm, silently skipping every
    other model. Confirmed live: this caused a 100-subject x 5-model stats
    batch to silently skip ~96-100% of subjects for 4 of the 5 models.
    """
    if action == "smooth":
        preproc_dir = config.DERIVATIVES_DIR / "bidspm-preproc" / f"sub-{subject_label}"
        if not preproc_dir.exists():
            return False
        pattern = f"*task-{task}*space-{config.SPACE}*desc-smth{config.FWHM}_bold.nii*"
        return len(list(preproc_dir.rglob(pattern))) > 0

    elif action == "stats":
        stats_dir = config.DERIVATIVES_DIR / "bidspm-stats" / f"sub-{subject_label}"
        if not stats_dir.exists():
            return False
        expected = _normalize_node_label(node_name) if node_name else None
        pattern = f"task-{task}_space-{config.SPACE}_FWHM-{config.FWHM}*"
        for stats_subdir in stats_dir.glob(pattern):
            if not list(stats_subdir.glob("beta_*.nii*")):
                continue
            match = re.search(r'_node-([^_]+)$', stats_subdir.name)
            if match:
                # No node_name given means the caller isn't disambiguating between
                # competing models (e.g. the GUI's stats-coverage report checks
                # "has this subject been processed at all") -- any named node counts.
                if expected is None or _normalize_node_label(match.group(1)) == expected:
                    return True
            else:
                # No _node- suffix: only matches a model whose node name is
                # itself one that getFFXdir.m omits the suffix for (or if we
                # have no expected node name to disambiguate against).
                if expected is None or expected in _FFX_UNNAMED_NODE_LABELS:
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
        "bms": 20,  # Per task, not per subject -- compares already-estimated models
    }

    total_minutes = 0
    breakdown = {}

    for action in actions:
        if action not in time_estimates:
            continue
        if action in ("dataset", "bms"):
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

    warnings.extend(_check_dataset_edge_filters(model_content))

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

    # BIDS stats model 1.0 uses "Nodes"; older drafts used "Steps".
    nodes = model.get('Nodes', model.get('Steps', []))

    for node_idx, node in enumerate(nodes):
        if 'Level' not in node:
            continue

        node_name = node.get('Name', f'node {node_idx}')

        if 'Contrasts' in node and node['Contrasts'] == []:
            issues.append(f"Node '{node_name}': Contrasts is an empty list — omit the key instead")

        for contrast in node.get('Contrasts', []):
            if not isinstance(contrast, dict):
                continue
            if 'Name' not in contrast or not contrast.get('Name', '').strip():
                issues.append(f"Node '{node_name}': contrast missing 'Name'")

            if 'ConditionList' not in contrast or not contrast.get('ConditionList'):
                name = contrast.get('Name', 'unnamed')
                issues.append(f"Node '{node_name}': contrast '{name}' has empty 'ConditionList'")

            if 'Weights' in contrast and not contrast.get('Weights'):
                name = contrast.get('Name', 'unnamed')
                issues.append(f"Node '{node_name}': contrast '{name}' has empty 'Weights'")

        dummy = node.get('DummyContrasts')
        if isinstance(dummy, dict) and 'Contrasts' in dummy and dummy['Contrasts'] == []:
            issues.append(f"Node '{node_name}': DummyContrasts.Contrasts is an empty list — omit the key to use all model variables")

    return issues


def _check_dataset_edge_filters(model: Dict) -> List[str]:
    """Warn when an Edge into a Dataset-level node omits Filter.contrast.

    Per the BIDS Stats Models docs, an Edge feeding a Dataset-level node should
    explicitly set Filter.contrast to pick which upstream contrast(s) flow in —
    https://bidspm.readthedocs.io/en/latest/stats/bids_stats_model.html#dataset-level
    """
    warnings = []

    nodes = model.get('Nodes', model.get('Steps', []))
    dataset_node_names = {
        str(node.get('Name', '')).strip()
        for node in nodes
        if isinstance(node, dict) and str(node.get('Level', '')).strip() == 'Dataset'
    }
    if not dataset_node_names:
        return warnings

    for edge in model.get('Edges', []):
        if not isinstance(edge, dict):
            continue
        destination = str(edge.get('Destination', '')).strip()
        if destination not in dataset_node_names:
            continue

        contrast_filter = edge.get('Filter', {}).get('contrast') if isinstance(edge.get('Filter'), dict) else None
        if not contrast_filter:
            source = edge.get('Source', 'unknown source')
            warnings.append(
                f"Edge '{source}' -> '{destination}': Destination is a Dataset-level node "
                "but Filter.contrast is not set"
            )

    return warnings


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

def _get_run_node_name(model_content: Dict[str, Any]) -> Optional[str]:
    """Resolve the Run-level (root) node's Name from a parsed BIDS Stats Model.

    This mirrors which node getFFXdir.m derives the stats output folder name
    from -- used to check for already-processed subjects against the correct
    node folder rather than any node folder (see check_subject_processed()).
    """
    nodes = model_content.get('Nodes', model_content.get('Steps', []))
    for node in nodes:
        if str(node.get('Level', '')).lower() == 'run':
            return node.get('Name')
    if nodes:
        return nodes[0].get('Name')
    return None


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
    smooth_backend: str = "fast"
    stats_workers: int = 4
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
        self.stats_node_name: Optional[str] = None
        self.execution_model_temp_path: Optional[Path] = None
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

        # Used by check_subject_processed() to tell this model's stats output
        # apart from other competing models' -- see its docstring.
        self.stats_node_name = self.options.node_name or _get_run_node_name(model_content)

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

                if 'smooth' in self.options.actions and self.options.smooth_backend == 'fast':
                    self._log(f">>> Fast-smoothing {len(subjects)} subject(s) in parallel (task {task})")
                    smooth_results = smooth_subjects_parallel(
                        self.config, subjects, task, force=self.options.force
                    )
                    for subject, result in smooth_results.items():
                        status = result.get("status")
                        if status == "no_input":
                            self._log_error(
                                f"No preprocessed data found for subject {subject}: "
                                f"{result.get('message')}. Check that fMRIPrep has been "
                                f"run for this subject."
                            )
                        elif status == "error":
                            self._log_error(
                                f"Fast smoothing failed for subject {subject}: {result.get('message')}"
                            )
                        elif status == "skipped":
                            self._log(
                                f"⏭️  Subject {subject} already smoothed. Use --force to reprocess."
                            )
                        elif status == "ok":
                            # Record this here: the per-subject loop below will
                            # see the file we just wrote and skip it as
                            # "already processed", which would otherwise make
                            # work done in this run vanish from the summary.
                            subjects_processed.append(subject)
                            actions_completed.add('smooth')

                # Validation and the already-processed check are kept sequential and
                # upfront in the main thread -- only the actual per-subject work
                # (container/local MATLAB invocation) runs in the worker pool below.
                eligible_subjects = []
                for subject in subjects:
                    # Validate space availability
                    if not validate_space_availability(self.config, [subject], task):
                        subjects_failed.append(subject)
                        continue

                    # Events.tsv are required to build the GLM design matrix.
                    # bidspm's own MATLAB code only warns (doesn't block) when
                    # they're missing, so we block explicitly here instead.
                    if 'stats' in self.options.actions and not validate_events_availability(
                        self.config, [subject], task
                    ):
                        subjects_failed.append(subject)
                        continue

                    # Check if already processed
                    if not self.options.force:
                        if self._skip_if_processed(subject, task):
                            continue

                    eligible_subjects.append(subject)

                max_workers = max(1, min(self.options.stats_workers, len(eligible_subjects))) \
                    if eligible_subjects else 1

                # Avoid a known race in bidspm's CPP_ROI atlas init: process one
                # subject sequentially first so the shared atlas cache is fully
                # populated before any concurrent workers can race on it (see
                # _atlas_cache_is_warm() docstring for the full mechanism).
                if (
                    max_workers > 1
                    and 'stats' in self.options.actions
                    and not _atlas_cache_is_warm(self.config)
                ):
                    self._log(
                        ">>> Warming shared atlas cache with one sequential subject "
                        "before parallelizing (avoids a race in bidspm's atlas init "
                        "when multiple workers hit an empty cache at once)"
                    )
                    warm_subject = eligible_subjects.pop(0)
                    if self._process_subject(warm_subject, task):
                        subjects_processed.append(warm_subject)
                        actions_completed.update(self.options.actions)
                    else:
                        subjects_failed.append(warm_subject)
                    max_workers = max(1, min(self.options.stats_workers, len(eligible_subjects))) \
                        if eligible_subjects else 1

                if max_workers <= 1:
                    for subject in eligible_subjects:
                        success = self._process_subject(subject, task)
                        if success:
                            subjects_processed.append(subject)
                            actions_completed.update(self.options.actions)
                        else:
                            subjects_failed.append(subject)
                else:
                    self._log(
                        f">>> Processing {len(eligible_subjects)} subject(s) with "
                        f"{max_workers} worker(s) (task {task})"
                    )
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        futures = {
                            executor.submit(self._process_subject, subject, task): subject
                            for subject in eligible_subjects
                        }
                        # Collect results here in the main thread only -- workers must
                        # never touch subjects_processed/subjects_failed/actions_completed
                        # directly, to avoid races on these shared lists/set.
                        for future in as_completed(futures):
                            subject = futures[future]
                            try:
                                success = future.result()
                            except Exception as exc:
                                self._log_error(f"Unhandled error processing subject {subject}: {exc}")
                                success = False
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
            self.config, subject, task, "stats", node_name=self.stats_node_name
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
            self._copy_brain_mask(subject, task)
            if not self._run_stats(subject, task):
                success = False

        return success

    def _copy_brain_mask(self, subject: str, task: str) -> None:
        """Copy fmriprep's brain mask for this subject/task/space into bidspm-preproc.

        The "stats" action only indexes /raw and /derivatives/bidspm-preproc as BIDS
        datasets (see --preproc_dir in _run_container_action) -- it never sees files
        that live only under FMRIPREP_DIR. Without this, a model's explicit Mask can
        never be resolved and SPM silently falls back to its own loose intracerebral
        mask, which inflates voxel count (and ReML/estimation runtime) for every GLM.
        """
        config = self.config
        pattern = f"sub-{subject}_*task-{task}_space-{config.SPACE}_desc-brain_mask.nii*"
        for mask_src in sorted(config.FMRIPREP_DIR.rglob(pattern)):
            rel = mask_src.relative_to(config.FMRIPREP_DIR)
            is_gz = mask_src.name.endswith(".nii.gz")
            # bidspm-preproc is exclusively plain .nii (its own smoothing step always
            # decompresses); a gzipped mask makes matlabbatch's cfg_files harvest drop
            # the entry silently, leaving spm_run_fmri_spec with an empty job.mask{1}.
            dst_name = rel.name[:-len(".gz")] if is_gz else rel.name
            mask_dst = config.DERIVATIVES_DIR / "bidspm-preproc" / rel.parent / dst_name
            mask_dst.parent.mkdir(parents=True, exist_ok=True)
            if not mask_dst.exists() or mask_dst.stat().st_mtime < mask_src.stat().st_mtime:
                if is_gz:
                    import gzip
                    with gzip.open(mask_src, "rb") as f_in, open(mask_dst, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                else:
                    shutil.copy2(mask_src, mask_dst)

            json_name = mask_src.name[:-len(".nii.gz")] + ".json" if is_gz \
                else mask_src.with_suffix(".json").name
            json_src = mask_src.with_name(json_name)
            if json_src.exists():
                json_dst = mask_dst.with_name(json_name)
                if not json_dst.exists() or json_dst.stat().st_mtime < json_src.stat().st_mtime:
                    shutil.copy2(json_src, json_dst)

    def _run_smooth(self, subject: str, task: str) -> bool:
        """Run smoothing for a subject."""
        return self._run_container_action("smooth", subject, task)

    def _run_stats(self, subject: str, task: str) -> bool:
        """Run stats for a subject."""
        return self._run_container_action("stats", subject, task)

    def _run_dataset_stats(self, task: str) -> bool:
        """Run dataset-level stats."""
        self._log(f">>> Dataset stats: task {task}")
        return self._run_container_dataset_action(task)
    
    def _run_container_action(self, action: str, subject: str, task: str) -> bool:
        """Run action via container."""
        if action == "smooth":
            args = [
                "/fmriprep", "/derivatives", "subject", "smooth",
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
        if self.config.SUBJECTS:
            args.extend(["--participant_label"] + list(self.config.SUBJECTS))
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

