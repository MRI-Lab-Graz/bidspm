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
from lib.project_manager import ProjectManager, Project, ProjectConfig, project_manager


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

# Store running executions (with periodic cleanup)
executions: Dict[str, Dict[str, Any]] = {}
current_execution_id: Optional[str] = None
current_project_id: Optional[str] = None
MAX_EXECUTIONS = 50  # Cleanup threshold


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


def should_skip_browser_auto_open() -> tuple[bool, str]:
    """Return whether browser auto-open should be skipped and why."""
    browser_cmd = os.environ.get('BROWSER', '')
    term_program = os.environ.get('TERM_PROGRAM', '')

    vscode_markers = [
        'browser.sh' in browser_cmd,
        term_program == 'vscode',
        bool(os.environ.get('VSCODE_IPC_HOOK_CLI')),
        bool(os.environ.get('VSCODE_GIT_ASKPASS_NODE')),
        bool(os.environ.get('VSCODE_GIT_IPC_HANDLE')),
    ]
    if any(vscode_markers):
        return True, 'VS Code environment detected'

    ssh_session = bool(os.environ.get('SSH_CONNECTION') or os.environ.get('SSH_TTY'))
    headless = not bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))
    if ssh_session and headless:
        return True, 'headless SSH session detected'

    return False, ''


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


def cleanup_old_executions():
    """Remove old completed executions to prevent memory growth."""
    global executions
    if len(executions) <= MAX_EXECUTIONS:
        return
    
    # Remove oldest finished executions
    finished = [(eid, e) for eid, e in executions.items() if e.get('finished')]
    finished.sort(key=lambda x: x[1].get('start_time', 0))
    
    to_remove = len(executions) - MAX_EXECUTIONS
    for eid, _ in finished[:to_remove]:
        del executions[eid]


