#!/usr/bin/env python3
"""
BIDSPM Web Interface - Visual/API Layer Only

This module provides the Flask web interface for BIDSPM.
All business logic is delegated to lib/core.py to avoid code duplication.

The web interface handles:
- API endpoints for frontend communication
- Project management
- File browsing
- Streaming output to clients
- Visual configuration

Structure aligned with bids_apps_runner:
- /projects - Project management page
- /analysis - Analysis/execution page (with project context)

It does NOT handle:
- Model validation logic (use lib.core.validate_bids_model)
- Pipeline execution logic (use lib.core.Pipeline)
- MATLAB detection (use lib.core.detect_matlab_environment)
"""

import os
import json
import secrets
import socket
import subprocess
import signal
import threading
import time
import re
import csv
import shlex
import random
import urllib.request
from collections import Counter
from difflib import get_close_matches
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

from flask import Flask, render_template, request, jsonify, Response, stream_with_context, redirect, url_for
from waitress import serve

# Import all business logic from core
from lib import (
    Pipeline, PipelineOptions, PipelineResult,
    detect_matlab_environment, check_feature_availability,
    discover_subjects, discover_tasks, discover_spaces,
    validate_bids_model, estimate_processing_time,
    load_config
)
from lib.config import auto_select_container_config
from lib.project_manager import project_manager
from web_config_fs_api import register_config_fs_routes
from web_discovery_model_api import register_discovery_model_routes
from web_execution_api import ExecutionRegistry, register_execution_routes
from web_pages import register_page_routes
from web_projects_api import register_project_routes
from web_utility_stats_api import register_utility_stats_routes


# =============================================================================
# App Configuration
# =============================================================================

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Version info
__version__ = "2.0.0"
app.config['APP_VERSION'] = __version__

# Execution state
BIDSPM_SCRIPT = os.path.abspath("bidspm.py")
PYTHON_EXE = os.path.abspath(".bidspm/bin/python")
LOG_DIR = Path("logs")
DEFAULT_PORT = 5100
APP_ROOT = Path(__file__).resolve().parent

MAX_EXECUTIONS = 50  # Cleanup threshold
execution_registry = ExecutionRegistry(
    get_project_manager=lambda: project_manager,
    log_dir=LOG_DIR,
    max_executions=MAX_EXECUTIONS,
)


@app.after_request
def disable_browser_cache(response):
    """Avoid stale startup documents in forwarded/browser-preview sessions."""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


# =============================================================================
# Utility Functions
# =============================================================================

def find_free_port(start_port: int = DEFAULT_PORT, max_tries: int = 100) -> Optional[int]:
    """Find an available port."""
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('0.0.0.0', port))
                return port
            except socket.error:
                continue
    return None


