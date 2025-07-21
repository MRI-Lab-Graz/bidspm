#!/usr/bin/env python3

import json
import subprocess
import sys
import os
import shutil
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import List


# ------------------------------
# Configuration
# ------------------------------

CONFIG_FILE = "config.json"
CONTAINER_CONFIG_FILE = "container.json"
LOG_FILE = "run_bidspm.log"
DEBUG = True  # Set to False to suppress debug output


@dataclass
class Config:
    WD: Path
    BIDS_DIR: Path
    SPACE: str
    FWHM: float
    SMOOTH: bool
    STATS: bool
    MODELS_FILE: str
    TASKS: List[str]
    DATASET: bool


@dataclass
class ContainerConfig:
    container_type: str  # "docker" or "apptainer"
    docker_image: str
    apptainer_image: str


def load_config(config_file: str) -> Config:
    if not Path(config_file).exists():
        log_error(f"Config file '{config_file}' not found.")

    with open(config_file) as f:
        data = json.load(f)

    return Config(
        WD=Path(data["WD"]),
        BIDS_DIR=Path(data["BIDS_DIR"]),
        SPACE=data["SPACE"],
        FWHM=data["FWHM"],
        SMOOTH=data["SMOOTH"],
        STATS=data["STATS"],
        MODELS_FILE=data["MODELS_FILE"],
        TASKS=data["TASKS"],
        DATASET=data["DATASET"]
    )


def load_container_config(config_file: str) -> ContainerConfig:
    if not Path(config_file).exists():
        log_error(f"Container config file '{config_file}' not found.")

    with open(config_file) as f:
        data = json.load(f)

    container_type = data.get("container_type", "docker").lower()
    if container_type not in ["docker", "apptainer"]:
        log_error(f"Invalid container_type '{container_type}'. Must be 'docker' or 'apptainer'.")

    return ContainerConfig(
        container_type=container_type,
        docker_image=data.get("docker_image", ""),
        apptainer_image=data.get("apptainer_image", "")
    )


# ------------------------------
# Logging & Utilities
# ------------------------------

def log_debug(msg):
    if DEBUG:
        log(f"[DEBUG] {msg}")


def log_error(msg):
    log(f"[ERROR] {msg}", error=True)
    sys.exit(1)


def log(msg, error=False):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_msg = f"{timestamp} {msg}"
    with open(LOG_FILE, "a") as f:
        f.write(full_msg + "\n")
    print(full_msg, file=sys.stderr if error else sys.stdout)


def check_command(cmd):
    if not shutil.which(cmd):
        log_error(f"'{cmd}' is required but not installed or in PATH.")


def run_command(cmd_list, capture_output=False):
    log_debug(f"Running command: {' '.join(cmd_list)}")
    try:
        result = subprocess.run(cmd_list, check=True, text=True,
                                stdout=subprocess.PIPE if capture_output else None,
                                stderr=subprocess.STDOUT)
        if capture_output:
            log(result.stdout)
    except subprocess.CalledProcessError as e:
        log_error(f"Command failed: {e}")
        sys.exit(1)


def build_container_command(container_config: ContainerConfig, config: Config, args: List[str]) -> List[str]:
    """Build container command based on container type (docker or apptainer)"""
    
    if container_config.container_type == "docker":
        if not container_config.docker_image:
            log_error("Docker image not specified in container configuration.")
        
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{config.WD}:/data",
            container_config.docker_image
        ]
        cmd.extend(args)
        return cmd
    
    elif container_config.container_type == "apptainer":
        if not container_config.apptainer_image:
            log_error("Apptainer image not specified in container configuration.")
        
        if not Path(container_config.apptainer_image).exists():
            log_error(f"Apptainer image file '{container_config.apptainer_image}' not found.")
        
        cmd = [
            "apptainer", "exec",
            "--bind", f"{config.WD}:/data",
            container_config.apptainer_image
        ]
        cmd.extend(args)
        return cmd
    
    else:
        log_error(f"Unsupported container type: {container_config.container_type}")


# ------------------------------
# Main Script
# ------------------------------

def main():
    # Dependency Checks
    check_command("python3")

    # Load configurations
    config = load_config(CONFIG_FILE)
    container_config = load_container_config(CONTAINER_CONFIG_FILE)
    
    # Check container runtime availability
    if container_config.container_type == "docker":
        check_command("docker")
        log_debug(f"Using Docker with image: {container_config.docker_image}")
    elif container_config.container_type == "apptainer":
        check_command("apptainer")
        log_debug(f"Using Apptainer with image: {container_config.apptainer_image}")
    
    model_path = config.WD / "derivatives" / "models" / config.MODELS_FILE

    if not model_path.exists():
        log_error(f"Model file '{config.MODELS_FILE}' not found at '{model_path}'.")

    log_debug("Validating model JSON against BIDS Stats Model schema")
    run_command(["python3", "validate_bids_model.py", str(model_path)], capture_output=True)

    # Path validations
    if not config.WD.is_dir():
        log_error(f"Working directory '{config.WD}' does not exist.")
    if not config.BIDS_DIR.is_dir():
        log_error(f"BIDS directory '{config.BIDS_DIR}' does not exist.")

    # Processing loop
    for task in config.TASKS:
        print("---------------------------------------------------")
        print(f">>> Processing task: {task}")
        print("---------------------------------------------------")

        for sub_dir in (config.WD / "derivatives" / "fmriprep").glob("sub-*"):
            if sub_dir.is_dir():
                subject_label = sub_dir.name.replace("sub-", "")
                log_debug(f"Processing subject: {subject_label}, task: {task}")

                if config.SMOOTH:
                    print(f">>> Smoothing for subject: {subject_label}, task: {task}")
                    smooth_args = [
                        "/data/derivatives/fmriprep", "/data/derivatives", "subject", "smooth",
                        "--participant_label", subject_label,
                        "--task", task,
                        "--space", config.SPACE,
                        "--fwhm", str(config.FWHM),
                        "--verbosity", "0"
                    ]
                    cmd = build_container_command(container_config, config, smooth_args)
                    run_command(cmd)

                if config.STATS:
                    print(f">>> Running stats for subject: {subject_label}, task: {task}")
                    stats_args = [
                        "/data/rawdata", "/data/derivatives", "subject", "stats",
                        "--preproc_dir", "/data/derivatives/bidspm-preproc",
                        "--model_file", f"/data/derivatives/models/{config.MODELS_FILE}",
                        "--participant_label", subject_label,
                        "--task", task,
                        "--space", config.SPACE,
                        "--fwhm", str(config.FWHM),
                        "--verbosity", "0"
                    ]
                    cmd = build_container_command(container_config, config, stats_args)
                    run_command(cmd)

        if config.DATASET:
            print(f">>> Running stats on dataset: task: {task}")
            dataset_args = [
                "/data/rawdata", "/data/derivatives", "dataset", "stats",
                "--preproc_dir", "/data/derivatives/bidspm-preproc",
                "--model_file", f"/data/derivatives/models/{config.MODELS_FILE}",
                "--task", task,
                "--space", config.SPACE,
                "--fwhm", str(config.FWHM),
                "--verbosity", "0"
            ]
            cmd = build_container_command(container_config, config, dataset_args)
            run_command(cmd)

    print(f">>> All processing complete. Logs saved to {LOG_FILE}")


if __name__ == "__main__":
    main()