def _execution_log_location(project_id: Optional[str], execution_id: str) -> tuple[Path, str]:
    """Return log file path and display filename for an execution."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if project_id:
        log_dir = project_manager.get_project_logs_dir(project_id)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_filename = f"run_{timestamp}_{execution_id[:8]}.log"
        return log_dir / log_filename, log_filename

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_filename = f"web_run_{timestamp}_{execution_id[:8]}.log"
    return LOG_DIR / log_filename, log_filename


def _append_execution_log(log_file: Path, message: str) -> None:
    """Append text to the execution log file."""
    with open(log_file, 'a', encoding='utf-8') as log:
        log.write(message)
        log.flush()


def _sanitize_sse_line(line: str) -> str:
    """Normalize log text for SSE transport."""
    return re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', ' ', line).rstrip("\n")


def _finalize_execution(execution_id: str, return_code: int) -> None:
    """Mark an execution finished and persist its terminal status to the log."""
    global current_execution_id

    exec_info = executions.get(execution_id)
    if not exec_info or exec_info.get('finished'):
        return

    finish_msg = f"\n[{datetime.now().isoformat()}] Process finished with exit code {return_code}\n"
    log_file = Path(exec_info['log_file'])
    _append_execution_log(log_file, finish_msg)

    exec_info['finished'] = True
    exec_info['return_code'] = return_code
    exec_info['process'] = None

    project_id = exec_info.get('project_id')
    log_filename = exec_info.get('log_filename')
    if project_id and log_filename:
        project_manager.update_project_log(project_id, log_filename)

    if current_execution_id == execution_id:
        current_execution_id = None


def _monitor_execution(execution_id: str, process: subprocess.Popen) -> None:
    """Wait for a detached execution and mark it finished when it exits."""
    try:
        return_code = process.wait()
    except Exception:
        return_code = -1
    _finalize_execution(execution_id, return_code)


def _get_all_bids_dirs() -> list:
    """Return all BIDS directories registered across all projects (normalised, absolute)."""
    dirs = []
    try:
        for project in project_manager.list_projects():
            bids = getattr(project.config, 'bids_dir', None) or ''
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
    """Collect event columns and sample values from BIDS *_events.tsv files."""
    if not bids_dir.exists() or not bids_dir.is_dir():
        return {
            "files_scanned": 0,
            "event_columns": [],
            "sample_values": {},
            "sample_status": {}
        }

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

    for event_file in event_files[:max_files]:
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
                            sample_values[col].add(str(row[col]).strip())
                    # Keep scan cheap for large files
                    if len(sample_values['trial_type']) > 50 and len(sample_values['condition']) > 50:
                        break
        except Exception:
            continue

    return {
        "files_scanned": min(len(event_files), max_files),
        "event_columns": sorted(event_columns),
        "sample_values": {
            "trial_type": sorted(sample_values['trial_type'])[:30],
            "condition": sorted(sample_values['condition'])[:30]
        },
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

    raw_conditions = set(event_info.get('sample_values', {}).get('condition', [])) | set(
        event_info.get('sample_values', {}).get('trial_type', [])
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
# Main Pages
# =============================================================================

@app.route('/test')
def test_page():
    """Simple test page to verify server is working."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>BIDSPM Test</title></head>
    <body style="font-family: sans-serif; padding: 20px;">
        <h1>BIDSPM Web Interface - Test Page</h1>
        <p>If you see this, the server is working correctly.</p>
        <p><a href="/">Go to main interface</a></p>
        <h2>System Info:</h2>
        <ul>
            <li>Server: Flask + Waitress</li>
            <li>Templates: Jinja2</li>
        </ul>
    </body>
    </html>
    """

@app.route('/')
@app.route('/projects')
def projects_page():
    """Render projects management page."""
    projects = project_manager.list_projects()
    return render_template('projects.html', 
                          projects=projects,
                          project_count=len(projects))


@app.route('/analysis')
@app.route('/analysis/<project_id>')
def analysis_page(project_id: Optional[str] = None):
    """Render analysis page, optionally with a project loaded."""
    project = None
    projects = project_manager.list_projects()
    
    if project_id:
        project = project_manager.load_project(project_id)
    
    return render_template('analysis.html', 
                          project=project,
                          projects=projects,
                          current_project_id=project_id,
                          current_project=project)


@app.route('/model_editor')
@app.route('/model_editor/<project_id>')
def model_editor_page(project_id: Optional[str] = None):
    """Dedicated model editor page (split-screen) for editing model JSON and transformations."""
    project = None
    projects = project_manager.list_projects()
    if project_id:
        project = project_manager.load_project(project_id)

    model_path = request.args.get('path', '')
    return render_template('model_editor.html',
                           project=project,
                           projects=projects,
                           current_project_id=project_id,
                           current_project=project,
                           model_path=model_path)


# =============================================================================
# Utility API Endpoints
# =============================================================================


@app.route('/transformer-builder')
@app.route('/transformer-builder/<project_id>')
def transformer_builder_page(project_id: Optional[str] = None):
    """Visual transformer builder for creating BIDS model transformations."""
    project = None
    projects = project_manager.list_projects()
    if project_id:
        project = project_manager.load_project(project_id)

    return render_template(
        'transformer_builder.html',
        project=project,
        projects=projects,
        current_project_id=project_id,
        current_project=project
    )
@app.route('/api/detect-spaces', methods=['POST'])
def api_detect_spaces():
    """Detect available spaces from fMRIPrep folder."""
    try:
        data = request.json or {}
        fmriprep_path = data.get('path', '').strip()
        
        if not fmriprep_path:
            return jsonify({"spaces": [], "error": "No path provided"})
        
        path = Path(fmriprep_path)
        if not path.exists():
            return jsonify({"spaces": [], "error": "Path not found"})
        
        # Detect spaces from file names
        available_spaces = []
        space_patterns = ['MNI152NLin2009cAsym', 'MNI152NLin6Asym', 'MNI152NLin2009cSym', 
                          'MNI152NLin6Sym', 'MNIPediatricAsym', 'T1w', 'fsaverage', 
                          'fsLR', 'fsnative', 'anat']
        
        for space in space_patterns:
            if list(path.glob(f'**/*space-{space}*.nii*')):
                available_spaces.append(space)
        
        return jsonify({"spaces": available_spaces})
    except Exception as e:
        return jsonify({"spaces": [], "error": str(e)})


# =============================================================================
# Project Management API
# =============================================================================

@app.route('/api/projects', methods=['GET'])
def api_list_projects():
    """List all projects."""
    try:
        projects = project_manager.list_projects()
        return jsonify({
            "projects": [p.to_dict() for p in projects],
            "count": len(projects)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects', methods=['POST'])
def api_create_project():
    """Create a new project."""
    try:
        data = request.json or {}
        name = data.get('name', '').strip()
        description = data.get('description', '').strip()
        config = data.get('config', None)
        
        if not name:
            return jsonify({"error": "Project name is required"}), 400
        
        project = project_manager.create_project(name, description, config)
        return jsonify({
            "project": project.to_dict(),
            "message": f"Project '{name}' created successfully"
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects/<project_id>', methods=['GET'])
def api_get_project(project_id: str):
    """Get a project by ID."""
    try:
        project = project_manager.load_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        return jsonify(project.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects/<project_id>', methods=['PUT'])
def api_update_project(project_id: str):
    """Update a project."""
    try:
        project = project_manager.load_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        
        data = request.json or {}
        
        if 'name' in data:
            project.name = data['name']
        if 'description' in data:
            project.description = data['description']
        if 'config' in data:
            # Merge new config with existing config
            existing_config = project.config.to_dict()
            existing_config.update(data['config'])
            project.config = ProjectConfig.from_dict(existing_config)
        
        project_manager.save_project(project)
        return jsonify({
            "project": project.to_dict(),
            "message": "Project updated successfully"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects/<project_id>', methods=['DELETE'])
def api_delete_project(project_id: str):
    """Delete a project."""
    try:
        project = project_manager.load_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        
        name = project.name
        project_manager.delete_project(project_id)
        return jsonify({"message": f"Project '{name}' deleted successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects/<project_id>/duplicate', methods=['POST'])
def api_duplicate_project(project_id: str):
    """Duplicate a project."""
    try:
        data = request.json or {}
        new_name = data.get('name')
        
        new_project = project_manager.duplicate_project(project_id, new_name)
        if not new_project:
            return jsonify({"error": "Project not found"}), 404
        
        return jsonify({
            "project": new_project.to_dict(),
            "message": f"Project duplicated as '{new_project.name}'"
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects/<project_id>/preflight', methods=['GET'])
def api_preflight_check(project_id: str):
    """Run preflight checks for a project."""
    try:
        project = project_manager.load_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        
        config = project.config
        results = {}
        
        # Check BIDS folder
        bids_path = Path(config.bids_folder) if config.bids_folder else None
        if not bids_path or not config.bids_folder:
            results['bids_folder'] = {'status': 'na', 'message': 'Not configured'}
        elif bids_path.exists():
            # Check for dataset_description.json
            if (bids_path / 'dataset_description.json').exists():
                results['bids_folder'] = {'status': 'ok', 'message': 'Valid BIDS folder'}
            else:
                results['bids_folder'] = {'status': 'warning', 'message': 'Folder exists but no dataset_description.json'}
        else:
            results['bids_folder'] = {'status': 'error', 'message': 'Folder not found'}
        
        # Check fMRIPrep folder
        fmriprep_path = Path(config.fmriprep_folder) if config.fmriprep_folder else None
        if not fmriprep_path or not config.fmriprep_folder:
            results['fmriprep_folder'] = {'status': 'na', 'message': 'Not configured'}
        elif fmriprep_path.exists():
            # Check for dataset_description.json
            if (fmriprep_path / 'dataset_description.json').exists():
                results['fmriprep_folder'] = {'status': 'ok', 'message': 'Valid fMRIPrep folder'}
            else:
                results['fmriprep_folder'] = {'status': 'warning', 'message': 'Folder exists but no dataset_description.json'}
        else:
            results['fmriprep_folder'] = {'status': 'error', 'message': 'Folder not found'}
        
        # Check for event files
        if bids_path and bids_path.exists():
            import glob
            # Only count events files in subject func folders
            event_files = list(bids_path.glob('sub-*/ses-*/func/*_events.tsv')) + \
                          list(bids_path.glob('sub-*/func/*_events.tsv'))
            if event_files:
                results['events'] = {'status': 'ok', 'message': f'{len(event_files)} event files found', 'value': str(len(event_files))}
            else:
                results['events'] = {'status': 'error', 'message': 'No event files found'}
        else:
            results['events'] = {'status': 'na', 'message': 'BIDS folder not available'}
        
        # Check space availability
        space = config.space or 'MNI152NLin2009cAsym'
        available_spaces = []
        if fmriprep_path and fmriprep_path.exists():
            # Look for space patterns in file names
            for space_name in ['MNI152NLin2009cAsym', 'MNI152NLin6Asym', 'T1w']:
                if list(fmriprep_path.glob(f'**/*space-{space_name}*.nii*')):
                    available_spaces.append(space_name)
            
            if space in available_spaces:
                results['space'] = {'status': 'ok', 'message': f'{space} available', 'value': space}
            elif available_spaces:
                results['space'] = {'status': 'warning', 'message': f'{space} not found. Available: {", ".join(available_spaces)}', 'value': available_spaces[0]}
            else:
                results['space'] = {'status': 'warning', 'message': 'No spaces detected'}
        else:
            results['space'] = {'status': 'na', 'message': 'fMRIPrep folder not available', 'value': space}
        
        # Check if smoothing is done
        output_path = Path(config.output_folder) if config.output_folder else None
        if output_path and output_path.exists():
            smooth_files = list(output_path.glob('**/*desc-smth*')) + list(output_path.glob('**/smooth/**/*.nii*'))
            if smooth_files:
                results['smooth'] = {'status': 'ok', 'message': f'Smoothing done ({len(smooth_files)} files)', 'value': 'Yes'}
            else:
                results['smooth'] = {'status': 'na', 'message': 'No smoothed files found', 'value': 'No'}
        else:
            results['smooth'] = {'status': 'na', 'message': 'Output folder not available', 'value': 'No'}
        
        # Include available spaces for dropdown
        results['available_spaces'] = available_spaces
        
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects/<project_id>/config', methods=['GET'])
def api_get_project_config(project_id: str):
    """Get project configuration."""
    try:
        project = project_manager.load_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        return jsonify(project.config.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects/<project_id>/config', methods=['PUT'])
def api_update_project_config(project_id: str):
    """Update project configuration."""
    try:
        data = request.json or {}
        success = project_manager.update_project_config(project_id, data)
        if not success:
            return jsonify({"error": "Project not found"}), 404
        return jsonify({"message": "Configuration updated successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects/<project_id>/import', methods=['POST'])
def api_import_config(project_id: str):
    """Import configuration from existing config file."""
    try:
        data = request.json or {}
        config_path = data.get('path')
        
        if not config_path or not os.path.exists(config_path):
            return jsonify({"error": "Config file not found"}), 400
        
        success = project_manager.import_config(project_id, Path(config_path))
        if not success:
            return jsonify({"error": "Failed to import configuration"}), 500
        
        return jsonify({"message": "Configuration imported successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects/<project_id>/export', methods=['GET'])
def api_export_config(project_id: str):
    """Export project configuration in BIDSPM format."""
    try:
        format_type = request.args.get('format', 'bidspm')
        config = project_manager.export_config(project_id, format_type)
        
        if not config:
            return jsonify({"error": "Project not found"}), 404
        
        return jsonify(config)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects/<project_id>/logs', methods=['GET'])
def api_get_project_logs(project_id: str):
    """Get project execution logs."""
    try:
        logs_dir = project_manager.get_project_logs_dir(project_id)
        
        if not logs_dir.exists():
            return jsonify({"logs": []})
        
        logs = []
        for log_file in sorted(logs_dir.glob("*.log"), reverse=True):
            stat = log_file.stat()
            logs.append({
                "name": log_file.name,
                "path": str(log_file),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
            })
        
        return jsonify({"logs": logs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# Pipeline Execution
# =============================================================================

@app.route('/run', methods=['POST'])
def run_bidspm():
    """
    Start pipeline execution.
    Delegates to lib.core.Pipeline but runs in subprocess for isolation.
    Supports project context for organized log storage.
    """
    global current_project_id
    
    data = request.json or {}
    actions = data.get('actions', [])
    project_id = data.get('project_id')
    
    if not actions:
        return jsonify({"error": "No actions selected"}), 400
    
    execution_id = secrets.token_hex(8)
    current_project_id = project_id

    # Project mode: always materialize and use the current project config for execution.
    # This avoids falling back to default config/config.json with stale MODELS_FILE values.
    if project_id:
        project = project_manager.load_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        if not data.get('settings'):
            configs_dir = project_manager.get_project_configs_dir(project_id)
            configs_dir.mkdir(parents=True, exist_ok=True)
            run_cfg_path = configs_dir / f"run_settings_{execution_id}.json"

            export_cfg = project_manager.export_config(project_id, format='bidspm') or {}
            with open(run_cfg_path, 'w', encoding='utf-8') as f:
                json.dump(export_cfg, f, indent=2)
                f.write('\n')

            data['settings'] = str(run_cfg_path)

        # If no explicit model override provided, use the project's models_file.
        if not data.get('model') and project.config.models_file:
            data['model'] = project.config.models_file
    
    # Pre-validate model if provided (uses core module)
    model_file = data.get('model')
    if model_file and any('stats' in action.lower() for action in actions):
        if not data.get('skip_validation'):
            if not os.path.isfile(model_file):
                return jsonify({"error": f"Model file not found: {model_file}"}), 400
            
            result = validate_bids_model(Path(model_file))
            if not result["valid"]:
                return jsonify({"error": f"Model validation failed: {result.get('error', 'Unknown error')}"}), 400

    # Build command
    python_exe = PYTHON_EXE if os.path.exists(PYTHON_EXE) else "python3"
    command = [python_exe, BIDSPM_SCRIPT]
    command.extend(['--action'] + actions)
    
    if data.get('settings'):
        command.extend(['--settings', data.get('settings')])
    if data.get('container'):
        command.extend(['--container', data.get('container')])
    if data.get('model'):
        command.extend(['--model', data.get('model')])
    if data.get('pilot'):
        command.append('--pilot')
    if data.get('skip_validation'):
        command.append('--skip-modelvalidation')
    if data.get('local'):
        command.append('--local')
    if data.get('force'):
        command.append('--force')

    cleanup_old_executions()

    log_file, log_filename = _execution_log_location(project_id, execution_id)
    command_display = shlex.join(command)
    
    executions[execution_id] = {
        'command': command,
        'finished': False,
        'process': None,
        'start_time': time.time(),
        'project_id': project_id,
        'log_file': str(log_file),
        'log_filename': log_filename,
        'return_code': None,
        'stop_requested': False,
        'pid': None
    }

    global current_execution_id
    current_execution_id = execution_id

    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'

    header = (
        f"\n{'=' * 80}\n"
        f"[{datetime.now().isoformat()}] Executing (detached via nohup): {command_display}\n"
        f"Log file: {log_file}\n"
        f"{'=' * 80}\n\n"
    )

    try:
        with open(log_file, 'a', encoding='utf-8', buffering=1) as log:
            log.write(header)
            log.flush()
            process = subprocess.Popen(
                ['nohup'] + command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
                text=True
            )
    except Exception as e:
        executions[execution_id]['finished'] = True
        _append_execution_log(log_file, f"[{datetime.now().isoformat()}] Failed to start execution: {str(e)}\n")
        return jsonify({"error": f"Failed to start execution: {str(e)}"}), 500

    executions[execution_id]['process'] = process
    executions[execution_id]['pid'] = process.pid

    monitor = threading.Thread(target=_monitor_execution, args=(execution_id, process), daemon=True)
    monitor.start()

    return jsonify({
        "execution_id": execution_id,
        "project_id": project_id,
        "log_file": str(log_file),
        "log_filename": log_filename,
        "pid": process.pid
    })


@app.route('/stream/<execution_id>')
def stream_output(execution_id: str):
    """Stream execution output to client via SSE."""
    def generate():
        if execution_id not in executions:
            yield "data: Error: Execution not found\n\n"
            return

        exec_info = executions[execution_id]
        log_file = Path(exec_info.get('log_file', ''))
        offset = 0
        keepalive_at = time.time()

        while True:
            emitted = False

            if log_file.exists():
                try:
                    with open(log_file, 'r', encoding='utf-8', errors='replace') as log:
                        log.seek(offset)
                        while True:
                            line = log.readline()
                            if not line:
                                offset = log.tell()
                                break
                            yield f"data: {_sanitize_sse_line(line)}\n\n"
                            emitted = True
                except Exception as e:
                    yield f"data: Log streaming error: {_sanitize_sse_line(str(e))}\n\n"
                    break

            if exec_info.get('finished') and not emitted:
                break

            if not emitted and (time.time() - keepalive_at) >= 1:
                yield ": keepalive\n\n"
                keepalive_at = time.time()

            time.sleep(0.2)
                
    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@app.route('/stop', methods=['POST'])
def stop_execution():
    """Stop current execution."""
    global current_execution_id
    
    if not current_execution_id or current_execution_id not in executions:
        return jsonify({"status": "no process running"})
    
    exec_info = executions[current_execution_id]
    
    if exec_info['finished'] or not exec_info['process']:
        return jsonify({"status": "already finished"})
    
    try:
        proc = exec_info['process']
        if proc.poll() is None:
            exec_info['stop_requested'] = True
            _append_execution_log(Path(exec_info['log_file']), f"\n[{datetime.now().isoformat()}] --- Stop requested by user ---\n")
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGINT)
                time.sleep(1)
                if proc.poll() is None:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    time.sleep(1)
                if proc.poll() is None:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception:
                proc.terminate()
                if proc.poll() is None:
                    proc.kill()
        return jsonify({"status": "stopping"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# Discovery Endpoints (delegate to core)
# =============================================================================

@app.route('/get_bids_tasks')
def get_bids_tasks():
    """Get tasks from BIDS directory."""
    path = request.args.get('path')
    if not path or not os.path.isdir(path):
        return jsonify([])
    
    tasks = discover_tasks(Path(path))
    return jsonify(tasks)


@app.route('/api/bids_entities')
def api_bids_entities():
    """Discover BIDS entities and observed values from dataset filenames."""
    path = request.args.get('path')
    if not path or not os.path.isdir(path):
        return jsonify({
            "entities": [],
            "groupby_options": ["subject"],
            "values": {"task": [], "run": [], "session": [], "subject": []}
        })

    bids_path = Path(path)
    entity_aliases = {
        'sub': 'subject',
        'ses': 'session',
        'acq': 'acquisition',
        'ce': 'ceagent',
        'rec': 'reconstruction',
        'dir': 'direction',
        'proc': 'processing',
        'desc': 'description',
        'res': 'resolution',
        'den': 'density',
        'trc': 'tracer'
    }
    known_datatypes = {
        'anat', 'func', 'dwi', 'fmap', 'perf', 'meg', 'eeg', 'ieeg', 'beh', 'pet',
        'micr', 'nirs', 'motion', 'mrs'
    }

    entities = set()
    values = {}

    def _add_value(key: str, value: str) -> None:
        key = (key or '').strip()
        value = (value or '').strip()
        if not key or not value:
            return
        entities.add(key)
        values.setdefault(key, set()).add(value)

    def _filename_stem(filename: str) -> str:
        if filename.endswith('.nii.gz'):
            return filename[:-7]
        if filename.endswith('.tsv.gz'):
            return filename[:-7]
        if filename.endswith('.json.gz'):
            return filename[:-8]
        return Path(filename).stem

    def _file_extension(file_path: Path) -> str:
        name = file_path.name
        if name.endswith('.nii.gz'):
            return '.nii.gz'
        if name.endswith('.tsv.gz'):
            return '.tsv.gz'
        if name.endswith('.json.gz'):
            return '.json.gz'
        return ''.join(file_path.suffixes) or file_path.suffix or ''

    max_scan = 8000
    scanned = 0

    try:
        for file_path in bids_path.rglob('*'):
            if scanned >= max_scan:
                break
            if not file_path.is_file():
                continue

            scanned += 1
            name = file_path.name

            # Parse entity key-value tokens from filename stem.
            stem = _filename_stem(name)
            tokens = [tok for tok in stem.split('_') if tok]
            for token in tokens:
                if '-' not in token:
                    continue
                short_key, raw_value = token.split('-', 1)
                key = entity_aliases.get(short_key, short_key)
                _add_value(key, raw_value)

            # Parse suffix from final non-entity token.
            suffix_token = ''
            for token in tokens:
                if '-' not in token:
                    suffix_token = token
            if suffix_token:
                _add_value('suffix', suffix_token)

            # Parse datatype from path folders.
            for part in file_path.parts:
                if part in known_datatypes:
                    _add_value('datatype', part)

            # Parse subject/session from parent directories where available.
            for part in file_path.parts[:-1]:
                if part.startswith('sub-') and len(part) > 4:
                    _add_value('subject', part[4:])
                elif part.startswith('ses-') and len(part) > 4:
                    _add_value('session', part[4:])

            # Track file extension.
            extension = _file_extension(file_path)
            if extension:
                _add_value('extension', extension)

    except Exception:
        pass

    # Prefer discover_tasks() for task labels when available.
    try:
        discovered_tasks = discover_tasks(bids_path)
        for task in discovered_tasks:
            if isinstance(task, str) and task.strip():
                _add_value('task', task.strip())
    except Exception:
        pass

    def _sort_tokens(tokens):
        def key_fn(token):
            text = str(token)
            if text.isdigit():
                return (0, int(text), text)
            return (1, text.lower(), text)
        return sorted(tokens, key=key_fn)

    value_lists = {k: _sort_tokens(v) for k, v in values.items()}

    groupby_options = ['subject']
    for candidate in ['run', 'session', 'task']:
        if candidate in entities:
            groupby_options.append(candidate)

    return jsonify({
        "entities": sorted(list(entities)),
        "groupby_options": groupby_options,
        "values": value_lists,
        "scanned_files": scanned
    })


@app.route('/get_fmriprep_spaces')
def get_fmriprep_spaces():
    """Get available spaces from fMRIPrep derivatives."""
    path = request.args.get('path')
    tasks = request.args.getlist('tasks')
    
    if not path or not os.path.isdir(path):
        return jsonify([])
    
    spaces = discover_spaces(Path(path), tasks if tasks else None)
    return jsonify(spaces)


@app.route('/get_subjects')
def get_subjects():
    """Get available subjects from config."""
    config_path = request.args.get('config', 'config/config.json')
    
    if not os.path.isfile(config_path):
        return jsonify([])
    
    try:
        config = load_config(config_path)
        subjects = discover_subjects(config)
        return jsonify(subjects)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/estimate_time', methods=['POST'])
def api_estimate_time():
    """Estimate processing time."""
    data = request.json
    config_path = data.get('config', 'config/config.json')
    actions = data.get('actions', ['smooth', 'stats'])
    
    try:
        config = load_config(config_path)
        subjects = config.SUBJECTS or discover_subjects(config)
        tasks = config.TASKS
        
        estimate = estimate_processing_time(subjects, actions, tasks)
        return jsonify(estimate)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/check_environment')
def api_check_environment():
    """Check MATLAB/container environment."""
    use_local = request.args.get('local', 'false').lower() == 'true'
    
    if use_local:
        caps = detect_matlab_environment()
        features = check_feature_availability(caps, using_container=False)
        return jsonify({
            "environment": caps.to_dict(),
            "features": {
                "smooth": features.smooth,
                "stats_subject": features.stats_subject,
                "stats_dataset": features.stats_dataset,
                "roi_analysis": features.roi_analysis,
                "custom_contrasts": features.custom_contrasts
            },
            "unavailable_reasons": features.unavailable_reasons
        })
    else:
        # Container check
        import shutil
        docker = shutil.which("docker") is not None
        apptainer = shutil.which("apptainer") is not None
        
        return jsonify({
            "docker_available": docker,
            "apptainer_available": apptainer,
            "all_features_available": docker or apptainer
        })


# =============================================================================
# Model Validation (delegate to core)
# =============================================================================

# Model Validation (delegate to core)
# =============================================================================

def _scan_bids_for_model(bids_dir: str) -> dict:
    """
    Scan a BIDS directory to extract tasks and trial_type levels.
    Returns a dict with keys: tasks (list), trial_types_by_task (dict).
    Mirrors what pybids auto_model() does, without the numpy 2.x incompatibility.
    """
    import re as _re
    bids_path = Path(bids_dir)
    tasks = []
    trial_types_by_task: dict = {}

    # Only scan subject func folders (ignores code/, derivatives/, etc.)
    all_evfiles = sorted(bids_path.glob('sub-*/ses-*/func/*_events.tsv')) + \
                  sorted(bids_path.glob('sub-*/func/*_events.tsv'))

    for evfile in all_evfiles:
        m = _re.search(r'task-([^_/]+)', evfile.name)
        if not m:
            continue
        task = m.group(1)
        if task not in tasks:
            tasks.append(task)
        try:
            with evfile.open(encoding='utf-8') as fh:
                reader = csv.DictReader(fh, delimiter='\t')
                for row in reader:
                    val = (row.get('trial_type') or '').strip()
                    if val and val != 'n/a':
                        trial_types_by_task.setdefault(task, set()).add(val)
        except Exception:
            pass

    # Deduplicate / sort
    for t in trial_types_by_task:
        trial_types_by_task[t] = sorted(trial_types_by_task[t])

    return {"tasks": tasks, "trial_types_by_task": trial_types_by_task}


def _build_default_model(tasks: list, trial_types_by_task: dict) -> dict:
    """
    Build a default BIDS stats model following the reference default model spec:
    https://bids-standard.github.io/stats-models/default_model.html
    One Run-level node per task, then a Subject-level and Dataset-level node.
    """
    nodes = []

    for task in tasks:
        conditions = trial_types_by_task.get(task, [])
        predictors = [f"trial_type.{c}" for c in conditions] if conditions else ["trial_type.condition_a"]
        predictors_with_intercept = predictors + [1]

        # One-vs-rest contrasts: each condition vs average of all others
        contrasts = []
        n = len(predictors)
        for i, pred in enumerate(predictors):
            cname = pred.replace("trial_type.", "")
            if n > 1:
                weights = [-1 / (n - 1) if j != i else 1 for j in range(n)]
            else:
                weights = [1]
            contrasts.append({
                "Name": cname,
                "ConditionList": predictors,
                "Weights": weights,
                "Test": "t"
            })

        node_name = f"run_level_{task}" if len(tasks) > 1 else "run_level"
        nodes.append({
            "Level": "Run",
            "Name": node_name,
            "GroupBy": ["run", "subject", "task"],
            "Model": {
                "Type": "glm",
                "X": predictors_with_intercept,
                "HRF": {
                    "Variables": predictors,
                    "Model": "spm"
                },
                "Options": {
                    "HighPassFilterCutoffHz": 0.0078,
                    "Mask": {"desc": ["brain"], "suffix": ["mask"]}
                },
                "Software": {"SPM": {"Version": 25}}
            },
            "Contrasts": contrasts
        })

    # Gather all run-level contrast names for subject level
    all_contrast_names = []
    for node in nodes:
        for c in node.get("Contrasts", []):
            if c["Name"] not in all_contrast_names:
                all_contrast_names.append(c["Name"])

    subject_contrasts = [
        {"Name": n, "ConditionList": [n], "Weights": [1], "Test": "t"}
        for n in all_contrast_names
    ]
    nodes.append({
        "Level": "Subject",
        "Name": "subject_level",
        "GroupBy": ["subject", "contrast"],
        "Model": {"Type": "glm", "X": all_contrast_names or ["contrast"]},
        "Contrasts": subject_contrasts
    })

    dataset_contrasts = [
        {"Name": n, "ConditionList": [n], "Weights": [1], "Test": "t"}
        for n in all_contrast_names
    ]
    nodes.append({
        "Level": "Dataset",
        "Name": "dataset_level",
        "GroupBy": ["contrast"],
        "Model": {"Type": "glm", "X": [1]},
        "Contrasts": dataset_contrasts
    })

    return {
        "Name": "default-model",
        "BIDSModelVersion": "1.0.0",
        "Description": "Default BIDS stats model – generated from dataset events files.",
        "Input": {"task": tasks},
        "Nodes": nodes
    }


@app.route('/api/model/create', methods=['POST'])
def api_model_create():
    """
    Create a BIDS stats model JSON file.
    If bids_dir is provided, scans its events files to build a default model
    (tasks + trial_type levels), mirroring pybids auto_model().
    Otherwise writes a minimal skeleton.
    """
    data = request.json or {}
    path = data.get('path', '').strip()
    bids_dir = data.get('bids_dir', '').strip()

    if not path:
        return jsonify({"success": False, "error": "No path provided"}), 400

    path = os.path.abspath(path)

    if os.path.exists(path) and not data.get('overwrite', False):
        return jsonify({"success": False, "error": "File already exists. Set overwrite=true to replace it."}), 409

    try:
        if bids_dir and os.path.isdir(bids_dir):
            scan = _scan_bids_for_model(bids_dir)
            model = _build_default_model(scan["tasks"], scan["trial_types_by_task"])
            source = "bids_scan"
        else:
            # Minimal skeleton when no BIDS dir is available
            model = _build_default_model([], {})
            source = "skeleton"

        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(model, f, indent=2)
            f.write('\n')
        return jsonify({"success": True, "path": path, "source": source,
                        "tasks": model["Input"].get("task", [])})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/validate_model', methods=['POST'])
def api_validate_model():
    """Validate BIDS stats model using core module."""
    data = request.json
    content = data.get('content')
    
    if not content:
        return jsonify({"valid": False, "error": "No content provided"}), 400
    
    # Write to temp file for validation
    temp_path = Path(f"config/temp_model_{secrets.token_hex(4)}.json")
    
    try:
        with open(temp_path, 'w') as f:
            json.dump(content, f)
        
        result = validate_bids_model(temp_path)
        return jsonify(result)
    finally:
        if temp_path.exists():
            temp_path.unlink()


@app.route('/get_model_tasks')
def get_model_tasks():
    """Get tasks defined in a model file."""
    path = request.args.get('path')
    if not path or not os.path.isfile(path):
        return jsonify({"error": "Invalid file path"})
    
    try:
        with open(path, 'r') as f:
            data = json.load(f)
            tasks = data.get('Input', {}).get('task', [])
            return jsonify({"tasks": tasks})
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route('/api/model_hints', methods=['POST'])
def api_model_hints():
    """Return inline hints for model editing based on BIDS data and model content."""
    data = request.json or {}
    model_content = data.get('model_content')
    model_path = data.get('model_path')
    bids_dir = data.get('bids_dir', '')
    fmriprep_dir = data.get('fmriprep_dir', '')

    if model_content is None and model_path:
        if not os.path.isfile(model_path):
            return jsonify({"error": f"Model file not found: {model_path}"}), 400
        try:
            with open(model_path, 'r', encoding='utf-8') as f:
                model_content = json.load(f)
        except Exception as e:
            return jsonify({"error": f"Failed to parse model file: {str(e)}"}), 400

    if model_content is None:
        return jsonify({"error": "No model content provided"}), 400

    if not isinstance(model_content, dict):
        return jsonify({"error": "Model content must be a JSON object"}), 400

    model_hints = _extract_model_hints(model_content)

    bids_tasks = []
    event_info = {"files_scanned": 0, "event_columns": [], "sample_values": {}}
    confound_info = {
        "files_scanned": 0,
        "columns": [],
        "trans_rot_present": [],
        "sample_status": "missing-dir"
    }
    if bids_dir and os.path.isdir(bids_dir):
        bids_tasks = discover_tasks(Path(bids_dir))
        event_info = _discover_event_info(Path(bids_dir), model_hints.get('model_tasks', []))
        if event_info.get('files_scanned', 0) == 0:
            return jsonify({
                "error": "No BIDS *_events.tsv files found in BIDS folder. Event files are required."
            }), 400

    if fmriprep_dir and os.path.isdir(fmriprep_dir):
        confound_info = _discover_confound_info(Path(fmriprep_dir), model_hints.get('model_tasks', []))

    warnings = _build_model_warnings(model_hints, bids_tasks, event_info)

    return jsonify({
        "model": model_hints,
        "dataset": {
            "bids_tasks": bids_tasks,
            "events": event_info,
            "confounds": confound_info
        },
        "warnings": warnings,
        "ok": len(warnings) == 0
    })


# =============================================================================
# Configuration Endpoints
# =============================================================================

@app.route('/load_config_file')
def load_config_file():
    """Load configuration file."""
    path = request.args.get('path', 'config/config.json')
    
    if not os.path.exists(path):
        return jsonify({
            "WD": "", "BIDS_DIR": "", "DERIVATIVES_DIR": "", "FMRIPREP_DIR": "",
            "SPACE": "MNI152NLin2009cAsym", "FWHM": 6, "MODELS_FILE": "",
            "TASKS": [], "VERBOSITY": 3, "container_type": "apptainer",
            "docker_image": "",
            "apptainer_image": "/data/local/container/bidspm/bidspm_4.0.0.sif"
        })
    
    with open(path, 'r') as f:
        return jsonify(json.load(f))


@app.route('/save_settings', methods=['POST'])
def save_settings():
    """Save configuration to file."""
    data = request.json
    filepath = data.get('filepath', 'config/config.json')
    content = data.get('content')
    
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    
    with open(filepath, 'w') as f:
        json.dump(content, f, indent=4)
    
    return jsonify({"status": "success", "path": filepath})


@app.route('/validate_config', methods=['POST'])
def validate_config():
    """Validate configuration against schema."""
    data = request.json
    content = data.get('content')
    schema_path = 'config/config_schema.json'
    
    if not os.path.exists(schema_path):
        return jsonify({"valid": False, "error": "Schema file not found"}), 404
    
    temp_path = f"config/temp_val_{secrets.token_hex(4)}.json"
    
    try:
        with open(temp_path, 'w') as f:
            json.dump(content, f)
        
        from docs.json_validator import JSONValidator
        is_valid = JSONValidator.validate_with_schema(temp_path, schema_path)
        
        if is_valid:
            return jsonify({"valid": True})
        else:
            return jsonify({"valid": False, "error": "Validation failed"})
    except Exception as e:
        return jsonify({"valid": False, "error": str(e)})
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.route('/check_paths', methods=['POST'])
def check_paths():
    """Check if configuration paths exist."""
    data = request.json
    results = {}
    
    for key in ['WD', 'BIDS_DIR', 'DERIVATIVES_DIR', 'FMRIPREP_DIR', 'MODELS_FILE']:
        path = data.get(key)
        if path:
            results[key] = os.path.exists(path)
        elif key == 'MODELS_FILE':
            results[key] = True  # Empty is allowed
    
    return jsonify(results)


@app.route('/get_schema')
def get_schema():
    """Get configuration schema."""
    schema_path = 'config/config_schema.json'
    if os.path.exists(schema_path):
        with open(schema_path, 'r') as f:
            return jsonify(json.load(f))
    return jsonify({})


# =============================================================================
# Container Configuration
# =============================================================================

@app.route('/load_container_file')
def load_container_file():
    """Load container configuration."""
    path = request.args.get('path', 'containers/container.json')
    
    if not os.path.exists(path):
        return jsonify({
            "container_type": "apptainer",
            "docker_image": "",
            "apptainer_image": "/data/local/container/bidspm/bidspm_4.0.0.sif"
        })
    
    with open(path, 'r') as f:
        return jsonify(json.load(f))


# =============================================================================
# File System Browsing
# =============================================================================

@app.route('/browse')
def browse_fs():
    """Browse filesystem for file/directory selection."""
    path = _resolve_fs_path(request.args.get('path', '')) or os.getcwd()
    only_dirs = request.args.get('only_dirs', 'false').lower() == 'true'
    extensions_raw = (request.args.get('extensions', '') or '').strip()
    allowed_extensions = None
    if extensions_raw:
        parsed = [e.strip().lower() for e in extensions_raw.split(',') if e.strip()]
        normalized = [e if e.startswith('.') else f'.{e}' for e in parsed]
        if normalized:
            allowed_extensions = tuple(normalized)
    
    if not os.path.exists(path):
        path = os.getcwd()
    elif os.path.isfile(path):
        path = os.path.dirname(os.path.abspath(path)) or os.getcwd()
    
    try:
        items = []
        parent = os.path.dirname(os.path.abspath(path))
        items.append({'name': '..', 'path': parent, 'type': 'dir'})
        
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_dir():
                    items.append({'name': entry.name, 'path': entry.path, 'type': 'dir'})
                elif not only_dirs:
                    entry_name_lc = entry.name.lower()
                    if allowed_extensions:
                        if entry_name_lc.endswith(allowed_extensions):
                            items.append({'name': entry.name, 'path': entry.path, 'type': 'file'})
                    elif entry_name_lc.endswith(('.json', '.sif')):
                        items.append({'name': entry.name, 'path': entry.path, 'type': 'file'})
        
        items.sort(key=lambda x: (x['type'] != 'dir', x['name'].lower()))
        return jsonify({'current_path': os.path.abspath(path), 'items': items})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/file_content')
def file_content():
    """Get content of a file."""
    path = request.args.get('path')
    if not path or not os.path.isfile(path):
        return "File not found", 404
    
    try:
        with open(path, 'r') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}", 500


@app.route('/file_content', methods=['POST'])
def save_file_content():
    """Save content to a file (used by in-browser model editor)."""
    data = request.json or {}
    path = data.get('path')
    content = data.get('content', '')
    validate_json = data.get('validate_json', False)

    if not path:
        return jsonify({"success": False, "error": "No file path provided"}), 400

    if _is_inside_bids_dir(path):
        return jsonify({"success": False, "error": "Writing inside the BIDS folder is not allowed."}), 403

    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

        if validate_json:
            parsed = json.loads(content)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(parsed, f, indent=2)
                f.write('\n')
        else:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)

        return jsonify({"success": True, "path": path})
    except json.JSONDecodeError as e:
        return jsonify({"success": False, "error": f"Invalid JSON: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/mkdir', methods=['POST'])
def create_directory():
    """Create a directory."""
    data = request.json
    path = data.get('path')
    
    if not path:
        return jsonify({"success": False, "error": "No path provided"}), 400

    if _is_inside_bids_dir(path):
        return jsonify({"success": False, "error": "Creating directories inside the BIDS folder is not allowed."}), 403
    
    try:
        os.makedirs(path, exist_ok=True)
        return jsonify({"success": True, "path": path})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# Legacy/Compatibility Endpoints
# =============================================================================

@app.route('/save_config', methods=['POST'])
def save_config():
    """Save configuration (legacy endpoint)."""
    data = request.json
    config_data = data.get('config')
    folder = data.get('folder', 'configs')
    filename = data.get('filename', f"config_{int(time.time())}.json")
    
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    
    with open(filepath, 'w') as f:
        json.dump(config_data, f, indent=4)
    
    return jsonify({"status": "saved", "path": filepath})


@app.route('/configs')
def list_configs():
    """List configuration files."""
    folder = request.args.get('folder', 'configs')
    
    if not os.path.exists(folder):
        return jsonify([])
    
    try:
        files = [f for f in os.listdir(folder) if f.endswith('.json')]
        return jsonify(files)
    except Exception:
        return jsonify([])


@app.route('/load_config')
def api_load_config():
    """Load configuration (legacy endpoint)."""
    folder = request.args.get('folder', 'configs')
    filename = request.args.get('filename')
    
    if not filename:
        return jsonify({"error": "No filename provided"}), 400
    
    filepath = os.path.join(folder, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    
    with open(filepath, 'r') as f:
        return jsonify(json.load(f))


# =============================================================================
# Transformer Builder API
# =============================================================================

@app.route('/api/scan_events_columns', methods=['POST'])
def api_scan_events_columns():
    """Scan a BIDS directory for events files and extract column names."""
    try:
        data = request.json or {}
        bids_dir = data.get('bids_dir', '').strip().strip('"\'')
        events_file = data.get('events_file', '').strip().strip('"\'')
        preview_file = data.get('preview_file', '').strip()
        preview_max_rows = data.get('preview_max_rows', 200)

        # preview_max_rows: 0 means "all rows"
        try:
            preview_max_rows = int(preview_max_rows)
            if preview_max_rows < 0:
                preview_max_rows = 200
        except (TypeError, ValueError):
            preview_max_rows = 200

        if events_file:
            events_file = _resolve_fs_path(events_file)

        if bids_dir:
            bids_dir = _resolve_fs_path(bids_dir)
            if not os.path.isdir(bids_dir):
                return jsonify({"error": f"Directory not found: {bids_dir}"}), 404
        elif events_file:
            bids_dir = os.path.dirname(os.path.abspath(events_file)) or str(APP_ROOT)
        else:
            return jsonify({"error": "No BIDS directory or events file specified"}), 400

        if events_file:
            if not os.path.isfile(events_file):
                return jsonify({"error": f"Events file not found: {events_file}"}), 404
            if not events_file.lower().endswith('.tsv'):
                return jsonify({"error": "Selected file must be a .tsv file"}), 400

        events_files = []
        tasks = set()
        all_columns = set()
        columns_by_type = {}

        if events_file:
            events_files = [events_file]
            file_name = os.path.basename(events_file)
            parts = file_name.split('_')
            for part in parts:
                if part.startswith('task-'):
                    tasks.add(part[5:])
        else:
            for root, _dirs, files in os.walk(bids_dir):
                for file_name in files:
                    if file_name.endswith('_events.tsv'):
                        events_files.append(os.path.join(root, file_name))
                        parts = file_name.split('_')
                        for part in parts:
                            if part.startswith('task-'):
                                tasks.add(part[5:])

        # Read columns from a subset to keep scanning responsive.
        for path in events_files[:5]:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f, delimiter='\t')
                    if reader.fieldnames:
                        for col in reader.fieldnames:
                            all_columns.add(col)
                            if col in ['trial_type', 'condition', 'response', 'accuracy']:
                                columns_by_type.setdefault(col, [])

                            f.seek(0)
                            reader = csv.DictReader(f, delimiter='\t')
                            values = set()
                            for row in reader:
                                val = row.get(col, '').strip()
                                if val and val != 'n/a':
                                    values.add(val)
                            if values and col not in ['onset', 'duration', 'framewise_displacement']:
                                if col not in columns_by_type:
                                    columns_by_type[col] = []
                                columns_by_type[col] = sorted(list(values))[:10]
            except Exception:
                continue

        sample_file = None
        sample_headers = []
        sample_rows = []
        sample_total_rows = 0
        sample_truncated = False
        if events_files:
            candidate_files = events_files[:]
            random.shuffle(candidate_files)

            if preview_file:
                if os.path.isabs(preview_file):
                    preview_abs = os.path.normpath(preview_file)
                else:
                    preview_abs = os.path.normpath(os.path.join(bids_dir, preview_file))
                if preview_abs in events_files:
                    candidate_files = [preview_abs] + [f for f in candidate_files if f != preview_abs]

            for chosen in candidate_files:
                try:
                    with open(chosen, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f, delimiter='\t')
                        headers = list(reader.fieldnames or [])
                        if not headers:
                            continue

                        rows = []
                        total_rows = 0
                        for row in reader:
                            total_rows += 1
                            if preview_max_rows == 0 or len(rows) < preview_max_rows:
                                rows.append([row.get(h, '') for h in headers])

                        try:
                            bids_root = os.path.abspath(bids_dir)
                            chosen_abs = os.path.abspath(chosen)
                            if os.path.commonpath([bids_root, chosen_abs]) == bids_root:
                                sample_file = os.path.relpath(chosen_abs, bids_root)
                            else:
                                sample_file = chosen_abs
                        except Exception:
                            sample_file = os.path.abspath(chosen)

                        sample_headers = headers
                        sample_rows = rows
                        sample_total_rows = total_rows
                        sample_truncated = preview_max_rows != 0 and total_rows > len(rows)
                        break
                except Exception:
                    continue

        return jsonify({
            "bids_dir": bids_dir,
            "events_files": len(events_files),
            "columns": sorted(list(all_columns)),
            "columns_by_type": {k: v for k, v in columns_by_type.items()},
            "tasks": sorted(list(tasks)),
            "sample_file": sample_file,
            "sample_headers": sample_headers,
            "sample_rows": sample_rows,
            "sample_total_rows": sample_total_rows,
            "sample_truncated": sample_truncated
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
    import webbrowser
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
    print(f"🌐 Starting BIDSPM Web Interface v{__version__}")
    print(f"🔗 URL: {url}")
    print("💡 Press Ctrl+C to stop the server")
    print()
    print(f"🚀 Running with Waitress server on 0.0.0.0:{port}")

    # In VS Code Remote or headless SSH sessions, browser auto-open often fires
    # before local port forwarding is ready, which can surface as an empty page
    # or connection-refused tab in the user's browser.
    skip_browser_open, skip_reason = should_skip_browser_auto_open()

    if not args.no_browser:
        if skip_browser_open:
            print()
            print(f"📌 Browser auto-open skipped: {skip_reason}.")
            print("   → Open the forwarded port from VS Code once the tunnel is ready,")
            print(f"     or open manually: {url}")
        else:
            def open_browser():
                if wait_for_http_ready(url):
                    webbrowser.open(url)
                    print("✅ Browser opened automatically")
                else:
                    print(f"⚠️  Server did not become ready within the browser-open timeout. Open manually: {url}")

            threading.Timer(1, open_browser).start()

    serve(app, host='0.0.0.0', port=port, threads=10)
