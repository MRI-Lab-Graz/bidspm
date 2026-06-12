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
import shlex
import shutil
import urllib.request
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
from webapp.web_config_fs_api import register_config_fs_routes
from webapp.web_discovery_model_api import (
    _build_model_warnings,
    _discover_confound_info,
    _discover_event_info,
    _discover_participants_info,
    _extract_model_hints,
    register_discovery_model_routes,
)
from webapp.web_execution_api import ExecutionRegistry, register_execution_routes
from webapp.web_pages import register_page_routes
from webapp.web_projects_api import register_project_routes
from webapp.web_utility_stats_api import register_utility_stats_routes


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
    """Wait for the server URL to respond, then try to open it in a browser.

    When running under VS Code Remote SSH the $BROWSER env var points to VS Code's
    browser.sh helper, which opens URLs in the Simple Browser panel rather than in
    Firefox.  Simple Browser is too restricted for a full Flask app (it renders
    blank), so we prefer a real browser (Firefox) and fall back to webbrowser.open
    only if no real browser is found.
    """
    if not wait_for_http_ready(url):
        return False, f"Server did not become ready within the browser-open timeout. Open manually: {url}"

    # Prefer a real browser; avoid the VS Code browser.sh wrapper.
    for browser_cmd in ('firefox', 'chromium-browser', 'google-chrome', 'xdg-open'):
        if shutil.which(browser_cmd):
            try:
                vscode_browser = os.environ.get('BROWSER', '')
                env = {**os.environ}
                if 'vscode' in vscode_browser.lower() or 'code' in vscode_browser.lower():
                    env.pop('BROWSER', None)   # let the real browser take over
                subprocess.Popen([browser_cmd, url], env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, f'Browser opened automatically ({browser_cmd})'
            except Exception:
                continue

    import webbrowser
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
