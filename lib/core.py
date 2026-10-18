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
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Sequence, List, Optional, Dict, Any, Callable, Tuple

from .spm_standalone import (
    build_spm_standalone_command,
    check_image as check_spm_image,
    find_new_spm_mats,
    is_estimated,
    write_estimation_job,
)
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

def _model_container_path(
    model_file_path: Optional[Path],
    derivatives_dir: Path,
) -> Optional[str]:
    """Return the container-side path for a model file or directory.

    Mirrors the path-resolution logic inside build_docker_command /
    build_apptainer_command so callers can compute the path before
    building the full command (avoiding a double invocation).
    """
    if model_file_path is None:
        return None
    try:
        rel = model_file_path.relative_to(derivatives_dir)
        return f"/derivatives/{rel}"
    except ValueError:
        if model_file_path.is_dir():
            return "/models/bms_models"
        return "/models/smdl.json"


def build_docker_command(
    container_config: ContainerConfig,
    config: Config,
    args: List[str],
    model_file_path: Optional[Path],
    override_entrypoint: Optional[List[str]] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> Tuple[List[str], Optional[str]]:
    """Build Docker container command.

    ``override_entrypoint``, when given, replaces the normal ``bidspm <args>``
    call with an arbitrary command (e.g. a direct ``octave --eval ...`` call)
    while still setting up all the same binds/overrides -- used by BMS, whose
    action the bidspm Python CLI does not implement yet (see run_bms()).
    """
    if not container_config.docker_image:
        raise ValueError("Docker image not specified in container configuration.")

    cmd = ["docker", "run", "--rm"]
    # The image runs as its own baked-in user (uid 1000), not the host user
    # (unlike Apptainer, which runs as the invoking host user by default).
    # Without this, writes into host-owned bind mounts like derivatives/ fail
    # with permission errors whenever the host uid isn't 1000. Not available
    # on Windows, where Docker Desktop's filesystem sharing doesn't have this
    # uid-mismatch problem in the first place.
    if hasattr(os, "getuid"):
        cmd.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
    # WORKDIR (/home/neuro, baked in and owned by uid 1000) is unwritable
    # under the host uid above; Octave code that writes to the current
    # directory (e.g. unpack.m during smoothing) needs a writable cwd. /tmp
    # is bind-mounted from a host-owned dir below, so point the container at
    # that instead of the image's default WORKDIR.
    cmd.extend(["-w", "/tmp"])
    cmd.extend([
        "-v", f"{config.BIDS_DIR}:/raw",
        "-v", f"{config.BIDS_DIR}:{config.BIDS_DIR}",
        "-v", f"{config.DERIVATIVES_DIR}:/derivatives",
        "-v", f"{config.FMRIPREP_DIR}:/fmriprep"
    ])

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

    # Persist other writable dirs the image needs (error logs, SPM
    # caches) outside the ephemeral --rm container, matching what Apptainer
    # already does. chmod 0o777 since --user above runs as the host uid,
    # which won't otherwise have write access to a dir it didn't create.
    for dir_name, container_path in [
        ("error_logs", "/home/neuro/bidspm/error_logs"),
        ("spm", "/home/neuro/spm"),
        ("matlab_cache", "/home/neuro/.matlab"),
    ]:
        local_dir = config.WD / dir_name
        local_dir.mkdir(exist_ok=True)
        local_dir.chmod(0o777)
        cmd.extend(["-v", f"{local_dir}:{container_path}"])

    # Environment variables
    cmd.extend([
        "-e", "HOME=/tmp",
        "-e", "TMPDIR=/tmp",
        "-e", "TMP=/tmp",
        "-e", "SPM_HTML_BROWSER=0",
        "-e", "BIDSPM_IGNORE_FIELDMAPS=1",
        "-e", "BIDSPM_IGNORE_FIGURES=1",
        "-e", "BIDSPM_SKIP_INTENDEDFOR_CHECK=1",
        *[x for k, v in (extra_env or {}).items() for x in ("-e", f"{k}={v}")],
    ])

    if override_entrypoint is not None:
        # The image bakes in ENTRYPOINT ["bidspm"]; just appending a
        # replacement command as trailing args (as we do for `args` below)
        # would pass it as arguments *to* bidspm instead of replacing it.
        # -- unlike Apptainer, where `apptainer exec <image> <cmd>` always
        # takes an explicit command with nothing baked in to override.
        cmd.extend(["--entrypoint", override_entrypoint[0]])
        cmd.append(container_config.docker_image)
        cmd.extend(override_entrypoint[1:])
    else:
        cmd.append(container_config.docker_image)
        cmd.extend(args)
    return cmd, model_container_path


def build_apptainer_command(
    container_config: ContainerConfig,
    config: Config,
    args: List[str],
    model_file_path: Optional[Path],
    override_entrypoint: Optional[List[str]] = None,
    extra_env: Optional[Dict[str, str]] = None,
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

    for dir_name, container_path in [
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
        "--env", "MATLABPATH=/home/neuro/bidspm:/home/neuro/bidspm/lib/CPP_ROI:/home/neuro/bidspm/lib/CPP_ROI/atlas:/home/neuro/bidspm/lib/CPP_ROI/src:/home/neuro/bidspm/lib/CPP_ROI/src/atlas:/opt/spm",
        "--env", "BIDSPM_IGNORE_FIELDMAPS=1",
        "--env", "BIDSPM_IGNORE_FIGURES=1",
        "--env", "BIDSPM_SKIP_INTENDEDFOR_CHECK=1",
        *[x for k, v in (extra_env or {}).items() for x in ("--env", f"{k}={v}")],
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
export MATLABPATH="/home/neuro/bidspm:/home/neuro/bidspm/lib/CPP_ROI:/home/neuro/bidspm/lib/CPP_ROI/atlas:/home/neuro/bidspm/lib/CPP_ROI/src:/home/neuro/bidspm/lib/CPP_ROI/src/atlas:/opt/spm:$MATLABPATH"
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
    override_entrypoint: Optional[List[str]] = None,
    extra_env: Optional[Dict[str, str]] = None,
) -> Tuple[List[str], Optional[str]]:
    """Build container command based on type (dispatches to specific builder)."""
    if container_config.container_type == "docker":
        return build_docker_command(container_config, config, args, model_file_path, override_entrypoint, extra_env)
    elif container_config.container_type == "apptainer":
        return build_apptainer_command(container_config, config, args, model_file_path, override_entrypoint, extra_env)
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


def check_models_dir_node_collision(models_dir: Path) -> List[str]:
    """Return error strings for any root-node Name collisions in models_dir.

    BMS requires all competing models to share task/space/FWHM, so two models
    with the same root-node Name produce the same output folder path and
    silently overwrite each other's SPM.mat/betas/contrasts.
    """
    errors: List[str] = []
    seen: Dict[str, str] = {}  # normalized_label -> first filename that used it

    for model_file in sorted(models_dir.glob("*_smdl.json")):
        try:
            with open(model_file, encoding="utf-8") as f:
                content = json.load(f)
        except Exception:
            continue

        node_name = _get_run_node_name(content)
        if node_name is None:
            continue

        normalized = _normalize_node_label(node_name)

        if normalized in _FFX_UNNAMED_NODE_LABELS:
            errors.append(
                f"{model_file.name}: root-node Name '{node_name}' maps to an "
                "unsuffixed output folder (bidspm omits _node- for 'run'/'runlevel' "
                "names) — rename it to a unique non-run/runlevel value to avoid "
                "silent overwrites"
            )
        elif normalized in seen:
            errors.append(
                f"{model_file.name} and {seen[normalized]}: both have root-node "
                f"Name '{node_name}' (normalized: '{normalized}') — they will write "
                "to the same output folder and overwrite each other's results"
            )
        else:
            seen[normalized] = model_file.name

    return errors


def materialize_bms_models(model_paths: List[Path]) -> Path:
    """Copy model files into a fresh temp dir with _smdl.json suffixes.

    bidspm globs '*_smdl.json' inside --models_dir; files without that suffix
    are silently ignored. This helper lets callers pass arbitrary model file
    paths and always gets the suffix right.
    Returns the new temp dir path (caller is responsible for cleanup).
    """
    import tempfile as _tempfile
    dest = Path(_tempfile.mkdtemp(prefix="bidspm_bms_"))
    for src in model_paths:
        stem = src.stem
        dest_name = src.name if stem.endswith("_smdl") else f"{stem}_smdl.json"
        shutil.copy2(src, dest / dest_name)
    return dest


def run_bms(
    config_file: str,
    container_config_file: Optional[str],
    models_dir: Optional[str] = None,
    fwhm: Optional[float] = None,
    participant_label: Optional[List[str]] = None,
    dry_run: bool = False,
    skip_validation: bool = False,
    on_progress: Optional[Callable[[str], None]] = None,
    bms_action: str = "bms",
    model_files: Optional[List[str]] = None,
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

    Provide either ``models_dir`` (a pre-built directory of ``*_smdl.json``
    files) or ``model_files`` (arbitrary model paths; a temp dir is
    materialized automatically and cleaned up after the run).
    """
    def _log(msg: str):
        if on_progress:
            on_progress(msg)
        else:
            print(msg)

    errors: List[str] = []

    _materialized_dir: Optional[Path] = None
    try:
        if model_files:
            _materialized_dir = materialize_bms_models(
                [Path(f).expanduser().resolve() for f in model_files]
            )
            resolved_models_dir = _materialized_dir
        elif models_dir:
            try:
                resolved_models_dir = resolve_models_dir(models_dir)
            except ValueError as e:
                errors.append(str(e))
                return {"success": False, "errors": errors, "dry_run_commands": []}
        else:
            errors.append(
                "Either --models-dir or --models must be provided for BMS."
            )
            return {"success": False, "errors": errors, "dry_run_commands": []}

        collision_errors = check_models_dir_node_collision(resolved_models_dir)
        if collision_errors:
            errors.extend(collision_errors)
            return {"success": False, "errors": errors, "dry_run_commands": []}

        container_file = container_config_file
        if not container_file:
            from .config import auto_select_container_config
            container_file = auto_select_container_config()

        if not container_file or not Path(container_file).exists():
            errors.append("No container configuration found (BMS requires container execution).")
            return {"success": False, "errors": errors, "dry_run_commands": []}

        config = load_config(config_file)

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

    finally:
        if _materialized_dir and _materialized_dir.exists():
            shutil.rmtree(_materialized_dir, ignore_errors=True)


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
    """Tasks in the file names of sub-*/[ses-*/]func (derivatives and sourcedata are not looked at)."""
    from .model_wizard import bids_tasks  # lists only the func folders instead of walking the whole tree
    return bids_tasks(bids_dir)


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

@lru_cache(maxsize=1)
def _fetch_bids_stats_schema() -> Dict[str, Any]:
    import requests
    return requests.get(
        "https://bids-standard.github.io/stats-models/BIDSStatsModel.json",
        timeout=10,
    ).json()


def validate_bids_model(model_path: Path, skip_cache: bool = False) -> Dict[str, Any]:
    """
    Validate BIDS stats model against schema.
    Returns dict with 'valid' bool, optional 'error' or 'warning'.
    """
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
    warnings.extend(_check_dataset_node_name(model_content))

    # Schema validation
    try:
        import requests
        from jsonschema import validate, ValidationError

        if skip_cache:
            _fetch_bids_stats_schema.cache_clear()
        try:
            schema = _fetch_bids_stats_schema()
        except (requests.RequestException, ValueError):
            warnings.append("Could not fetch the BIDS stats-model schema (offline?); schema validation skipped")
            return {"valid": True, "warning": "; ".join(warnings)}
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


def _check_dataset_node_name(model: Dict) -> List[str]:
    """Warn when a Dataset-level node is not named 'dataset'.

    bidspm's report code (boilerplate.m) looks the node up by Name == 'dataset';
    any other name makes it log "Could not find a corresponding Node".
    """
    nodes = model.get('Nodes', model.get('Steps', []))
    return [
        f"Node '{node.get('Name')}': Dataset-level nodes must be named 'dataset' "
        "(bidspm looks the node up by name)"
        for node in nodes
        if isinstance(node, dict) and str(node.get('Level', '')).strip() == 'Dataset'
        and str(node.get('Name', '')).strip() != 'dataset'
    ]


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

_MAX_BLAS_THREADS = 8


_BIDSPM_FAILURE_MARKERS = ("ERROR LOG SAVED:",)  # printed when bidspm caught an error (exit code stays 0)


def _blas_thread_env(workers: int, cpus: Optional[int]) -> Dict[str, str]:
    """Per-container BLAS/OpenMP thread limits so parallel workers don't oversubscribe the CPUs.

    Octave starts one busy-waiting thread per core by default; with several workers they thrash
    each other (3 parallel subjects on 32 cores: 394 s unrestricted vs 115 s at 1 thread each).
    """
    n = str(max(1, min(_MAX_BLAS_THREADS, (cpus or 1) // max(1, workers))))
    return {"OPENBLAS_NUM_THREADS": n, "OMP_NUM_THREADS": n, "MKL_NUM_THREADS": n}


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
    name_by_confounds: bool = False
    estimation_engine: str = "octave"  # 'standalone': estimate in SPM's compiled standalone (opt-in)
    run_results: bool = False  # SPM Results export is opt-in (slow); always on for 'report'

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
        self._workers = 1  # active stats workers, set in run(); sizes the BLAS threads
        self._validation_lock = threading.Lock()
        self._validated = False
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

            if not self._check_standalone_image():
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

            from .preflight import resolve_tasks  # same fallback as the readiness check
            tasks = resolve_tasks(
                self.config.TASKS, self.model_file_path or self.options.model_file or self.config.MODELS_FILE,
                self.config.BIDS_DIR)
            if not self.config.TASKS:
                self._log(f">>> No TASKS in the config, using: {', '.join(tasks) or 'none'}")
            for task in tasks:
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
                self._workers = max_workers

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
                    self._log(f">>> Dataset stats: task {task}")
                    self._run_container_dataset_action(task)
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
            if not self._run_container_action("smooth", subject, task):
                success = False

        if 'stats' in self.options.actions:
            self._log(f">>> Stats: subject {subject}, task {task}")
            self._copy_brain_mask(subject, task)
            started = time.time() - 1
            if self.options.estimation_engine == "standalone":
                ok = self._run_stats_standalone(subject, task)
            else:
                ok = self._run_container_action("stats", subject, task)
            # bidspm's launcher is try/catch + exit, so a failed run still exits 0: check for output.
            if ok and not self.options.dry_run \
                    and not find_new_spm_mats(self.config, subject, task, since=started):
                self._log_error(f"Stats for subject {subject}, task {task}: the container exited 0 but "
                                f"wrote no SPM.mat; see the container log above")
                ok = False
            if not ok:
                success = False

        return success

    def _check_standalone_image(self) -> bool:
        """Preflight for estimation_engine='standalone': the user-supplied image must exist (no pull, no fallback)."""
        if self.options.estimation_engine != "standalone":
            return True
        ok, msg = check_spm_image(self.container_config)
        if not ok:
            self._log_error(msg)
        else:
            self._log(f"SPM standalone image: {msg}")
        return ok

    def _run_stats_standalone(self, subject: str, task: str) -> bool:
        """design (Octave bidspm) -> fmri_est (SPM standalone) -> contrasts (Octave bidspm).

        All three see the same /derivatives layout, so the absolute paths inside SPM.mat stay valid.
        """
        started = time.time() - 1
        if not self._run_container_action("stats", subject, task, extra_args=["--design_only"]):
            return False

        job_dir = self.config.WD / "tmp" / f"spm_est_{subject}_{random.randint(1000, 9999)}"
        if self.options.dry_run:
            job_dir_cmd = build_spm_standalone_command(self.container_config, self.config, job_dir)
            self.dry_run_commands.append(' '.join(job_dir_cmd))
            self._log(f"[DRY RUN] Would estimate in SPM standalone: {' '.join(job_dir_cmd[:5])}...")
        else:
            mats = find_new_spm_mats(self.config, subject, task, since=started)
            if not mats:
                self._log_error(f"Design step wrote no SPM.mat for subject {subject}, task {task}")
                return False
            container_paths = [f"/derivatives/{m.relative_to(self.config.DERIVATIVES_DIR)}" for m in mats]
            write_estimation_job(container_paths, job_dir)
            self._log(f">>> Estimating in SPM standalone: subject {subject}, task {task}")
            if not run_command(build_spm_standalone_command(self.container_config, self.config, job_dir)):
                return False
            if not all(is_estimated(m) for m in mats):
                self._log_error(f"SPM standalone exited 0 but wrote no beta images for subject {subject}, "
                                f"task {task}; not running contrasts")
                return False

        return self._run_container_action("stats", subject, task, cli_action="contrasts")

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

    def _validation_args(self) -> List[str]:
        """Only the first container of a run validates the BIDS dataset (it walks the whole
        dataset, once per container otherwise); later ones skip it."""
        with self._validation_lock:
            first, self._validated = not self._validated, True
        return [] if first else ["--skip_validation"]

    def _container_env(self) -> Dict[str, str]:
        """Extra env for every container: BLAS thread limits, and skipping the (slow) SPM Results
        export unless requested. The report action reads results/*.csv|png, so it keeps them."""
        env = _blas_thread_env(self._workers, os.cpu_count())
        if not (self.options.run_results or 'report' in self.options.actions):
            env["BIDSPM_SKIP_RESULTS"] = "1"
        return env

    def _run_container_action(self, action: str, subject: str, task: str, *,
                              cli_action: Optional[str] = None,
                              extra_args: Sequence[str] = ()) -> bool:
        """Run action via container. ``cli_action`` swaps the bidspm CLI action word (stats -> contrasts)."""
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
                "/raw", "/derivatives", "subject", cli_action or "stats",
                "--preproc_dir", "/derivatives/bidspm-preproc",
                "--participant_label", subject,
                "--task", task,
                "--space", self.config.SPACE,
                "--fwhm", str(self.config.FWHM),
                "--verbosity", str(self.config.VERBOSITY)
            ]
            args += list(extra_args)
            if self.options.node_name:
                args.extend(["--node_name", self.options.node_name])
            if self.options.name_by_confounds:
                args.append("--name_by_confounds")
            model_path = _model_container_path(self.model_file_path, self.config.DERIVATIVES_DIR)
            if model_path:
                args += ["--model_file", model_path]
        else:
            return False

        cmd, _ = build_container_command(
            self.container_config, self.config, args + self._validation_args(), self.model_file_path,
            extra_env=self._container_env(),
        )

        if self.options.dry_run:
            self.dry_run_commands.append(' '.join(cmd))
            self._log(f"[DRY RUN] Would execute: {' '.join(cmd[:5])}...")
            return True

        return run_command(cmd, failure_markers=_BIDSPM_FAILURE_MARKERS)
    
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
        if self.options.name_by_confounds:
            args.append("--name_by_confounds")
        model_path = _model_container_path(self.model_file_path, self.config.DERIVATIVES_DIR)
        if model_path:
            args += ["--model_file", model_path]

        cmd, _ = build_container_command(
            self.container_config, self.config, args + self._validation_args(), self.model_file_path,
            extra_env=self._container_env(),
        )

        if self.options.dry_run:
            self.dry_run_commands.append(' '.join(cmd))
            self._log(f"[DRY RUN] Would execute dataset stats")
            return True

        return run_command(cmd, failure_markers=_BIDSPM_FAILURE_MARKERS)

