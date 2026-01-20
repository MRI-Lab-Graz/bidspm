#!/usr/bin/env python3
"""Logging utilities for BIDSPM Runner"""

import sys
from datetime import datetime
from pathlib import Path

# Module-level variables
LOG_DIR = Path("logs")
LOG_FILE = str(LOG_DIR / "run_bidspm.log")
DEBUG = True  # Set to False to suppress debug output


def set_log_file(log_file: str):
    """Set the global log file path."""
    global LOG_FILE
    LOG_FILE = log_file


def generate_log_filename(model_file_path: str) -> str:
    """Generate log filename based on model name and timestamp"""
    model_name = Path(model_file_path).stem  # Get filename without extension
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return str(LOG_DIR / f"{model_name}_{timestamp}.log")


def log_debug(msg):
    """Log debug message if DEBUG is enabled."""
    if DEBUG:
        log(f"[DEBUG] {msg}")


def log_error(msg):
    """Log error message and exit."""
    log(f"[ERROR] {msg}", error=True)
    sys.exit(1)


def log_error_non_fatal(msg):
    """Log non-fatal error that doesn't stop execution"""
    print(f"⚠️  {msg}", file=sys.stderr)


def log(msg, error=False):
    """Write log message to both file and stdout/stderr."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_msg = f"{timestamp} {msg}"
    log_path = Path(LOG_FILE)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        f.write(full_msg + "\n")
    print(full_msg, file=sys.stderr if error else sys.stdout)
