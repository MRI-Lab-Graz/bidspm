"""Utility functions for logging, validation, and file operations."""

import sys
import json
import shutil
import subprocess
import re
import time
import queue
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional, Sequence

LOG_DIR = Path("logs")
LOG_FILE = str(LOG_DIR / "run_bidspm.log")
DEBUG = False


@dataclass
class StreamCommandResult:
    """Result of a streaming subprocess execution."""
    success: bool
    returncode: int
    output: str
    timed_out: bool = False


def log_debug(msg):
    if DEBUG:
        log(f"[DEBUG] {msg}")


def log_error(msg):
    log(f"[ERROR] {msg}", error=True)
    sys.exit(1)


def log(msg, error=False):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_msg = f"{timestamp} {msg}"
    log_path = Path(LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(full_msg + "\n")
    print(full_msg, file=sys.stderr if error else sys.stdout)


def log_error_non_fatal(msg):
    """Log non-fatal error that doesn't stop execution"""
    print(f"⚠️  {msg}", file=sys.stderr)


def run_streaming_command(
    cmd_list: Sequence[str],
    *,
    capture_output: bool = False,
    on_output: Optional[Callable[[str], None]] = None,
    on_idle: Optional[Callable[[float], None]] = None,
    idle_timeout_seconds: float = 20.0,
    timeout: Optional[float] = None,
    env: Optional[dict] = None,
) -> StreamCommandResult:
    """Run a command while streaming stdout/stderr and reporting idle periods."""
    log_debug(f"Running command: {' '.join(cmd_list)}")

    process = subprocess.Popen(
        list(cmd_list),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )

    output_queue: queue.Queue[Optional[str]] = queue.Queue()
    output_tail = deque(maxlen=200)
    captured_lines = [] if capture_output else None

    def _reader() -> None:
        try:
            assert process.stdout is not None
            for line in iter(process.stdout.readline, ''):
                output_queue.put(line)
        finally:
            if process.stdout is not None:
                process.stdout.close()
            output_queue.put(None)

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    start_time = time.monotonic()
    last_output_at = start_time
    last_idle_notice_at = start_time
    timed_out = False

    while True:
        now = time.monotonic()
        if timeout is not None and process.poll() is None and (now - start_time) >= timeout:
            timed_out = True
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            break

        try:
            line = output_queue.get(timeout=1)
        except queue.Empty:
            now = time.monotonic()
            if process.poll() is not None and output_queue.empty():
                break
            if (
                on_idle is not None
                and idle_timeout_seconds > 0
                and (now - last_output_at) >= idle_timeout_seconds
                and (now - last_idle_notice_at) >= idle_timeout_seconds
            ):
                on_idle(now - last_output_at)
                last_idle_notice_at = now
            continue

        if line is None:
            if process.poll() is not None:
                break
            continue

        clean_line = line.rstrip('\n')
        output_tail.append(clean_line)
        if captured_lines is not None:
            captured_lines.append(clean_line)

        if on_output is not None:
            on_output(clean_line)
        else:
            print(line, end='')

        last_output_at = time.monotonic()
        last_idle_notice_at = last_output_at

    returncode = process.wait() if process.poll() is None else process.returncode
    output = '\n'.join(captured_lines if captured_lines is not None else output_tail)
    return StreamCommandResult(
        success=(returncode == 0 and not timed_out),
        returncode=returncode,
        output=output,
        timed_out=timed_out,
    )


def generate_log_filename(model_file_path: str) -> str:
    """Generate log filename based on model name and timestamp"""
    model_name = Path(model_file_path).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return str(LOG_DIR / f"{model_name}_{timestamp}.log")


def check_command(cmd):
    if not shutil.which(cmd):
        log_error(f"'{cmd}' is required but not installed or in PATH.")


def check_docker_availability():
    """Check if Docker is installed and running."""
    if not shutil.which("docker"):
        log_error("Docker is required but not installed or in PATH.")
    
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
    result = run_streaming_command(cmd_list, capture_output=capture_output)

    if result.success:
        if capture_output and result.output:
            log(result.output)
        return True

    if result.timed_out:
        log_error_non_fatal(f"Command timed out: {' '.join(cmd_list)}")
    else:
        log_error_non_fatal(f"Command failed with exit code {result.returncode}: {' '.join(cmd_list)}")

    if result.output:
        if capture_output:
            print(f"Command output:\n{result.output}")
        log(f"Command failed output:\n{result.output}")
    return False


def validate_space_availability(config, subjects_to_process: list, task: str) -> bool:
    """Validate that the specified SPACE exists in fMRIPrep derivatives"""
    log_debug(f"Validating SPACE '{config.SPACE}' for task '{task}'")
    
    found_subjects = []
    missing_subjects = []
    available_spaces = set()
    
    for subject_label in subjects_to_process:
        subject_dir = config.FMRIPREP_DIR / f"sub-{subject_label}"
        if not subject_dir.is_dir():
            missing_subjects.append(subject_label)
            continue
            
        pattern = f"sub-{subject_label}_*task-{task}_*space-*_desc-preproc_bold.nii.gz"
        bold_files = list(subject_dir.rglob(pattern))
        
        subject_spaces = set()
        space_found = False
        
        for bold_file in bold_files:
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
                log_debug(f"Subject {subject_label}: SPACE '{config.SPACE}' NOT found. Available: {sorted(subject_spaces)}")
            else:
                log_debug(f"Subject {subject_label}: No BOLD files found for task '{task}'")
    
    if missing_subjects:
        if len(subjects_to_process) == 1:
            # Single subject - clearer message
            subject = subjects_to_process[0]
            print(f"⚠️  Skipping subject {subject}: no data for task '{task}' in SPACE '{config.SPACE}'")
            if available_spaces:
                log_debug(f"Subject {subject}: Available spaces: {sorted(available_spaces)}")
            else:
                log_debug(f"Subject {subject}: No BOLD files found for task '{task}'")
        else:
            # Multiple subjects
            print("❌ SPACE validation failed!")
            print(f"   Specified SPACE: '{config.SPACE}'")
            print(f"   Task: '{task}'")
            print(f"   Subjects missing SPACE '{config.SPACE}': {missing_subjects}")
            if available_spaces:
                print(f"   Available spaces found: {sorted(available_spaces)}")
                print("   💡 Suggestion: Update SPACE in config to one of the available spaces")
            else:
                print(f"   ⚠️  No BOLD files found for task '{task}' in any subject")
        return False
    
    if len(subjects_to_process) > 1:
        print(f"✅ SPACE validation passed: '{config.SPACE}' found for all {len(found_subjects)} subjects")
    else:
        log_debug(f"SPACE validation passed: '{config.SPACE}' found for subject {found_subjects[0]}")
    return True


def validate_events_availability(config, subjects_to_process: list, task: str) -> bool:
    """Validate that events.tsv files exist for the given task.

    bidspm's own MATLAB code (getEventsData.m / setBatchSubjectLevelGLMSpec.m)
    only logs a WARNING and proceeds with an empty onset file when no
    events.tsv is found -- it does NOT block the stats action. That means a
    subject-level GLM can "succeed" with all task regressors silently
    missing. This check blocks stats explicitly instead of relying on that
    warn-and-continue behavior.
    """
    missing_subjects = []

    for subject_label in subjects_to_process:
        pattern = f"sub-{subject_label}_*task-{task}_*events.tsv"
        events_files = list(config.BIDS_DIR.rglob(pattern))
        if not events_files:
            missing_subjects.append(subject_label)

    if missing_subjects:
        if len(subjects_to_process) == 1:
            print(f"❌ Blocking stats for subject {subjects_to_process[0]}: "
                  f"no events.tsv found for task '{task}' in {config.BIDS_DIR}")
        else:
            print("❌ events.tsv validation failed!")
            print(f"   Task: '{task}'")
            print(f"   Subjects missing events.tsv: {missing_subjects}")
        return False

    return True


def ensure_derivatives_dataset_description(derivatives_dir: Path):
    """Create a minimal dataset_description.json in derivatives directory."""
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


def cleanup_tmp_directories(config, max_age_hours: int = 24):
    """Clean up old temporary directories to prevent disk space issues."""
    try:
        import time
        tmp_parent = config.WD / "tmp"
        if not tmp_parent.exists():
            return
        
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        for tmp_dir in tmp_parent.iterdir():
            if tmp_dir.is_dir():
                dir_age = current_time - tmp_dir.stat().st_mtime
                if dir_age > max_age_seconds:
                    try:
                        shutil.rmtree(tmp_dir)
                        log_debug(f"Cleaned up old tmp directory: {tmp_dir}")
                    except Exception as e:
                        log_debug(f"Could not clean up {tmp_dir}: {e}")
    except Exception as e:
        log_debug(f"Error during tmp cleanup: {e}")


def get_container_model_path(model_file_path: Path, derivatives_dir: Path) -> str:
    """Get the correct model file path within the container"""
    try:
        relative_path = model_file_path.relative_to(derivatives_dir)
        return f"/derivatives/{relative_path}"
    except ValueError:
        return "/models/smdl.json"
