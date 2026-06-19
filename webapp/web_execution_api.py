import json
import os
import re
import secrets
import shlex
import signal
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from flask import Flask, Response, jsonify, request, stream_with_context


ProjectManagerGetter = Callable[[], object]
NormalizeSubjects = Callable[[object], list[str]]
ValidateModel = Callable[[Path], dict]


class ExecutionRegistry:
    def __init__(self, get_project_manager: ProjectManagerGetter, log_dir: Path, max_executions: int = 50) -> None:
        self.get_project_manager = get_project_manager
        self.log_dir = Path(log_dir)
        self.max_executions = max_executions
        self.executions: dict[str, dict] = {}
        self.current_execution_id: Optional[str] = None
        self.current_project_id: Optional[str] = None

    def cleanup_old_executions(self) -> None:
        if len(self.executions) <= self.max_executions:
            return

        finished = [(execution_id, execution) for execution_id, execution in self.executions.items() if execution.get('finished')]
        finished.sort(key=lambda item: item[1].get('start_time', 0))
        to_remove = len(self.executions) - self.max_executions
        for execution_id, _ in finished[:to_remove]:
            del self.executions[execution_id]

    def execution_log_location(self, project_id: Optional[str], execution_id: str) -> tuple[Path, str]:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        if project_id:
            log_dir = self.get_project_manager().get_project_logs_dir(project_id)
            log_dir.mkdir(parents=True, exist_ok=True)
            log_filename = f'run_{timestamp}_{execution_id[:8]}.log'
            return log_dir / log_filename, log_filename

        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_filename = f'web_run_{timestamp}_{execution_id[:8]}.log'
        return self.log_dir / log_filename, log_filename

    @staticmethod
    def append_execution_log(log_file: Path, message: str) -> None:
        with open(log_file, 'a', encoding='utf-8') as log_handle:
            log_handle.write(message)
            log_handle.flush()

    @staticmethod
    def sanitize_sse_line(line: str) -> str:
        return re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', ' ', line).rstrip('\n')

    def finalize_execution(self, execution_id: str, return_code: int) -> None:
        execution = self.executions.get(execution_id)
        if not execution or execution.get('finished'):
            return

        finish_message = f"\n[{datetime.now().isoformat()}] Process finished with exit code {return_code}\n"
        self.append_execution_log(Path(execution['log_file']), finish_message)

        execution['finished'] = True
        execution['return_code'] = return_code
        execution['process'] = None

        project_id = execution.get('project_id')
        log_filename = execution.get('log_filename')
        if project_id and log_filename:
            self.get_project_manager().update_project_log(project_id, log_filename)

        if self.current_execution_id == execution_id:
            self.current_execution_id = None

    def monitor_execution(self, execution_id: str, process: subprocess.Popen) -> None:
        try:
            return_code = process.wait()
        except Exception:
            return_code = -1
        self.finalize_execution(execution_id, return_code)