def wait_for_http_ready(url: str, timeout: float = 8.0, interval: float = 0.2) -> bool:
    """Poll a local HTTP URL until it responds or the timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if 200 <= getattr(response, 'status', 0) < 400:
                    return True
        except Exception:
            time.sleep(interval)
    return False


def collect_startup_preflight_checks(app_root: Path = APP_ROOT) -> List[Dict[str, Any]]:
    """Collect basic readiness checks for the local web interface startup."""
    registered_routes = {rule.rule for rule in app.url_map.iter_rules()}
    required_api_routes = {'/check_environment', '/api/model/create', '/api/preflight/tools'}
    required_page_routes = {'/', '/projects', '/analysis', '/model_editor'}

    return [
        {
            'label': 'Core pipeline',
            'ready': all(item is not None for item in (Pipeline, PipelineOptions, PipelineResult)),
        },
        {
            'label': 'Project manager',
            'ready': hasattr(project_manager, 'list_projects') and hasattr(project_manager, 'load_project'),
        },
        {
            'label': 'Templates',
            'ready': (app_root / 'templates').is_dir(),
        },
        {
            'label': 'Static assets',
            'ready': (app_root / 'static').is_dir(),
        },
        {
            'label': 'Config schema',
            'ready': (app_root / 'config' / 'config_schema.json').is_file(),
        },
        {
            'label': 'Waitress server',
            'ready': callable(serve),
        },
        {
            'label': 'REST API',
            'ready': required_api_routes.issubset(registered_routes),
        },
        {
            'label': 'Workflow routes',
            'ready': required_page_routes.issubset(registered_routes),
        },
    ]


def print_startup_preflight_report(app_root: Path = APP_ROOT) -> bool:
    """Print startup checks and return True when every check is ready."""
    checks = collect_startup_preflight_checks(app_root=app_root)
    label_width = max(len(check['label']) for check in checks) + 2

    print('Pre-flight check')
    for check in checks:
        symbol = '✓' if check['ready'] else '✗'
        status = 'ready' if check['ready'] else 'missing'
        print(f"  {symbol} {check['label']:<{label_width}} {status}")

    return all(check['ready'] for check in checks)


def open_browser_when_ready(url: str) -> tuple[bool, str]:
    """Wait for the server URL to respond, then try to open it in a browser."""
    import webbrowser

    if not wait_for_http_ready(url):
        return False, f"Server did not become ready within the browser-open timeout. Open manually: {url}"

    try:
        opened = webbrowser.open(url)
    except Exception as exc:
        return False, f"Unable to open browser automatically ({exc}). Open manually: {url}"

    if opened:
        return True, 'Browser opened automatically'

    return False, f"Browser launch was requested but no browser handler confirmed the open. Open manually: {url}"


def _pids_listening_on_port(port: int) -> List[int]:
    """Return PIDs listening on the given TCP port."""
    try:
        result = subprocess.run(
            ['ss', '-tlnp', f'sport = :{port}'],
            capture_output=True,
            text=True,
            check=False
        )
    except Exception:
        return []

    return sorted({int(pid) for pid in re.findall(r'pid=(\d+)', result.stdout)})


def kill_existing_on_port(port: int) -> bool:
    """Kill any process currently listening on the given port. Returns True if something was killed."""
    killed = False
    own_pid = os.getpid()
    pids = [pid for pid in _pids_listening_on_port(port) if pid != own_pid]

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            killed = True
            print(f"  Stopped existing instance (PID {pid}) on port {port}")
        except (ProcessLookupError, PermissionError):
            continue

    if not killed:
        return False

    deadline = time.time() + 3
    while time.time() < deadline:
        remaining = [pid for pid in _pids_listening_on_port(port) if pid != own_pid]
        if not remaining:
            return True
        time.sleep(0.2)

    remaining = [pid for pid in _pids_listening_on_port(port) if pid != own_pid]
    for pid in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
            print(f"  Force-stopped lingering instance (PID {pid}) on port {port}")
        except (ProcessLookupError, PermissionError):
            continue

    time.sleep(0.2)
    return True


def _get_all_bids_dirs() -> list:
    """Return all BIDS directories registered across all projects (normalised, absolute)."""
    dirs = []
    try:
        for project in project_manager.list_projects():
            bids = getattr(project.config, 'bids_folder', None) or ''
            if bids:
                dirs.append(os.path.normpath(os.path.abspath(bids)))
    except Exception:
        pass
    return dirs


def _is_inside_bids_dir(target_path: str) -> bool:
    """Return True if *target_path* is inside any registered BIDS folder."""
    target = os.path.normpath(os.path.abspath(target_path))
    for bids_dir in _get_all_bids_dirs():
        if target == bids_dir or target.startswith(bids_dir + os.sep):
            return True
    return False


def _resolve_fs_path(path: str) -> str:
    """Resolve user-supplied paths with stable app-root fallback for relative values."""
    raw_path = (path or '').strip()
    if not raw_path:
        return ''

    expanded = os.path.expanduser(raw_path)
    if os.path.isabs(expanded):
        return os.path.normpath(os.path.abspath(expanded))

    app_candidate = os.path.normpath(os.path.abspath(str(APP_ROOT / expanded)))
    cwd_candidate = os.path.normpath(os.path.abspath(expanded))

    if os.path.exists(app_candidate):
        return app_candidate
    if os.path.exists(cwd_candidate):
        return cwd_candidate

    # For new files/directories, keep relative targets anchored to the app root.
    return app_candidate


def _normalize_token_list(raw: Any) -> List[str]:
    """Normalize a scalar/list value into a deduplicated list of non-empty strings."""
    if raw is None:
        return []

    values = raw if isinstance(raw, list) else [raw]
    normalized = []
    seen = set()
    for value in values:
        token = str(value or '').strip()
        if not token or token in seen:
            continue
        seen.add(token)
        normalized.append(token)
    return normalized


def _normalize_subject_ids(raw: Any) -> List[str]:
    """Normalize subject labels to bare IDs (strip optional sub- prefix)."""
    normalized = []
    seen = set()
    for token in _normalize_token_list(raw):
        label = token[4:] if token.lower().startswith('sub-') else token
        label = label.strip()
        if not label or label in seen:
            continue
        seen.add(label)
        normalized.append(label)
    return normalized


def _extract_model_hints(model_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract tasks, contrast levels, and replacement values from a BIDS model."""
    field_status = {
        "model_tasks": "absent",
        "replace_values": "absent",
        "contrast_levels": "absent",
        "transformed_columns": "absent"
    }

    raw_input = model_data.get('Input', {})
    raw_tasks = raw_input.get('task', []) if isinstance(raw_input, dict) else []
    tasks = raw_tasks
    if isinstance(tasks, str):
        tasks = [tasks]
    elif not isinstance(tasks, list):
        tasks = []
        if raw_tasks not in (None, [], ''):
            field_status["model_tasks"] = "invalid"

    replace_values = set()
    contrast_levels = set()
    contrast_terms = set()
    transformed_columns = set()
    saw_replace_instruction = False
    saw_contrast_term = False
    saw_transformations = False

    nodes = model_data.get('Nodes', [])
    if not isinstance(nodes, list):
        nodes = []
        field_status["replace_values"] = "invalid"
        field_status["contrast_levels"] = "invalid"

    for node in nodes:
        if not isinstance(node, dict):
            field_status["replace_values"] = "invalid"
            field_status["contrast_levels"] = "invalid"
            continue

        transformations = node.get('Transformations', {})
        instructions = transformations.get('Instructions', []) if isinstance(transformations, dict) else []
        if transformations and not isinstance(transformations, dict):
            field_status["replace_values"] = "invalid"
            field_status["transformed_columns"] = "invalid"

        if isinstance(transformations, dict):
            saw_transformations = True
            generated_columns = transformations.get('GeneratedColumns', [])
            if generated_columns not in (None, []):
                if not isinstance(generated_columns, list):
                    field_status["transformed_columns"] = "invalid"
                else:
                    for column_name in generated_columns:
                        if isinstance(column_name, str) and column_name.strip():
                            transformed_columns.add(column_name.strip())

        for instruction in instructions if isinstance(instructions, list) else []:
            if not isinstance(instruction, dict):
                field_status["replace_values"] = "invalid"
                field_status["transformed_columns"] = "invalid"
                continue

            output_value = instruction.get('Output')
            if isinstance(output_value, str) and output_value.strip():
                transformed_columns.add(output_value.strip())
            elif isinstance(output_value, list):
                for output_name in output_value:
                    if isinstance(output_name, str) and output_name.strip():
                        transformed_columns.add(output_name.strip())
                    elif output_name not in (None, ''):
                        field_status["transformed_columns"] = "invalid"
            elif output_value not in (None, ''):
                field_status["transformed_columns"] = "invalid"

            if instruction.get('Name') == 'Replace':
                saw_replace_instruction = True
                replace_entries = instruction.get('Replace', [])
                if not isinstance(replace_entries, list):
                    field_status["replace_values"] = "invalid"
                    continue
                for rep in replace_entries:
                    if not isinstance(rep, dict):
                        field_status["replace_values"] = "invalid"
                        continue
                    value = rep.get('value')
                    if isinstance(value, str) and value.strip():
                        replace_values.add(value.strip())

        contrasts = node.get('Contrasts', [])
        if contrasts and not isinstance(contrasts, list):
            field_status["contrast_levels"] = "invalid"
            continue

        for contrast in contrasts if isinstance(contrasts, list) else []:
            if not isinstance(contrast, dict):
                field_status["contrast_levels"] = "invalid"
                continue
            condition_list = contrast.get('ConditionList', [])
            if condition_list and not isinstance(condition_list, list):
                field_status["contrast_levels"] = "invalid"
                continue
            for term in condition_list if isinstance(condition_list, list) else []:
                if not isinstance(term, str):
                    field_status["contrast_levels"] = "invalid"
                    continue
                saw_contrast_term = True
                contrast_terms.add(term)
                if '.' in term:
                    _, level = term.rsplit('.', 1)
                    if level:
                        contrast_levels.add(level)
                else:
                    contrast_levels.add(term)

    model_tasks = sorted({t.strip() for t in tasks if isinstance(t, str) and t.strip()})
    if model_tasks:
        field_status["model_tasks"] = "present"
    elif field_status["model_tasks"] != "invalid":
        field_status["model_tasks"] = "absent"

    if replace_values:
        field_status["replace_values"] = "present"
    elif field_status["replace_values"] != "invalid":
        field_status["replace_values"] = "absent" if saw_replace_instruction or nodes else "absent"

    if contrast_levels:
        field_status["contrast_levels"] = "present"
    elif field_status["contrast_levels"] != "invalid":
        field_status["contrast_levels"] = "absent" if saw_contrast_term or nodes else "absent"

    if transformed_columns:
        field_status["transformed_columns"] = "present"
    elif field_status["transformed_columns"] != "invalid":
        field_status["transformed_columns"] = "absent" if saw_transformations or nodes else "absent"

    return {
        "model_tasks": model_tasks,
        "replace_values": sorted(replace_values),
        "contrast_levels": sorted(contrast_levels),
        "contrast_terms": sorted(contrast_terms),
        "transformed_columns": sorted(transformed_columns),
        "field_status": field_status
    }


