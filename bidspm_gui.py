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
import sys
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
    check_subject_processed,
    validate_bids_model, estimate_processing_time,
    load_config
)
from lib.config import auto_select_container_config
from lib.project_manager import project_manager, GLOBAL_LOG_DIR
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

def resolve_python_executable() -> str:
    """Resolve which Python interpreter to launch bidspm.py subprocesses with.

    Priority:
      1. ``$BIDSPM_PYTHON`` env var, if it points at a real file -- explicit
         override for unusual setups.
      2. ``.bidspm/bin/python`` (the intended project venv), if it actually
         resolves -- a dangling symlink here (e.g. pointing at a since-moved
         system Python) must NOT be silently accepted.
      3. ``sys.executable`` -- the interpreter currently running this server.
         It is guaranteed to have every required dependency (flask,
         jsonschema, bsmschema, ...) since it already imported them to get
         this far, unlike a blind ``'python3'`` PATH lookup which could
         resolve to an unrelated, dependency-less interpreter.
      4. ``'python3'`` on PATH, only if ``sys.executable`` is somehow empty.
    """
    env_override = os.environ.get("BIDSPM_PYTHON", "").strip()
    if env_override and os.path.exists(env_override):
        return env_override

    venv_python = os.path.abspath(".bidspm/bin/python")
    if os.path.exists(venv_python):
        return venv_python

    return sys.executable or "python3"


# Execution state
BIDSPM_SCRIPT = os.path.abspath("bidspm.py")
PYTHON_EXE = resolve_python_executable()
LOG_DIR = GLOBAL_LOG_DIR  # fallback when no project is selected; per-project runs use project_manager
DEFAULT_PORT = 5100
APP_ROOT = Path(__file__).resolve().parent

MAX_EXECUTIONS = 50  # Cleanup threshold
execution_registry = ExecutionRegistry(
    get_project_manager=lambda: project_manager,
    log_dir=LOG_DIR,
    max_executions=MAX_EXECUTIONS,
)


def static_version(relative_path: str) -> str:
    """Cache-busting token for a static asset, derived from its mtime.

    Editing a JS/CSS file changes this automatically. Templates used to
    embed a hand-typed ``v='YYYYMMDDx'`` per <script> tag -- forgetting to
    bump it on edit meant browsers kept serving stale cached JS (a suspected
    cause of the recurring "blank page after update" reports).
    """
    asset_path = APP_ROOT / 'static' / relative_path
    try:
        return str(int(asset_path.stat().st_mtime))
    except OSError:
        return '0'


app.jinja_env.globals['static_version'] = static_version


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
            # Surfaces which interpreter run subprocesses use -- a dangling
            # .bidspm/bin/python symlink silently falling back to some other
            # python3 used to be invisible until a run failed with a
            # confusing ModuleNotFoundError deep in a log file.
            'label': f'Python interpreter ({PYTHON_EXE})',
            'ready': os.path.isfile(PYTHON_EXE),
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
    """Wait for the server URL to respond, then open it via $BROWSER / webbrowser.

    Under VS Code Remote SSH, $BROWSER points to browser.sh which calls
    `code --openExternal <url>` — this forwards the URL to the Mac client and
    opens it in the system browser (Safari).  We must NOT call xdg-open or any
    other Linux-native launcher first, because they silently do nothing on a
    headless server yet report success, preventing the VS Code path from running.
    """
    if not wait_for_http_ready(url):
        return False, f"Server did not become ready within the browser-open timeout. Open manually: {url}"

    import webbrowser
    try:
        opened = webbrowser.open(url)
    except Exception as exc:
        return False, f"Unable to open browser automatically ({exc}). Open manually: {url}"

    if opened:
        return True, 'Browser opened automatically'

    return False, f"Browser launch was requested but no browser handler confirmed the open. Open manually: {url}"


def _pids_listening_on_port(port: int) -> List[int]:
    """Return PIDs listening on the given TCP port (Linux and macOS)."""
    import sys
    try:
        if sys.platform == "darwin":
            # macOS: ss is not available, use lsof
            result = subprocess.run(
                ['lsof', '-ti', f'tcp:{port}'],
                capture_output=True, text=True, check=False
            )
            return sorted({int(p) for p in result.stdout.split() if p.strip().isdigit()})
        else:
            result = subprocess.run(
                ['ss', '-tlnp', f'sport = :{port}'],
                capture_output=True, text=True, check=False
            )
            return sorted({int(pid) for pid in re.findall(r'pid=(\d+)', result.stdout)})
    except Exception:
        return []


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
    check_subject_processed=check_subject_processed,
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
    print(f"\n  👉  Open in browser: {url}\n")

    # Auto-open the browser unless suppressed.
    # Skip on VS Code Remote SSH — the tunnel intercepts localhost URLs and
    # would open a stripped-down WebView instead of a real browser.
    _in_remote_ssh = bool(os.environ.get("SSH_CLIENT") or os.environ.get("SSH_TTY"))
    if not args.no_browser and not _in_remote_ssh:
        import sys as _sys
        import threading as _threading
        def _open_browser():
            if not wait_for_http_ready(url):
                return
            try:
                if _sys.platform == "darwin":
                    subprocess.run(["open", url], check=False)
                else:
                    import webbrowser
                    webbrowser.open(url)
            except Exception:
                pass
        _threading.Thread(target=_open_browser, daemon=True).start()

    serve(app, host='0.0.0.0', port=port, threads=10)
