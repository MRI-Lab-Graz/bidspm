"""Configuration management for bidspm."""

import json
import platform
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Config:
    WD: Path
    BIDS_DIR: Path
    DERIVATIVES_DIR: Path
    SPACE: str
    FWHM: float
    MODELS_FILE: str
    TASKS: List[str]
    FMRIPREP_DIR: Path
    VERBOSITY: int
    SUBJECTS: Optional[List[str]] = None
    ROI: Optional[bool] = None
    ROI_CONFIG: Optional[dict] = None
    SKIP_VALIDATION: Optional[bool] = False
    CONTAINER_TYPE: Optional[str] = "local"
    LOCAL_ACTION_TIMEOUT_SECONDS: int = 900  # kept as generic fallback
    SMOOTH_TIMEOUT_SECONDS: int = 900
    STATS_TIMEOUT_SECONDS: int = 300
    DATASET_TIMEOUT_SECONDS: int = 300


@dataclass
class ContainerConfig:
    container_type: str  # "docker" or "apptainer"
    docker_image: str = ""
    apptainer_image: str = ""


def load_config(config_file: str) -> Config:
    """Load configuration from JSON file."""
    if not Path(config_file).exists():
        from .utils import log_error
        log_error(f"Config file '{config_file}' not found.")

    with open(config_file) as f:
        data = json.load(f)

    # SESSION support: if present, generate selection.json
    session = data.get("SESSION")
    if session:
        selection = {
            "bold": {
                "datatype": "func",
                "suffix": "bold",
                "ses": session
            }
        }
        runs = data.get("RUNS")
        if runs:
            selection["bold"]["run"] = runs
        try:
            with open("selection.json", "w") as sel_f:
                json.dump(selection, sel_f, indent=2)
            print(f"✅ selection.json generated for session {session}.")
        except Exception as e:
            print(f"⚠️  Could not write selection.json: {e}")

    # Derive paths
    wd = Path(data["WD"])
    bids_dir = Path(data["BIDS_DIR"])
    derivatives_raw = str(data.get("DERIVATIVES_DIR", "")).strip()
    derivatives_dir = Path(derivatives_raw) if derivatives_raw else wd
    fmriprep_dir = Path(data["FMRIPREP_DIR"])
    verbosity = data.get("VERBOSITY", 3)
    container_type = str(data.get("container_type", "local")).lower()
    local_action_timeout_seconds = int(data.get("LOCAL_ACTION_TIMEOUT_SECONDS", 900))
    smooth_timeout = int(data.get("SMOOTH_TIMEOUT_SECONDS", local_action_timeout_seconds))
    stats_timeout = int(data.get("STATS_TIMEOUT_SECONDS", 300))
    dataset_timeout = int(data.get("DATASET_TIMEOUT_SECONDS", 300))

    return Config(
        WD=wd,
        BIDS_DIR=bids_dir,
        DERIVATIVES_DIR=derivatives_dir,
        SPACE=data["SPACE"],
        FWHM=data["FWHM"],
        MODELS_FILE=data.get("MODELS_FILE", None),
        TASKS=data["TASKS"],
        FMRIPREP_DIR=fmriprep_dir,
        VERBOSITY=verbosity,
        SUBJECTS=data.get("SUBJECTS"),
        ROI=data.get("ROI"),
        ROI_CONFIG=data.get("ROI_CONFIG"),
        SKIP_VALIDATION=data.get("skip_validation", False),
        CONTAINER_TYPE=container_type,
        LOCAL_ACTION_TIMEOUT_SECONDS=max(1, local_action_timeout_seconds),
        SMOOTH_TIMEOUT_SECONDS=max(1, smooth_timeout),
        STATS_TIMEOUT_SECONDS=max(1, stats_timeout),
        DATASET_TIMEOUT_SECONDS=max(1, dataset_timeout),
    )


def load_container_config(config_file: str) -> ContainerConfig:
    if not Path(config_file).exists():
        from .utils import log_error
        log_error(f"Container config file '{config_file}' not found.")

    with open(config_file) as f:
        data = json.load(f)

    container_type = data.get("container_type", "docker").lower()
    if container_type not in ["docker", "apptainer"]:
        from .utils import log_error
        log_error(f"Invalid container_type '{container_type}'. Must be 'docker' or 'apptainer'.")

    return ContainerConfig(
        container_type=container_type,
        docker_image=data.get("docker_image", ""),
        apptainer_image=data.get("apptainer_image", "")
    )


def detect_platform_and_suggest_container():
    """Detect platform and suggest appropriate container configuration."""
    system = platform.system().lower()
    
    if system == "darwin":
        return "docker", "Docker recommended for macOS (Apptainer not supported)."
    elif system == "linux":
        docker_available = False
        apptainer_available = False
        
        try:
            subprocess.run(["docker", "--version"], capture_output=True, check=True)
            docker_available = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
            
        try:
            subprocess.run(["apptainer", "--version"], capture_output=True, check=True)
            apptainer_available = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass
        
        if apptainer_available and not docker_available:
            return "apptainer", "HPC environment detected - using Apptainer (Docker not available)."
        elif docker_available and not apptainer_available:
            return "docker", "Docker detected on Linux."
        elif docker_available and apptainer_available:
            return "apptainer", "Both Docker and Apptainer available - using Apptainer for reproducibility."
        else:
            return None, "Neither Docker nor Apptainer found on Linux system."
    else:
        return "docker", f"Unknown platform ({system}), Docker recommended."


def auto_select_container_config():
    """Automatically select container configuration based on platform."""
    detected_type, message = detect_platform_and_suggest_container()
    
    print(f"🔍 Platform detection: {message}")
    
    config_candidates = []
    
    if detected_type == "docker":
        config_candidates = ["containers/container.json", "containers/container_docker.json", "containers/container_dev.json"]
    elif detected_type == "apptainer":
        config_candidates = ["containers/container_production.json", "containers/container_apptainer.json", "containers/container.json"]
    
    for candidate in config_candidates:
        if Path(candidate).exists():
            try:
                with open(candidate, 'r') as f:
                    config = json.load(f)
                if config.get("container_type") == detected_type:
                    print(f"✅ Auto-selected container config: {candidate}")
                    return candidate
            except Exception:
                continue
    
    return None