def _discover_event_info(bids_dir: Path, tasks_filter: Optional[List[str]] = None, max_files: int = 120) -> Dict[str, Any]:
    """Collect event columns and representative sample values from BIDS *_events.tsv files."""
    if not bids_dir.exists() or not bids_dir.is_dir():
        return {
            "files_scanned": 0,
            "event_columns": [],
            "sample_values": {},
            "all_values": {},
            "numeric_columns": [],
            "numeric_sample_values": {},
            "profile_variants": {},
            "sample_status": {}
        }

    def _normalize_cell(value: Any) -> str:
        text = str(value or '').strip()
        if not text or text.lower() in {'n/a', 'na', 'nan', 'null'}:
            return ''
        return text

    def _is_numeric_token(value: str) -> bool:
        try:
            float(value)
            return True
        except (TypeError, ValueError):
            return False

    task_tokens = set(tasks_filter or [])
    # Only look in subject func folders — never in code/, derivatives/, etc.
    event_files = sorted(bids_dir.glob('sub-*/ses-*/func/*_events.tsv')) + \
                  sorted(bids_dir.glob('sub-*/func/*_events.tsv'))
    event_files = sorted(set(event_files))
    if task_tokens:
        event_files = [
            f for f in event_files
            if any(f"task-{task}_" in f.name or f"task-{task}." in f.name for task in task_tokens)
        ]

    event_columns = set()
    sample_values = {
        "trial_type": set(),
        "condition": set()
    }
    numeric_tracker: Dict[str, Dict[str, Any]] = {}
    profile_counts = {
        "trial_type": Counter(),
        "condition": Counter()
    }

    for event_file in event_files[:max_files]:
        file_values = {
            "trial_type": set(),
            "condition": set()
        }
        try:
            with open(event_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='\t')
                if not reader.fieldnames:
                    continue

                fieldnames = [name.strip() for name in reader.fieldnames if name]
                event_columns.update(fieldnames)

                for row in reader:
                    for col in ('trial_type', 'condition'):
                        if col in row and row[col]:
                            value = str(row[col]).strip()
                            if value and value != 'n/a':
                                sample_values[col].add(value)
                                file_values[col].add(value)

                    for col_name in fieldnames:
                        normalized = _normalize_cell(row.get(col_name, ''))
                        if not normalized:
                            continue
                        if col_name not in numeric_tracker:
                            numeric_tracker[col_name] = {
                                "saw_numeric": False,
                                "saw_non_numeric": False,
                                "sample_values": []
                            }
                        tracker = numeric_tracker[col_name]
                        if _is_numeric_token(normalized):
                            tracker["saw_numeric"] = True
                            samples = tracker["sample_values"]
                            if normalized not in samples and len(samples) < 25:
                                samples.append(normalized)
                        else:
                            tracker["saw_non_numeric"] = True

                    # Keep scan cheap for large files while still collecting a per-file profile.
                    if len(file_values['trial_type']) > 50 and len(file_values['condition']) > 50:
                        break

                for col in ('trial_type', 'condition'):
                    if file_values[col]:
                        profile_counts[col][tuple(sorted(file_values[col]))] += 1
        except Exception:
            continue

    representative_values = {}
    profile_variants = {}
    for col in ('trial_type', 'condition'):
        if profile_counts[col]:
            representative_profile, _ = profile_counts[col].most_common(1)[0]
            representative_values[col] = list(representative_profile)[:30]
            profile_variants[col] = len(profile_counts[col])
        else:
            representative_values[col] = []
            profile_variants[col] = 0

    numeric_columns = sorted([
        col_name
        for col_name, tracker in numeric_tracker.items()
        if tracker.get("saw_numeric") and not tracker.get("saw_non_numeric")
    ])
    numeric_sample_values = {
        col_name: numeric_tracker[col_name].get("sample_values", [])[:12]
        for col_name in numeric_columns
    }

    return {
        "files_scanned": min(len(event_files), max_files),
        "event_columns": sorted(event_columns),
        "sample_values": representative_values,
        "all_values": {
            "trial_type": sorted(sample_values['trial_type'])[:50],
            "condition": sorted(sample_values['condition'])[:50]
        },
        "numeric_columns": numeric_columns,
        "numeric_sample_values": numeric_sample_values,
        "profile_variants": profile_variants,
        "sample_status": {
            "trial_type": "present" if sample_values['trial_type'] else (
                "missing-column" if 'trial_type' not in event_columns else "empty-column"
            ),
            "condition": "present" if sample_values['condition'] else (
                "missing-column" if 'condition' not in event_columns else "empty-column"
            )
        }
    }


