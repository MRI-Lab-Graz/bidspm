import os
from datetime import datetime
from pathlib import Path
from typing import Callable

from flask import Flask, jsonify, request

from lib.project_manager import ProjectConfig


ProjectManagerGetter = Callable[[], object]


def _build_project_preflight_results(config) -> dict:
    results = {}

    bids_path = Path(config.bids_folder) if config.bids_folder else None
    if not bids_path or not config.bids_folder:
        results['bids_folder'] = {'status': 'na', 'message': 'Not configured'}
    elif bids_path.exists():
        if (bids_path / 'dataset_description.json').exists():
            results['bids_folder'] = {'status': 'ok', 'message': 'Valid BIDS folder'}
        else:
            results['bids_folder'] = {'status': 'warning', 'message': 'Folder exists but no dataset_description.json'}
    else:
        results['bids_folder'] = {'status': 'error', 'message': 'Folder not found'}

    fmriprep_path = Path(config.fmriprep_folder) if config.fmriprep_folder else None
    if not fmriprep_path or not config.fmriprep_folder:
        results['fmriprep_folder'] = {'status': 'na', 'message': 'Not configured'}
    elif fmriprep_path.exists():
        if (fmriprep_path / 'dataset_description.json').exists():
            results['fmriprep_folder'] = {'status': 'ok', 'message': 'Valid fMRIPrep folder'}
        else:
            results['fmriprep_folder'] = {'status': 'warning', 'message': 'Folder exists but no dataset_description.json'}
    else:
        results['fmriprep_folder'] = {'status': 'error', 'message': 'Folder not found'}

    if bids_path and bids_path.exists():
        event_files = list(bids_path.glob('sub-*/ses-*/func/*_events.tsv')) + list(bids_path.glob('sub-*/func/*_events.tsv'))
        if event_files:
            results['events'] = {'status': 'ok', 'message': f'{len(event_files)} event files found', 'value': str(len(event_files))}
        else:
            results['events'] = {'status': 'error', 'message': 'No event files found'}
    else:
        results['events'] = {'status': 'na', 'message': 'BIDS folder not available'}

    space = config.space or 'MNI152NLin2009cAsym'
    available_spaces = []
    if fmriprep_path and fmriprep_path.exists():
        for space_name in ['MNI152NLin2009cAsym', 'MNI152NLin6Asym', 'T1w']:
            if next(fmriprep_path.glob(f'**/*space-{space_name}*.nii*'), None) is not None:
                available_spaces.append(space_name)

        if space in available_spaces:
            results['space'] = {'status': 'ok', 'message': f'{space} available', 'value': space}
        elif available_spaces:
            results['space'] = {'status': 'warning', 'message': f'{space} not found. Available: {", ".join(available_spaces)}', 'value': available_spaces[0]}
        else:
            results['space'] = {'status': 'warning', 'message': 'No spaces detected'}
    else:
        results['space'] = {'status': 'na', 'message': 'fMRIPrep folder not available', 'value': space}

    derivatives_path = Path(config.derivatives_folder) if config.derivatives_folder else None
    if derivatives_path and derivatives_path.exists():
        smooth_found = next((derivatives_path / 'bidspm-preproc').glob('**/*desc-smth*'), None) is not None
        results['smooth'] = {
            'status': 'ok' if smooth_found else 'na',
            'message': 'Smoothed files found' if smooth_found else 'No smoothed files found',
            'value': 'Yes' if smooth_found else 'No',
        }
    else:
        results['smooth'] = {'status': 'na', 'message': 'Derivatives folder not available', 'value': 'No'}

    results['available_spaces'] = available_spaces
    return results


