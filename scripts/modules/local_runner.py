#!/usr/bin/env python3
"""Local BIDSPM execution functions"""

import os
import subprocess
import threading
from pathlib import Path
from typing import List, Tuple

from .config import Config
from .environment import check_local_bidspm_installation, get_local_bidspm_cli_command
from .logging_utils import log_debug, log_error, log_error_non_fatal

# Module-level constant
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _run_streaming(
    cmd: list,
    timeout_seconds: int,
    env: dict,
    cwd: Path,
) -> Tuple[int, str, str]:
    """Run a subprocess, printing stdout/stderr lines as they arrive.

    Returns (returncode, full_stdout, full_stderr).
    Raises subprocess.TimeoutExpired (process already killed) on timeout.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        env=env,
    )

    stdout_lines: List[str] = []
    stderr_lines: List[str] = []

    def _reader(pipe, lines, tag: str) -> None:
        for raw in iter(pipe.readline, ""):
            line = raw.rstrip("\n")
            # Filter out pure backspace/CR noise from SPM progress bars
            if line and not all(c in "\x08\r" for c in line):
                print(f"   [{tag}] {line}", flush=True)
            lines.append(raw)
        pipe.close()

    t_out = threading.Thread(target=_reader, args=(proc.stdout, stdout_lines, "OUT"), daemon=True)
    t_err = threading.Thread(target=_reader, args=(proc.stderr, stderr_lines, "ERR"), daemon=True)
    t_out.start()
    t_err.start()

    try:
        proc.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        proc.kill()
        t_out.join(timeout=3)
        t_err.join(timeout=3)
        exc = subprocess.TimeoutExpired(cmd, timeout_seconds)
        exc.stdout = "".join(stdout_lines)
        exc.stderr = "".join(stderr_lines)
        raise exc

    t_out.join(timeout=5)
    t_err.join(timeout=5)
    return proc.returncode, "".join(stdout_lines), "".join(stderr_lines)


def run_local_bidspm(config: Config, action: str, subjects: List[str], task: str, model_file_path: Path):
    """Execute BIDSPM locally using the Python CLI"""
    print(f"🔧 Running BIDSPM locally for action: {action}")
    
    # Check if local installation is available
    if not check_local_bidspm_installation():
        log_error("Local BIDSPM installation not found. Use containers or run: ./setup.sh --local-install")
        return False
    
    # Use Python CLI approach (much faster and more reliable)
    return run_local_bidspm_cli(config, action, subjects, task, model_file_path)


def run_local_bidspm_cli(config: Config, action: str, subjects: List[str], task: str, model_file_path: Path):
    """Execute BIDSPM using the Python CLI (fast and reliable)"""
    print(f"🔧 Running BIDSPM Python CLI for action: {action}")

    repo_root = REPO_ROOT
    bidspm_root = repo_root / "local_src" / "bidspm_local"
    bidspm_src = bidspm_root / "src"
    bidspm_lib = bidspm_root / "lib"
    spm_root = repo_root / "external" / "spm12_standalone"
    octave_dir = repo_root / "octave"
    octave_startup = octave_dir / "octave_startup.m"
    octave_minimal = octave_dir / "octave_minimal.m"

    search_paths = [bidspm_root, bidspm_src, bidspm_lib, spm_root]

    def prepend_env_path(env_dict, key, paths):
        existing = env_dict.get(key, "")
        entries = [str(p) for p in paths if p and Path(p).exists()]
        if existing:
            entries.append(existing)
        # Remove duplicates while preserving order
        seen = set()
        cleaned = []
        for entry in entries:
            if entry and entry not in seen:
                cleaned.append(entry)
                seen.add(entry)
        env_dict[key] = os.pathsep.join(cleaned)

    success = True
    cli_base_cmd = get_local_bidspm_cli_command(repo_root)
    _timeout_map = {
        "smooth": int(getattr(config, "SMOOTH_TIMEOUT_SECONDS", 900) or 900),
        "stats": int(getattr(config, "STATS_TIMEOUT_SECONDS", 1800) or 1800),
        "dataset": int(getattr(config, "DATASET_TIMEOUT_SECONDS", 300) or 300),
    }

    for subject in subjects:
        timeout_seconds = max(1, _timeout_map.get(action, int(getattr(config, "LOCAL_ACTION_TIMEOUT_SECONDS", 900) or 900)))
        print(f">>> {action.title()} for subject: {subject}, task: {task}")

        try:
            cmd = [
                *cli_base_cmd,
                str(config.BIDS_DIR),
                str(config.DERIVATIVES_DIR),
                "subject",
                action,
            ]

            cmd.extend([
                "--participant_label", subject,
                "--task", task,
                "--space", config.SPACE,
                "--verbosity", str(config.VERBOSITY),
            ])

            if action == "smooth":
                cmd.extend(["--fwhm", str(config.FWHM)])
            elif action in ["stats", "contrasts", "results"]:
                preproc_dir = config.DERIVATIVES_DIR / "bidspm-preproc"
                cmd.extend([
                    "--model_file", str(model_file_path),
                    "--preproc_dir", str(preproc_dir),
                ])

            log_debug(f"Local BIDSPM CLI command: {' '.join(cmd)}")

            env = os.environ.copy()
            env["BIDSPM_PROJECT_ROOT"] = str(repo_root)
            env["BIDSPM_PATH"] = str(bidspm_root)
            env["SPM12_PATH"] = str(spm_root)
            env["SPM_HOME"] = str(spm_root)
            env["SPM_STANDALONE_HOME"] = str(spm_root)

            prepend_env_path(env, "MATLABPATH", search_paths)
            prepend_env_path(env, "OCTAVE_PATH", search_paths)

            if octave_startup.exists():
                env["OCTAVE_SITE_INITFILE"] = str(octave_startup)
            elif octave_minimal.exists():
                env["OCTAVE_SITE_INITFILE"] = str(octave_minimal)

            log_debug(f"Timeout: {timeout_seconds}s | Command: {' '.join(cmd)}")
            returncode, out, err = _run_streaming(cmd, timeout_seconds, env, repo_root)

            if returncode == 0:
                print(f"✅ {action.title()} completed successfully for subject {subject}")
            else:
                print(f"❌ {action.title()} failed for subject {subject} (exit {returncode})")
                success = False

        except subprocess.TimeoutExpired as exc:
            print(f"⚠️  {action.title()} timed out for subject {subject} after {timeout_seconds} seconds")
            success = False
        except Exception as e:
            print(f"⚠️  {action.title()} failed for subject {subject}: {e}")
            success = False

    return success


def run_local_bidspm_direct(config: Config, action: str, subjects: List[str], task: str, model_file_path: Path):
    """Execute BIDSPM directly using MATLAB/Octave (for backward compatibility)"""
    import shutil
    
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
        return False
    
    success = True
    local_bidspm_dir = Path("local_src/bidspm_local")
    _timeout_map = {
        "smooth": int(getattr(config, "SMOOTH_TIMEOUT_SECONDS", 900) or 900),
        "stats": int(getattr(config, "STATS_TIMEOUT_SECONDS", 1800) or 1800),
        "dataset": int(getattr(config, "DATASET_TIMEOUT_SECONDS", 300) or 300),
    }
    timeout_seconds = max(1, _timeout_map.get(action, int(getattr(config, "LOCAL_ACTION_TIMEOUT_SECONDS", 900) or 900)))
    
    for subject in subjects:
        try:
            print(f">>> Local {action} for subject: {subject}, task: {task}")
            
            # Create MATLAB/Octave script based on action
            script_content = _generate_matlab_script(action, config, subject, task, model_file_path, local_bidspm_dir)
            
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
                                      capture_output=True, timeout=timeout_seconds)
                
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
            log_error_non_fatal(f"Local {action} timed out for subject {subject} after {timeout_seconds} seconds")
            success = False
        except Exception as e:
            log_error_non_fatal(f"Error running local {action} for subject {subject}: {e}")
            success = False
    
    return success


def _generate_matlab_script(action: str, config: Config, subject: str, task: str, 
                            model_file_path: Path, local_bidspm_dir: Path) -> str:
    """Generate MATLAB/Octave script for the specified action"""
    
    base_script = f"""