def _discover_confound_info(
    fmriprep_dir: Path,
    tasks_filter: Optional[List[str]] = None,
    max_files: int = 120
) -> Dict[str, Any]:
    """Collect confound column names from fMRIPrep desc-confounds_timeseries TSV files."""
    if not fmriprep_dir.exists() or not fmriprep_dir.is_dir():
        return {
            "files_scanned": 0,
            "columns": [],
            "trans_rot_present": [],
            "sample_status": "missing-dir"
        }

    task_tokens = set(tasks_filter or [])
    confound_files = sorted(fmriprep_dir.glob('sub-*/ses-*/func/*desc-confounds_timeseries.tsv')) + \
        sorted(fmriprep_dir.glob('sub-*/func/*desc-confounds_timeseries.tsv'))
    confound_files = sorted(set(confound_files))

    if task_tokens:
        confound_files = [
            f for f in confound_files
            if any(f"task-{task}_" in f.name or f"task-{task}." in f.name for task in task_tokens)
        ]

    if not confound_files:
        return {
            "files_scanned": 0,
            "columns": [],
            "trans_rot_present": [],
            "sample_status": "missing-files"
        }

    columns = set()
    for confound_file in confound_files[:max_files]:
        try:
            with open(confound_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, delimiter='\t')
                if not reader.fieldnames:
                    continue
                columns.update(name.strip() for name in reader.fieldnames if name and name.strip())
        except Exception:
            continue

    trans_rot_defaults = ['trans_x', 'trans_y', 'trans_z', 'rot_x', 'rot_y', 'rot_z']
    trans_rot_present = [name for name in trans_rot_defaults if name in columns]

    return {
        "files_scanned": min(len(confound_files), max_files),
        "columns": sorted(columns),
        "trans_rot_present": trans_rot_present,
        "sample_status": "present" if columns else "empty"
    }