def register_execution_routes(
    app: Flask,
    execution_registry: ExecutionRegistry,
    get_project_manager: ProjectManagerGetter,
    normalize_subject_ids: NormalizeSubjects,
    validate_bids_model: ValidateModel,
    bidspm_script: str,
    python_exe_path: str,
) -> None:
    @app.route('/run', methods=['POST'])
    def run_bidspm():
        data = request.json or {}
        actions = data.get('actions', [])
        project_id = data.get('project_id')
        subjects_override = normalize_subject_ids(data.get('subjects_override')) if 'subjects_override' in data else []

        if not actions:
            return jsonify({'error': 'No actions selected'}), 400

        execution_id = secrets.token_hex(8)
        execution_registry.current_project_id = project_id
        project_manager = get_project_manager()

        if project_id:
            project = project_manager.load_project(project_id)
            if not project:
                return jsonify({'error': 'Project not found'}), 404

            if not data.get('settings'):
                configs_dir = project_manager.get_project_configs_dir(project_id)
                configs_dir.mkdir(parents=True, exist_ok=True)
                run_cfg_path = configs_dir / f'run_settings_{execution_id}.json'

                export_cfg = project_manager.export_config(project_id, format='bidspm') or {}
                if subjects_override:
                    export_cfg['SUBJECTS'] = subjects_override
                with open(run_cfg_path, 'w', encoding='utf-8') as file_handle:
                    json.dump(export_cfg, file_handle, indent=2)
                    file_handle.write('\n')

                data['settings'] = str(run_cfg_path)

            if not data.get('model') and project.config.models_file:
                data['model'] = project.config.models_file

        if subjects_override and data.get('settings'):
            settings_path = str(data.get('settings')).strip()
            if not os.path.isfile(settings_path):
                return jsonify({'error': f'Settings file not found: {settings_path}'}), 400

            try:
                with open(settings_path, 'r', encoding='utf-8') as stream:
                    run_config = json.load(stream)
            except Exception as exc:
                return jsonify({'error': f'Failed to read settings file: {exc}'}), 400

            run_config['SUBJECTS'] = subjects_override
            override_path = Path('config') / f'run_settings_override_{execution_id}.json'
            override_path.parent.mkdir(parents=True, exist_ok=True)
            with open(override_path, 'w', encoding='utf-8') as stream:
                json.dump(run_config, stream, indent=2)
                stream.write('\n')
            data['settings'] = str(override_path)

        model_file = data.get('model')
        if model_file and any('stats' in action.lower() for action in actions):
            if not data.get('skip_validation'):
                if not os.path.isfile(model_file):
                    return jsonify({'error': f'Model file not found: {model_file}'}), 400

                result = validate_bids_model(Path(model_file))
                if not result['valid']:
                    return jsonify({'error': f"Model validation failed: {result.get('error', 'Unknown error')}"}), 400

        python_exe = python_exe_path if os.path.exists(python_exe_path) else 'python3'
        command = [python_exe, bidspm_script]
        command.extend(['--action'] + actions)

        if data.get('settings'):
            command.extend(['--settings', data.get('settings')])
        if data.get('container'):
            command.extend(['--container', data.get('container')])
        if data.get('model'):
            command.extend(['--model', data.get('model')])
        if data.get('node_name'):
            command.extend(['--node-name', data.get('node_name')])
        if data.get('pilot'):
            command.append('--pilot')
        if data.get('skip_validation'):
            command.append('--skip-modelvalidation')
        if data.get('local'):
            command.append('--local')
        if data.get('force'):
            command.append('--force')
        if data.get('stats_workers'):
            command.extend(['--stats-workers', str(data.get('stats_workers'))])

        execution_registry.cleanup_old_executions()

        log_file, log_filename = execution_registry.execution_log_location(project_id, execution_id)
        command_display = shlex.join(command)

        execution_registry.executions[execution_id] = {
            'command': command,
            'finished': False,
            'process': None,
            'start_time': time.time(),
            'project_id': project_id,
            'log_file': str(log_file),
            'log_filename': log_filename,
            'return_code': None,
            'stop_requested': False,
            'pid': None,
        }
        execution_registry.current_execution_id = execution_id

        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        header = (
            f"\n{'=' * 80}\n"
            f"[{datetime.now().isoformat()}] Executing (detached via nohup): {command_display}\n"
            f"Log file: {log_file}\n"
            f"{'=' * 80}\n\n"
        )

        try:
            with open(log_file, 'a', encoding='utf-8', buffering=1) as log_handle:
                log_handle.write(header)
                log_handle.flush()
                process = subprocess.Popen(
                    ['nohup'] + command,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env=env,
                    text=True,
                )
        except Exception as exc:
            execution_registry.executions[execution_id]['finished'] = True
            execution_registry.append_execution_log(
                log_file,
                f"[{datetime.now().isoformat()}] Failed to start execution: {exc}\n",
            )
            return jsonify({'error': f'Failed to start execution: {exc}'}), 500

        execution_registry.executions[execution_id]['process'] = process
        execution_registry.executions[execution_id]['pid'] = process.pid
        threading.Thread(
            target=execution_registry.monitor_execution,
            args=(execution_id, process),
            daemon=True,
        ).start()

        return jsonify({
            'execution_id': execution_id,
            'project_id': project_id,
            'log_file': str(log_file),
            'log_filename': log_filename,
            'pid': process.pid,
        })

    @app.route('/stream/<execution_id>')
    def stream_output(execution_id: str):
        def generate():
            if execution_id not in execution_registry.executions:
                yield 'data: Error: Execution not found\n\n'
                return

            exec_info = execution_registry.executions[execution_id]
            log_file = Path(exec_info.get('log_file', ''))
            offset = 0
            keepalive_at = time.time()

            while True:
                emitted = False
                if log_file.exists():
                    try:
                        with open(log_file, 'r', encoding='utf-8', errors='replace') as log_handle:
                            log_handle.seek(offset)
                            while True:
                                line = log_handle.readline()
                                if not line:
                                    offset = log_handle.tell()
                                    break
                                yield f"data: {execution_registry.sanitize_sse_line(line)}\n\n"
                                emitted = True
                    except Exception as exc:
                        yield f"data: Log streaming error: {execution_registry.sanitize_sse_line(str(exc))}\n\n"
                        break

                if exec_info.get('finished') and not emitted:
                    break

                if not emitted and (time.time() - keepalive_at) >= 1:
                    yield ': keepalive\n\n'
                    keepalive_at = time.time()

                time.sleep(0.2)

        return Response(stream_with_context(generate()), mimetype='text/event-stream')

    @app.route('/stop', methods=['POST'])
    def stop_execution():
        current_execution_id = execution_registry.current_execution_id
        if not current_execution_id or current_execution_id not in execution_registry.executions:
            return jsonify({'status': 'no process running'})

        exec_info = execution_registry.executions[current_execution_id]
        if exec_info['finished'] or not exec_info['process']:
            return jsonify({'status': 'already finished'})

        try:
            proc = exec_info['process']
            if proc.poll() is None:
                exec_info['stop_requested'] = True
                execution_registry.append_execution_log(
                    Path(exec_info['log_file']),
                    f"\n[{datetime.now().isoformat()}] --- Stop requested by user ---\n",
                )
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
            return jsonify({'status': 'stopping'})
        except Exception as exc:
            return jsonify({'status': 'error', 'message': str(exc)}), 500