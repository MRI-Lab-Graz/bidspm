# bidspm library modules
"""
BIDSPM Library - Core functionality for BIDS-StatsModel pipelines.

Modules:
    - config: Configuration loading and management
    - utils: Logging, validation, file operations
    - core: Main pipeline logic (shared between CLI and web)
    - project_manager: Project management for the web interface
"""

from .config import Config, ContainerConfig, load_config, load_container_config
from .utils import (
    log, log_debug, log_error, log_error_non_fatal,
    generate_log_filename, check_command, run_command
)
from .core import (
    Pipeline, PipelineOptions, PipelineResult,
    discover_subjects, discover_tasks, discover_spaces,
    check_subject_processed,
    validate_bids_model, estimate_processing_time,
    resolve_models_dir, run_bms,
    check_models_dir_node_collision,
)
from .project_manager import (
    ProjectManager, Project, ProjectConfig,
    project_manager, PROJECTS_DIR, DATA_DIR
)

__all__ = [
    # Config
    'Config', 'ContainerConfig', 'load_config', 'load_container_config',
    # Utils
    'log', 'log_debug', 'log_error', 'log_error_non_fatal',
    'generate_log_filename', 'check_command', 'run_command',
    # Core
    'Pipeline', 'PipelineOptions', 'PipelineResult',
    'discover_subjects', 'discover_tasks', 'discover_spaces',
    'check_subject_processed',
    'validate_bids_model', 'estimate_processing_time',
    'resolve_models_dir', 'run_bms', 'check_models_dir_node_collision',
    # Project Manager
    'ProjectManager', 'Project', 'ProjectConfig',
    'project_manager', 'PROJECTS_DIR', 'DATA_DIR',
]