def _discover_participants_info(bids_dir: Path, max_values_per_column: int = 20) -> Dict[str, Any]:
    """Collect participants.tsv metadata for dataset-level grouping and covariates."""
    default_payload = {
        "columns": [],
        "categorical_columns": [],
        "numeric_columns": [],
        "sample_values": {},
        "numeric_stats": {},
        "sample_status": "missing-dir"
    }

    if not bids_dir.exists() or not bids_dir.is_dir():
        return default_payload

    participants_file = bids_dir / 'participants.tsv'
    if not participants_file.is_file():
        return {
            **default_payload,
            "sample_status": "missing-file"
        }

    def _normalize_token(value: Any) -> str:
        text = str(value or '').strip()
        if not text or text.lower() in {'n/a', 'na', 'nan', 'null'}:
            return ''
        return text

    def _parse_number(value: str) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _sort_key(token: str):
        if token.isdigit():
            return (0, int(token), token)
        parsed = _parse_number(token)
        if parsed is not None:
            return (1, parsed, token)
        return (2, token.lower(), token)

    try:
        with open(participants_file, 'r', encoding='utf-8') as stream:
            reader = csv.DictReader(stream, delimiter='\t')
            if not reader.fieldnames:
                return {
                    **default_payload,
                    "sample_status": "invalid-header"
                }

            columns = [
                name.strip() for name in reader.fieldnames
                if name and name.strip() and name.strip() != 'participant_id'
            ]
            if not columns:
                return {
                    **default_payload,
                    "sample_status": "empty"
                }

            value_sets = {column: set() for column in columns}
            numeric_flags = {column: True for column in columns}

            for row in reader:
                for column in columns:
                    normalized = _normalize_token(row.get(column, ''))
                    if not normalized:
                        continue
                    value_sets[column].add(normalized)
                    if _parse_number(normalized) is None:
                        numeric_flags[column] = False

        categorical_columns = []
        numeric_columns = []
        sample_values = {}
        numeric_stats = {}

        for column in columns:
            sorted_values = sorted(value_sets[column], key=_sort_key)
            sample_values[column] = sorted_values[:max_values_per_column]

            if sorted_values and numeric_flags[column]:
                numeric_columns.append(column)
                numeric_values = [
                    number for number in (_parse_number(value) for value in sorted_values)
                    if number is not None
                ]
                if numeric_values:
                    numeric_stats[column] = {
                        "min": min(numeric_values),
                        "max": max(numeric_values),
                        "count": len(numeric_values)
                    }
            else:
                categorical_columns.append(column)

        return {
            "columns": columns,
            "categorical_columns": categorical_columns,
            "numeric_columns": numeric_columns,
            "sample_values": sample_values,
            "numeric_stats": numeric_stats,
            "sample_status": "present"
        }
    except Exception:
        return {
            **default_payload,
            "sample_status": "error"
        }


