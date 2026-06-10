#!/usr/bin/env python3
"""Utility functions for BIDSPM Runner"""

import os
import random
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from .config import Config
from .logging_utils import log_debug, log_error_non_fatal, log


_BIDSPM_ERROR_PATTERN = "bidspm - ERROR"

def run_command(cmd_list, capture_output=False):
    """Execute a command and return success status."""
    log_debug(f"Running command: {' '.join(cmd_list)}")

    bidspm_error_seen = False

    try:
        # Stream output line-by-line so the user sees live progress and we can
        # detect bidspm-level errors that don't set a non-zero exit code.
        proc = subprocess.Popen(
            cmd_list,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        output_lines = []
        for line in proc.stdout:
            line_stripped = line.rstrip()
            print(line_stripped, flush=True)
            output_lines.append(line_stripped)
            if _BIDSPM_ERROR_PATTERN in line_stripped:
                bidspm_error_seen = True
        proc.wait()

        if capture_output:
            log('\n'.join(output_lines))

        if proc.returncode != 0:
            log_error_non_fatal(f"Command failed with exit code {proc.returncode}: {' '.join(cmd_list)}")
            return False

        if bidspm_error_seen:
            log_error_non_fatal(f"bidspm reported an ERROR during execution (exit code was 0): {' '.join(cmd_list[:3])}")
            return False

        return True

    except Exception as e:
        log_error_non_fatal(f"Command failed: {e}: {' '.join(cmd_list)}")
        return False


def get_container_model_path(model_file_path: Path, derivatives_dir: Path) -> str:
    """Get the correct model file path within the container"""
    try:
        # If model file is inside derivatives directory, use relative path
        relative_path = model_file_path.relative_to(derivatives_dir)
        return f"/derivatives/{relative_path}"
    except ValueError:
        # Model file is outside derivatives, use mounted path
        return "/models/smdl.json"


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
