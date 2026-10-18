import json
import os
import secrets
import time
from typing import Callable

from flask import Flask, Response, jsonify, request

from lib.safe_paths import UnsafePath, safe_target


def _reject_constant(name):
    raise ValueError(f'{name} is not valid JSON')


PathResolver = Callable[[str], str]
PathGuard = Callable[[str], bool]


def _default_config_payload() -> dict:
    return {
        'WD': '',
        'BIDS_DIR': '',
        'DERIVATIVES_DIR': '',
        'FMRIPREP_DIR': '',
        'SPACE': 'MNI152NLin2009cAsym',
        'FWHM': 6,
        'MODELS_FILE': '',
        'TASKS': [],
        'VERBOSITY': 3,
        'container_type': 'docker',
        'docker_image': 'bidspm/bidspm:latest',
        'apptainer_image': '',
    }


def _default_container_payload() -> dict:
    return {
        'container_type': 'docker',
        'docker_image': 'bidspm/bidspm:latest',
        'apptainer_image': '',
    }


def register_config_fs_routes(
    app: Flask,
    resolve_fs_path: PathResolver,
    is_inside_bids_dir: PathGuard,
) -> None:
    def _json_file_response(path):
        """The parsed JSON file as a response; unreadable/invalid files are JSON errors, never an HTML 500."""
        try:
            with open(path, 'r', encoding='utf-8') as file_handle:
                return jsonify(json.load(file_handle, parse_constant=_reject_constant))
        except IsADirectoryError:
            return jsonify({'error': f'{path} is a folder, not a configuration file.'}), 400
        except (ValueError, RecursionError) as exc:  # JSONDecodeError, UnicodeDecodeError, NaN, too deep
            return jsonify({'error': f'{path} is not valid JSON: {exc}'}), 422
        except OSError as exc:
            return jsonify({'error': f'could not read {path}: {exc.strerror or exc}'}), 400

    @app.route('/load_config_file')
    def load_config_file():
        """Load configuration file."""
        path = request.args.get('path', 'config/config.json')
        if '..' in path.replace('\\', '/').split('/'):
            return jsonify({'error': "The path must not contain '..'."}), 400

        if not os.path.exists(path):
            return jsonify(_default_config_payload())

        return _json_file_response(path)

    @app.route('/save_settings', methods=['POST'])
    def save_settings():
        """Save configuration to file."""
        data = request.json if isinstance(request.json, dict) else {}
        filepath = data.get('filepath', 'config/config.json')
        content = data.get('content')

        try:
            filepath = safe_target(filepath, inside=is_inside_bids_dir)
        except UnsafePath as exc:
            return jsonify({'status': 'error', 'error': str(exc)}), exc.status
        if not filepath.endswith('.json'):
            return jsonify({'status': 'error', 'error': 'The settings file must end with .json'}), 400

        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as file_handle:
                json.dump(content, file_handle, indent=4)
        except (OSError, TypeError, ValueError) as exc:
            return jsonify({'status': 'error', 'error': f'could not save: {exc}'}), 400

        return jsonify({'status': 'success', 'path': filepath})

    @app.route('/validate_config', methods=['POST'])
    def validate_config():
        """Validate configuration against schema."""
        data = request.json or {}
        content = data.get('content')
        schema_path = 'config/config_schema.json'

        if not os.path.exists(schema_path):
            return jsonify({'valid': False, 'error': 'Schema file not found'}), 404

        temp_path = f"config/temp_val_{secrets.token_hex(4)}.json"

        try:
            with open(temp_path, 'w', encoding='utf-8') as file_handle:
                json.dump(content, file_handle)

            from docs.json_validator import JSONValidator

            is_valid = JSONValidator.validate_with_schema(temp_path, schema_path)
            if is_valid:
                return jsonify({'valid': True})
            return jsonify({'valid': False, 'error': 'Validation failed'})
        except Exception as exc:
            return jsonify({'valid': False, 'error': str(exc)})
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    @app.route('/check_paths', methods=['POST'])
    def check_paths():
        """Check if configuration paths exist."""
        data = request.json or {}
        results = {}

        for key in ['WD', 'BIDS_DIR', 'DERIVATIVES_DIR', 'FMRIPREP_DIR', 'MODELS_FILE']:
            path = data.get(key)
            if path:
                results[key] = os.path.exists(path)
            elif key == 'MODELS_FILE':
                results[key] = True

        return jsonify(results)

    @app.route('/get_schema')
    def get_schema():
        """Get configuration schema."""
        schema_path = 'config/config_schema.json'
        if os.path.exists(schema_path):
            with open(schema_path, 'r', encoding='utf-8') as file_handle:
                return jsonify(json.load(file_handle))
        return jsonify({})

    @app.route('/load_container_file')
    def load_container_file():
        """Load container configuration."""
        path = request.args.get('path', 'containers/container.json')

        if not os.path.exists(path):
            return jsonify(_default_container_payload())

        return _json_file_response(path)

    @app.route('/browse')
    def browse_fs():
        """Browse filesystem for file/directory selection."""
        path = resolve_fs_path(request.args.get('path', '')) or os.getcwd()
        only_dirs = request.args.get('only_dirs', 'false').lower() == 'true'
        extensions_raw = (request.args.get('extensions', '') or '').strip()
        allowed_extensions = None
        if extensions_raw:
            parsed = [extension.strip().lower() for extension in extensions_raw.split(',') if extension.strip()]
            normalized = [extension if extension.startswith('.') else f'.{extension}' for extension in parsed]
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

            with os.scandir(path) as entries:
                for entry in entries:
                    if entry.is_dir():
                        items.append({'name': entry.name, 'path': entry.path, 'type': 'dir'})
                    elif not only_dirs:
                        entry_name_lc = entry.name.lower()
                        if allowed_extensions:
                            if entry_name_lc.endswith(allowed_extensions):
                                items.append({'name': entry.name, 'path': entry.path, 'type': 'file'})
                        elif entry_name_lc.endswith(('.json', '.sif')):
                            items.append({'name': entry.name, 'path': entry.path, 'type': 'file'})

            items.sort(key=lambda item: (item['type'] != 'dir', item['name'].lower()))
            return jsonify({'current_path': os.path.abspath(path), 'items': items})
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/file_content')
    def file_content():
        """Get content of a file."""
        path = request.args.get('path')
        if not path or not os.path.isfile(path):
            return 'File not found', 404

        try:
            with open(path, 'r', encoding='utf-8') as file_handle:
                text = file_handle.read()
        except Exception as exc:
            return f'Error reading file: {exc}', 500
        # file contents are data, never a page: no sniffing to HTML, and a sandbox if one is ever opened directly
        return Response(text, mimetype='text/plain', headers={
            'Content-Type': 'text/plain; charset=utf-8',
            'X-Content-Type-Options': 'nosniff',
            'Content-Security-Policy': 'sandbox',
        })

    @app.route('/file_content', methods=['POST'])
    def save_file_content():
        """Save content to a file (used by in-browser model editor)."""
        data = request.json if isinstance(request.json, dict) else {}
        path = data.get('path')
        content = data.get('content', '')
        validate_json = data.get('validate_json', False)

        if not path:
            return jsonify({'success': False, 'error': 'No file path provided'}), 400

        try:
            path = safe_target(path, inside=is_inside_bids_dir)
        except UnsafePath as exc:
            return jsonify({'success': False, 'error': str(exc)}), exc.status

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)

            if validate_json:
                parsed = json.loads(content, parse_constant=_reject_constant)
                with open(path, 'w', encoding='utf-8') as file_handle:
                    json.dump(parsed, file_handle, indent=2)
                    file_handle.write('\n')
            else:
                with open(path, 'w', encoding='utf-8') as file_handle:
                    file_handle.write(content)

            return jsonify({'success': True, 'path': path})
        except ValueError as exc:
            return jsonify({'success': False, 'error': f'Invalid JSON: {exc}'}), 400
        except Exception as exc:
            return jsonify({'success': False, 'error': str(exc)}), 500

    @app.route('/mkdir', methods=['POST'])
    def create_directory():
        """Create a directory."""
        data = request.json if isinstance(request.json, dict) else {}
        path = data.get('path')

        if not path:
            return jsonify({'success': False, 'error': 'No path provided'}), 400

        try:
            path = safe_target(path, inside=is_inside_bids_dir)
        except UnsafePath as exc:
            return jsonify({'success': False, 'error': str(exc)}), exc.status

        try:
            os.makedirs(path, exist_ok=True)
            return jsonify({'success': True, 'path': path})
        except Exception as exc:
            return jsonify({'success': False, 'error': str(exc)}), 500

    @app.route('/save_config', methods=['POST'])
    def save_config():
        """Save configuration (legacy endpoint)."""
        data = request.json if isinstance(request.json, dict) else {}
        config_data = data.get('config')
        folder = data.get('folder', 'configs')
        filename = data.get('filename', f'config_{int(time.time())}.json')

        try:
            folder = safe_target(folder, inside=is_inside_bids_dir)
            filepath = safe_target(filename, base=folder, inside=is_inside_bids_dir)  # a name under the folder, never outside it
        except UnsafePath as exc:
            return jsonify({'status': 'error', 'error': str(exc)}), exc.status
        if not filepath.endswith('.json'):
            return jsonify({'status': 'error', 'error': 'The configuration file name must end with .json'}), 400

        try:
            os.makedirs(folder, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as file_handle:
                json.dump(config_data, file_handle, indent=4)
        except (OSError, TypeError, ValueError) as exc:
            return jsonify({'status': 'error', 'error': f'could not save: {exc}'}), 400

        return jsonify({'status': 'saved', 'path': filepath})

    @app.route('/configs')
    def list_configs():
        """List configuration files."""
        folder = request.args.get('folder', 'configs')

        if not os.path.exists(folder):
            return jsonify([])

        try:
            files = [name for name in os.listdir(folder) if name.endswith('.json')]
            return jsonify(files)
        except Exception:
            return jsonify([])

    @app.route('/load_config')
    def api_load_config():
        """Load configuration (legacy endpoint)."""
        folder = request.args.get('folder', 'configs')
        filename = request.args.get('filename')

        if not filename:
            return jsonify({'error': 'No filename provided'}), 400

        try:
            filepath = safe_target(filename, base=folder)
        except UnsafePath as exc:
            return jsonify({'error': str(exc)}), exc.status
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404

        return _json_file_response(filepath)