% BIDSPM Local Execution Script - MINIMAL MODE
% HPC-compatible setup with SPM12 and BIDSPM paths

% Configure local package installation directory
if exist('pkg', 'builtin')
    pkg('prefix', fullfile(pwd, 'octave_packages'), fullfile(pwd, 'octave_packages'));
    fprintf('Octave package directory set to local folder\\n');
end

% Set warning level to reduce verbose output
warning('off', 'all');

% Add SPM12 standalone if available
spm12_path = fullfile(pwd, 'external/spm12_standalone');
if exist(spm12_path, 'dir')
    addpath(spm12_path);
    fprintf('SPM12 standalone added to path\\n');
end

% Add BIDSPM to path manually (skip bidspm('init') to avoid package downloads)
bidspm_path = '{local_bidspm_dir.absolute()}';
addpath(bidspm_path);
addpath(fullfile(bidspm_path, 'src'));
addpath(genpath(fullfile(bidspm_path, 'lib')));
addpath(genpath(fullfile(bidspm_path, 'src')));
fprintf('BIDSPM paths added manually (offline mode)\\n');

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
"""
    
    if action == "smooth":
        script_content = base_script + f"""
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
    elif action in ["stats", "dataset"]:
        level = "subject" if action == "stats" else "dataset"
        participant_line = f"'participant_label', {{'{subject}'}}, ..." if action == "stats" else ""
        
        script_content = base_script + f"""
try
    bidspm('{config.BIDS_DIR}', ...
           '{config.DERIVATIVES_DIR}', ...
           '{level}', ...
           'action', 'stats', ...
           {participant_line}
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
    else:
        raise ValueError(f"Unsupported action: {action}")
    
    return script_content
