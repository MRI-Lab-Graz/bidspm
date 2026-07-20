import json
import os
import secrets
import time
from typing import Callable

from flask import Flask, jsonify, request


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
        'docker_image': 'ghcr.io/mri-lab-graz/bidspm:latest',
        'apptainer_image': '',
    }


def _default_container_payload() -> dict:
    return {
        'container_type': 'docker',
        'docker_image': 'ghcr.io/mri-lab-graz/bidspm:latest',
        'apptainer_image': '',
    }


def register_config_fs_routes(
    app: Flask,
    resolve_fs_path: PathResolver,
    is_inside_bids_dir: PathGuard,
) -> None:
    @app.route('/load_config_file')
    def load_config_file():
        """Load configuration file."""
        path = request.args.get('path', 'config/config.json')

        if not os.path.exists(path):
            return jsonify(_default_config_payload())

        with open(path, 'r', encoding='utf-8') as file_handle:
            return jsonify(json.load(file_handle))

    @app.route('/save_settings', methods=['POST'])
    def save_settings():
        """Save configuration to file."""
        data = request.json or {}
        filepath = data.get('filepath', 'config/config.json')
        content = data.get('content')

        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as file_handle:
            json.dump(content, file_handle, indent=4)

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

        with open(path, 'r', encoding='utf-8') as file_handle:
            return jsonify(json.load(file_handle))

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
                return file_handle.read()
        except Exception as exc:
            return f'Error reading file: {exc}', 500

    @app.route('/file_content', methods=['POST'])
    def save_file_content():
        """Save content to a file (used by in-browser model editor)."""
        data = request.json or {}
        path = data.get('path')
        content = data.get('content', '')
        validate_json = data.get('validate_json', False)

        if not path:
            return jsonify({'success': False, 'error': 'No file path provided'}), 400

        if is_inside_bids_dir(path):
            return jsonify({'success': False, 'error': 'Writing inside the BIDS folder is not allowed.'}), 403

        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

            if validate_json:
                parsed = json.loads(content)
                with open(path, 'w', encoding='utf-8') as file_handle:
                    json.dump(parsed, file_handle, indent=2)
                    file_handle.write('\n')
            else:
                with open(path, 'w', encoding='utf-8') as file_handle:
                    file_handle.write(content)

            return jsonify({'success': True, 'path': path})
        except json.JSONDecodeError as exc:
            return jsonify({'success': False, 'error': f'Invalid JSON: {exc}'}), 400
        except Exception as exc:
            return jsonify({'success': False, 'error': str(exc)}), 500

    @app.route('/mkdir', methods=['POST'])
    def create_directory():
        """Create a directory."""
        data = request.json or {}
        path = data.get('path')

        if not path:
            return jsonify({'success': False, 'error': 'No path provided'}), 400

        if is_inside_bids_dir(path):
            return jsonify({'success': False, 'error': 'Creating directories inside the BIDS folder is not allowed.'}), 403

        try:
            os.makedirs(path, exist_ok=True)
            return jsonify({'success': True, 'path': path})
        except Exception as exc:
            return jsonify({'success': False, 'error': str(exc)}), 500

    @app.route('/save_config', methods=['POST'])
    def save_config():
        """Save configuration (legacy endpoint)."""
        data = request.json or {}
        config_data = data.get('config')
        folder = data.get('folder', 'configs')
        filename = data.get('filename', f'config_{int(time.time())}.json')

        os.makedirs(folder, exist_ok=True)
        filepath = os.path.join(folder, filename)

        with open(filepath, 'w', encoding='utf-8') as file_handle:
            json.dump(config_data, file_handle, indent=4)

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

        filepath = os.path.join(folder, filename)
        if not os.path.exists(filepath):
            return jsonify({'error': 'File not found'}), 404

        with open(filepath, 'r', encoding='utf-8') as file_handle:
            return jsonify(json.load(file_handle))