def _build_model_warnings(model_hints: Dict[str, Any], bids_tasks: List[str], event_info: Dict[str, Any]) -> List[str]:
    """Generate typo-oriented warnings from model and dataset context."""
    warnings = []
    model_tasks = model_hints.get('model_tasks', [])
    replace_values = set(model_hints.get('replace_values', []))
    contrast_levels = model_hints.get('contrast_levels', [])
    transformed_columns = set(model_hints.get('transformed_columns', []))

    if bids_tasks and model_tasks:
        missing_tasks = [task for task in model_tasks if task not in bids_tasks]
        for task in missing_tasks:
            suggestions = get_close_matches(task, bids_tasks, n=3, cutoff=0.6)
            if suggestions:
                warnings.append(
                    f"Task '{task}' is not present in BIDS data. Close matches: {', '.join(suggestions)}"
                )
            else:
                warnings.append(f"Task '{task}' is not present in BIDS data.")

    if replace_values and contrast_levels:
        for level in contrast_levels:
            if level in replace_values or level in transformed_columns:
                continue
            suggestions = get_close_matches(level, list(replace_values), n=3, cutoff=0.6)
            if suggestions:
                warnings.append(
                    f"Contrast level '{level}' is not generated by Replace values. Close matches: {', '.join(suggestions)}"
                )

    trial_type_variants = int(event_info.get('profile_variants', {}).get('trial_type', 0) or 0)
    if trial_type_variants > 1:
        warnings.append(
            f"Detected {trial_type_variants} distinct trial_type profiles across the selected task files. "
            "Editor suggestions use the most common profile to avoid mixing incompatible event codings."
        )

    raw_value_source = event_info.get('all_values') or event_info.get('sample_values') or {}
    raw_conditions = set(raw_value_source.get('condition', [])) | set(
        raw_value_source.get('trial_type', [])
    )
    if raw_conditions and not replace_values and contrast_levels:
        for level in contrast_levels:
            if level in raw_conditions or level in transformed_columns:
                continue
            suggestions = get_close_matches(level, list(raw_conditions), n=3, cutoff=0.7)
            if suggestions:
                warnings.append(
                    f"Contrast level '{level}' does not appear in sampled event values. Close matches: {', '.join(suggestions)}"
                )

    return warnings


