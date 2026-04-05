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

# Store running executions (with periodic cleanup)
executions: Dict[str, Dict[str, Any]] = {}
current_execution_id: Optional[str] = None
current_project_id: Optional[str] = None
MAX_EXECUTIONS = 50  # Cleanup threshold


# =============================================================================
# Utility Functions
# =============================================================================

def find_free_port(start_port: int = 5000, max_tries: int = 100) -> Optional[int]:
    """Find an available port."""
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('0.0.0.0', port))
                return port
            except socket.error:
                continue
    return None


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
def index():
    """Redirect to projects page."""
    return redirect(url_for('projects_page'))


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


# =============================================================================
# Utility API Endpoints
# =============================================================================

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
            event_files = list(bids_path.glob('**/*_events.tsv'))
            if event_files:
                results['events'] = {'status': 'ok', 'message': f'{len(event_files)} event files found', 'value': str(len(event_files))}
            else:
                results['events'] = {'status': 'warning', 'message': 'No event files found'}
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
    
    data = request.json
    actions = data.get('actions', [])
    project_id = data.get('project_id')
    
    if not actions:
        return jsonify({"error": "No actions selected"}), 400
    
    execution_id = secrets.token_hex(8)
    current_project_id = project_id
    
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
    
    executions[execution_id] = {
        'command': command,
        'output': [],
        'finished': False,
        'process': None,
        'start_time': time.time(),
        'project_id': project_id
    }

    def execute():
        global current_execution_id
        current_execution_id = execution_id
        
        # Use project-specific log directory if available
        if project_id:
            log_dir = project_manager.get_project_logs_dir(project_id)
            log_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_filename = f"run_{timestamp}.log"
            log_file = log_dir / log_filename
        else:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_file = LOG_DIR / "web_run.log"
            log_filename = "web_run.log"
        
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            start_new_session=True,
            env=env
        )
        executions[execution_id]['process'] = process
        executions[execution_id]['log_file'] = str(log_file)

        msg = f"[{datetime.now().isoformat()}] Executing: {' '.join(command)}\n"
        executions[execution_id]['output'].append(msg)
        
        with open(log_file, "a") as log:
            log.write(f"\n{'='*80}\n")
            log.write(msg)
            log.write(f"{'='*80}\n\n")

        try:
            for line in process.stdout:
                executions[execution_id]['output'].append(line)
                with open(log_file, "a") as log:
                    log.write(line)
        except Exception as e:
            error_msg = f"\nError reading output: {str(e)}\n"
            executions[execution_id]['output'].append(error_msg)

        process.wait()
        finish_msg = f"\n[{datetime.now().isoformat()}] Process finished with exit code {process.returncode}\n"
        executions[execution_id]['output'].append(finish_msg)
        executions[execution_id]['finished'] = True
        executions[execution_id]['return_code'] = process.returncode
        
        with open(log_file, "a") as log:
            log.write(finish_msg)
        
        # Update project's last log reference
        if project_id:
            project_manager.update_project_log(project_id, log_filename)

    thread = threading.Thread(target=execute, daemon=True)
    thread.start()

    return jsonify({
        "execution_id": execution_id,
        "project_id": project_id
    })


@app.route('/stream/<execution_id>')
def stream_output(execution_id: str):
    """Stream execution output to client via SSE."""
    def generate():
        if execution_id not in executions:
            yield "data: Error: Execution not found\n\n"
            return

        idx = 0
        while True:
            if idx < len(executions[execution_id]['output']):
                line = executions[execution_id]['output'][idx]
                line = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', ' ', line)
                line = line.rstrip("\n")
                yield f"data: {line}\n\n"
                idx += 1
            elif executions[execution_id]['finished']:
                break
            else:
                time.sleep(0.05)
                
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
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGINT)
                time.sleep(1)
                if proc.poll() is None:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
            except Exception:
                proc.terminate()
                if proc.poll() is None:
                    proc.kill()
        
        exec_info['output'].append("\n--- Execution stopped by user ---\n")
        exec_info['finished'] = True
        return jsonify({"status": "stopped"})
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
            "TASKS": [], "VERBOSITY": 3, "container_type": "local"
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
            "container_type": "local",
            "docker_image": "bidspm/bidspm:latest",
            "apptainer_image": ""
        })
    
    with open(path, 'r') as f:
        return jsonify(json.load(f))


# =============================================================================
# File System Browsing
# =============================================================================

@app.route('/browse')
def browse_fs():
    """Browse filesystem for file/directory selection."""
    path = request.args.get('path', os.getcwd())
    only_dirs = request.args.get('only_dirs', 'false').lower() == 'true'
    
    if not os.path.exists(path):
        path = os.getcwd()
    
    try:
        items = []
        parent = os.path.dirname(os.path.abspath(path))
        items.append({'name': '..', 'path': parent, 'type': 'dir'})
        
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_dir():
                    items.append({'name': entry.name, 'path': entry.path, 'type': 'dir'})
                elif not only_dirs:
                    if entry.name.endswith(('.json', '.sif')):
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


@app.route('/mkdir', methods=['POST'])
def create_directory():
    """Create a directory."""
    data = request.json
    path = data.get('path')
    
    if not path:
        return jsonify({"success": False, "error": "No path provided"}), 400
    
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
                       help='Port to use (default: auto-select starting from 5000)')
    args = parser.parse_args()
    
    if args.port:
        port = args.port
    else:
        port = find_free_port(5000)
    
    if not port:
        print("Error: Could not find a free port.")
        import sys
        sys.exit(1)
    
    print(f"\n{'='*50}")
    print(f"🚀 BIDSPM Web Interface")
    print(f"{'='*50}")
    print(f"   Local:   http://localhost:{port}")
    print(f"   Network: http://0.0.0.0:{port}")
    print(f"{'='*50}\n")
    
    serve(app, host='0.0.0.0', port=port, threads=10)