def register_project_routes(app: Flask, get_project_manager: ProjectManagerGetter) -> None:
    @app.route('/api/projects', methods=['GET'])
    def api_list_projects():
        """List all projects."""
        try:
            projects = get_project_manager().list_projects()
            return jsonify({
                'projects': [project.to_dict() for project in projects],
                'count': len(projects),
            })
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/projects', methods=['POST'])
    def api_create_project():
        """Create a new project."""
        try:
            data = request.json or {}
            name = data.get('name', '').strip()
            description = data.get('description', '').strip()
            config = data.get('config', None)

            if not name:
                return jsonify({'error': 'Project name is required'}), 400

            project = get_project_manager().create_project(name, description, config)
            return jsonify({
                'project': project.to_dict(),
                'message': f"Project '{name}' created successfully",
            }), 201
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/projects/<project_id>', methods=['GET'])
    def api_get_project(project_id: str):
        """Get a project by ID."""
        try:
            project = get_project_manager().load_project(project_id)
            if not project:
                return jsonify({'error': 'Project not found'}), 404
            return jsonify(project.to_dict())
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/projects/<project_id>', methods=['PUT'])
    def api_update_project(project_id: str):
        """Update a project."""
        try:
            manager = get_project_manager()
            project = manager.load_project(project_id)
            if not project:
                return jsonify({'error': 'Project not found'}), 404

            data = request.json or {}
            if 'name' in data:
                project.name = data['name']
            if 'description' in data:
                project.description = data['description']
            if 'config' in data:
                existing_config = project.config.to_dict()
                existing_config.update(data['config'])
                project.config = ProjectConfig.from_dict(existing_config)

            manager.save_project(project)
            return jsonify({
                'project': project.to_dict(),
                'message': 'Project updated successfully',
            })
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/projects/<project_id>', methods=['DELETE'])
    def api_delete_project(project_id: str):
        """Delete a project."""
        try:
            manager = get_project_manager()
            project = manager.load_project(project_id)
            if not project:
                return jsonify({'error': 'Project not found'}), 404

            project_name = project.name
            manager.delete_project(project_id)
            return jsonify({'message': f"Project '{project_name}' deleted successfully"})
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/projects/<project_id>/duplicate', methods=['POST'])
    def api_duplicate_project(project_id: str):
        """Duplicate a project."""
        try:
            data = request.json or {}
            new_name = data.get('name')
            new_project = get_project_manager().duplicate_project(project_id, new_name)
            if not new_project:
                return jsonify({'error': 'Project not found'}), 404

            return jsonify({
                'project': new_project.to_dict(),
                'message': f"Project duplicated as '{new_project.name}'",
            }), 201
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/projects/<project_id>/preflight', methods=['GET'])
    def api_preflight_check(project_id: str):
        """Run preflight checks for a project."""
        try:
            project = get_project_manager().load_project(project_id)
            if not project:
                return jsonify({'error': 'Project not found'}), 404
            return jsonify(_build_project_preflight_results(project.config))
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/projects/<project_id>/config', methods=['GET'])
    def api_get_project_config(project_id: str):
        """Get project configuration."""
        try:
            project = get_project_manager().load_project(project_id)
            if not project:
                return jsonify({'error': 'Project not found'}), 404
            return jsonify(project.config.to_dict())
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/projects/<project_id>/config', methods=['PUT'])
    def api_update_project_config(project_id: str):
        """Update project configuration."""
        try:
            data = request.json or {}
            success = get_project_manager().update_project_config(project_id, data)
            if not success:
                return jsonify({'error': 'Project not found'}), 404
            return jsonify({'message': 'Configuration updated successfully'})
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/projects/<project_id>/import', methods=['POST'])
    def api_import_config(project_id: str):
        """Import configuration from existing config file."""
        try:
            data = request.json or {}
            config_path = data.get('path')

            if not config_path or not os.path.exists(config_path):
                return jsonify({'error': 'Config file not found'}), 400

            success = get_project_manager().import_config(project_id, Path(config_path))
            if not success:
                return jsonify({'error': 'Failed to import configuration'}), 500

            return jsonify({'message': 'Configuration imported successfully'})
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/projects/<project_id>/export', methods=['GET'])
    def api_export_config(project_id: str):
        """Export project configuration in BIDSPM format."""
        try:
            format_type = request.args.get('format', 'bidspm')
            config = get_project_manager().export_config(project_id, format_type)
            if not config:
                return jsonify({'error': 'Project not found'}), 404
            return jsonify(config)
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/projects/<project_id>/logs', methods=['GET'])
    def api_get_project_logs(project_id: str):
        """Get project execution logs."""
        try:
            logs_dir = get_project_manager().get_project_logs_dir(project_id)
            if not logs_dir.exists():
                return jsonify({'logs': []})

            logs = []
            for log_file in sorted(logs_dir.glob('*.log'), reverse=True):
                stat = log_file.stat()
                logs.append({
                    'name': log_file.name,
                    'path': str(log_file),
                    'size': stat.st_size,
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })

            return jsonify({'logs': logs})
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500