# =============================================================================
# Main Pages / Project APIs
# =============================================================================

register_page_routes(app, get_project_manager=lambda: project_manager)
register_project_routes(app, get_project_manager=lambda: project_manager)


# =============================================================================
# Utility API Endpoints
# =============================================================================

register_config_fs_routes(
    app,
    resolve_fs_path=_resolve_fs_path,
    is_inside_bids_dir=_is_inside_bids_dir,
)
register_execution_routes(
    app,
    execution_registry=execution_registry,
    get_project_manager=lambda: project_manager,
    normalize_subject_ids=_normalize_subject_ids,
    validate_bids_model=validate_bids_model,
    bidspm_script=BIDSPM_SCRIPT,
    python_exe_path=PYTHON_EXE,
)
register_discovery_model_routes(
    app,
    resolve_fs_path=_resolve_fs_path,
    app_root=APP_ROOT,
)
register_utility_stats_routes(
    app,
    get_project_manager=lambda: project_manager,
    resolve_fs_path=_resolve_fs_path,
    normalize_token_list=_normalize_token_list,
    normalize_subject_ids=_normalize_subject_ids,
)


# =============================================================================
# Server Control
# =============================================================================

@app.route('/shutdown', methods=['POST'])
def shutdown():
    """Shutdown the server."""
    print("Shutdown requested...")
    os._exit(0)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='BIDSPM Web Interface')
    parser.add_argument('-p', '--port', type=int, default=None,
                       help='Port to use (default: 5100; any existing instance on that port is stopped first)')
    parser.add_argument('--no-browser', action='store_true',
                       help='Do not attempt to open a browser automatically (useful on headless servers)')
    args = parser.parse_args()

    target_port = args.port or DEFAULT_PORT

    # Kill any stale instance on the target port so the user always gets
    # a fresh server at the same URL (fixes the recurring blank-page issue).
    kill_existing_on_port(target_port)

    port = find_free_port(target_port, max_tries=1)
    if not port:
        print(f"Error: Port {target_port} is still in use after attempting to free it.")
        import sys
        sys.exit(1)

    url = f"http://localhost:{port}"
    preflight_ready = print_startup_preflight_report()

    print()
    print(f"Open in browser: {url}")
    if args.no_browser:
        status = 'ready' if preflight_ready else 'startup checks completed with warnings'
        print(f"Status: {status}. Browser auto-launch disabled (--no-browser).")
    elif preflight_ready:
        print('Status: ready. Launching the interface now.')
    else:
        print('Status: startup checks completed with warnings. Launching the interface now.')
    print('Press Ctrl+C to stop the server')
    print()
    print(f"Running with Waitress server on 0.0.0.0:{port}")

    if not args.no_browser:
        def launch_browser() -> None:
            opened, message = open_browser_when_ready(url)
            prefix = '✅' if opened else '⚠️'
            print(f"{prefix} {message}")

        threading.Timer(1, launch_browser).start()

    serve(app, host='0.0.0.0', port=port, threads=10)
