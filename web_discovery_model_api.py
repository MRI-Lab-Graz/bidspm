import csv
import json
import os
import random
import secrets
from collections import Counter
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from flask import Flask, jsonify, request

from lib import (
    check_feature_availability,
    detect_matlab_environment,
    discover_spaces,
    discover_subjects,
    discover_tasks,
    estimate_processing_time,
    load_config,
    validate_bids_model,
)


PathResolver = Callable[[str], str]


def _extract_model_hints(model_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract tasks, contrast levels, and replacement values from a BIDS model."""
    field_status = {
        'model_tasks': 'absent',
        'replace_values': 'absent',
        'contrast_levels': 'absent',
        'transformed_columns': 'absent',
    }

    raw_input = model_data.get('Input', {})
    raw_tasks = raw_input.get('task', []) if isinstance(raw_input, dict) else []
    tasks = raw_tasks
    if isinstance(tasks, str):
        tasks = [tasks]
    elif not isinstance(tasks, list):
        tasks = []
        if raw_tasks not in (None, [], ''):
            field_status['model_tasks'] = 'invalid'

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
        field_status['replace_values'] = 'invalid'
        field_status['contrast_levels'] = 'invalid'

    for node in nodes:
        if not isinstance(node, dict):
            field_status['replace_values'] = 'invalid'
            field_status['contrast_levels'] = 'invalid'
            continue

        transformations = node.get('Transformations', {})
        instructions = transformations.get('Instructions', []) if isinstance(transformations, dict) else []
        if transformations and not isinstance(transformations, dict):
            field_status['replace_values'] = 'invalid'
            field_status['transformed_columns'] = 'invalid'

        if isinstance(transformations, dict):
            saw_transformations = True
            generated_columns = transformations.get('GeneratedColumns', [])
            if generated_columns not in (None, []):
                if not isinstance(generated_columns, list):
                    field_status['transformed_columns'] = 'invalid'
                else:
                    for column_name in generated_columns:
                        if isinstance(column_name, str) and column_name.strip():
                            transformed_columns.add(column_name.strip())

        for instruction in instructions if isinstance(instructions, list) else []:
            if not isinstance(instruction, dict):
                field_status['replace_values'] = 'invalid'
                field_status['transformed_columns'] = 'invalid'
                continue

            output_value = instruction.get('Output')
            if isinstance(output_value, str) and output_value.strip():
                transformed_columns.add(output_value.strip())
            elif isinstance(output_value, list):
                for output_name in output_value:
                    if isinstance(output_name, str) and output_name.strip():
                        transformed_columns.add(output_name.strip())
                    elif output_name not in (None, ''):
                        field_status['transformed_columns'] = 'invalid'
            elif output_value not in (None, ''):
                field_status['transformed_columns'] = 'invalid'

            if instruction.get('Name') == 'Replace':
                saw_replace_instruction = True
                replace_entries = instruction.get('Replace', [])
                if not isinstance(replace_entries, list):
                    field_status['replace_values'] = 'invalid'
                    continue
                for replacement in replace_entries:
                    if not isinstance(replacement, dict):
                        field_status['replace_values'] = 'invalid'
                        continue
                    value = replacement.get('value')
                    if isinstance(value, str) and value.strip():
                        replace_values.add(value.strip())

        contrasts = node.get('Contrasts', [])
        if contrasts and not isinstance(contrasts, list):
            field_status['contrast_levels'] = 'invalid'
            continue

        for contrast in contrasts if isinstance(contrasts, list) else []:
            if not isinstance(contrast, dict):
                field_status['contrast_levels'] = 'invalid'
                continue
            condition_list = contrast.get('ConditionList', [])
            if condition_list and not isinstance(condition_list, list):
                field_status['contrast_levels'] = 'invalid'
                continue
            for term in condition_list if isinstance(condition_list, list) else []:
                if not isinstance(term, str):
                    field_status['contrast_levels'] = 'invalid'
                    continue
                saw_contrast_term = True
                contrast_terms.add(term)
                if '.' in term:
                    _, level = term.rsplit('.', 1)
                    if level:
                        contrast_levels.add(level)
                else:
                    contrast_levels.add(term)

    model_tasks = sorted({task.strip() for task in tasks if isinstance(task, str) and task.strip()})
    if model_tasks:
        field_status['model_tasks'] = 'present'
    elif field_status['model_tasks'] != 'invalid':
        field_status['model_tasks'] = 'absent'

    if replace_values:
        field_status['replace_values'] = 'present'
    elif field_status['replace_values'] != 'invalid':
        field_status['replace_values'] = 'absent' if saw_replace_instruction or nodes else 'absent'

    if contrast_levels:
        field_status['contrast_levels'] = 'present'
    elif field_status['contrast_levels'] != 'invalid':
        field_status['contrast_levels'] = 'absent' if saw_contrast_term or nodes else 'absent'

    if transformed_columns:
        field_status['transformed_columns'] = 'present'
    elif field_status['transformed_columns'] != 'invalid':
        field_status['transformed_columns'] = 'absent' if saw_transformations or nodes else 'absent'

    return {
        'model_tasks': model_tasks,
        'replace_values': sorted(replace_values),
        'contrast_levels': sorted(contrast_levels),
        'contrast_terms': sorted(contrast_terms),
        'transformed_columns': sorted(transformed_columns),
        'field_status': field_status,
    }


def _discover_event_info(bids_dir: Path, tasks_filter: Optional[List[str]] = None, max_files: int = 120) -> Dict[str, Any]:
    """Collect event columns and representative sample values from BIDS *_events.tsv files."""
    if not bids_dir.exists() or not bids_dir.is_dir():
        return {
            'files_scanned': 0,
            'event_columns': [],
            'sample_values': {},
            'all_values': {},
            'numeric_columns': [],
            'numeric_sample_values': {},
            'profile_variants': {},
            'sample_status': {},
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
    event_files = sorted(bids_dir.glob('sub-*/ses-*/func/*_events.tsv')) + sorted(bids_dir.glob('sub-*/func/*_events.tsv'))
    event_files = sorted(set(event_files))
    if task_tokens:
        event_files = [
            event_file
            for event_file in event_files
            if any(f'task-{task}_' in event_file.name or f'task-{task}.' in event_file.name for task in task_tokens)
        ]

    event_columns = set()
    sample_values = {'trial_type': set(), 'condition': set()}
    numeric_tracker: Dict[str, Dict[str, Any]] = {}
    profile_counts = {'trial_type': Counter(), 'condition': Counter()}

    for event_file in event_files[:max_files]:
        file_values = {'trial_type': set(), 'condition': set()}
        try:
            with open(event_file, 'r', encoding='utf-8') as file_handle:
                reader = csv.DictReader(file_handle, delimiter='\t')
                if not reader.fieldnames:
                    continue

                fieldnames = [name.strip() for name in reader.fieldnames if name]
                event_columns.update(fieldnames)

                for row in reader:
                    for column in ('trial_type', 'condition'):
                        if column in row and row[column]:
                            value = str(row[column]).strip()
                            if value and value != 'n/a':
                                sample_values[column].add(value)
                                file_values[column].add(value)

                    for column_name in fieldnames:
                        normalized = _normalize_cell(row.get(column_name, ''))
                        if not normalized:
                            continue
                        if column_name not in numeric_tracker:
                            numeric_tracker[column_name] = {
                                'saw_numeric': False,
                                'saw_non_numeric': False,
                                'sample_values': [],
                            }
                        tracker = numeric_tracker[column_name]
                        if _is_numeric_token(normalized):
                            tracker['saw_numeric'] = True
                            samples = tracker['sample_values']
                            if normalized not in samples and len(samples) < 25:
                                samples.append(normalized)
                        else:
                            tracker['saw_non_numeric'] = True

                    if len(file_values['trial_type']) > 50 and len(file_values['condition']) > 50:
                        break

                for column in ('trial_type', 'condition'):
                    if file_values[column]:
                        profile_counts[column][tuple(sorted(file_values[column]))] += 1
        except Exception:
            continue

    representative_values = {}
    profile_variants = {}
    for column in ('trial_type', 'condition'):
        if profile_counts[column]:
            representative_profile, _ = profile_counts[column].most_common(1)[0]
            representative_values[column] = list(representative_profile)[:30]
            profile_variants[column] = len(profile_counts[column])
        else:
            representative_values[column] = []
            profile_variants[column] = 0

    numeric_columns = sorted([
        column_name
        for column_name, tracker in numeric_tracker.items()
        if tracker.get('saw_numeric') and not tracker.get('saw_non_numeric')
    ])
    numeric_sample_values = {
        column_name: numeric_tracker[column_name].get('sample_values', [])[:12]
        for column_name in numeric_columns
    }

    return {
        'files_scanned': min(len(event_files), max_files),
        'event_columns': sorted(event_columns),
        'sample_values': representative_values,
        'all_values': {
            'trial_type': sorted(sample_values['trial_type'])[:50],
            'condition': sorted(sample_values['condition'])[:50],
        },
        'numeric_columns': numeric_columns,
        'numeric_sample_values': numeric_sample_values,
        'profile_variants': profile_variants,
        'sample_status': {
            'trial_type': 'present' if sample_values['trial_type'] else ('missing-column' if 'trial_type' not in event_columns else 'empty-column'),
            'condition': 'present' if sample_values['condition'] else ('missing-column' if 'condition' not in event_columns else 'empty-column'),
        },
    }


def _discover_confound_info(fmriprep_dir: Path, tasks_filter: Optional[List[str]] = None, max_files: int = 120) -> Dict[str, Any]:
    """Collect confound column names from fMRIPrep desc-confounds_timeseries TSV files."""
    if not fmriprep_dir.exists() or not fmriprep_dir.is_dir():
        return {
            'files_scanned': 0,
            'columns': [],
            'trans_rot_present': [],
            'sample_status': 'missing-dir',
        }

    task_tokens = set(tasks_filter or [])
    confound_files = sorted(fmriprep_dir.glob('sub-*/ses-*/func/*desc-confounds_timeseries.tsv')) + sorted(fmriprep_dir.glob('sub-*/func/*desc-confounds_timeseries.tsv'))
    confound_files = sorted(set(confound_files))
    if task_tokens:
        confound_files = [
            confound_file
            for confound_file in confound_files
            if any(f'task-{task}_' in confound_file.name or f'task-{task}.' in confound_file.name for task in task_tokens)
        ]

    if not confound_files:
        return {
            'files_scanned': 0,
            'columns': [],
            'trans_rot_present': [],
            'sample_status': 'missing-files',
        }

    columns = set()
    for confound_file in confound_files[:max_files]:
        try:
            with open(confound_file, 'r', encoding='utf-8') as file_handle:
                reader = csv.DictReader(file_handle, delimiter='\t')
                if not reader.fieldnames:
                    continue
                columns.update(name.strip() for name in reader.fieldnames if name and name.strip())
        except Exception:
            continue

    trans_rot_defaults = ['trans_x', 'trans_y', 'trans_z', 'rot_x', 'rot_y', 'rot_z']
    trans_rot_present = [name for name in trans_rot_defaults if name in columns]

    return {
        'files_scanned': min(len(confound_files), max_files),
        'columns': sorted(columns),
        'trans_rot_present': trans_rot_present,
        'sample_status': 'present' if columns else 'empty',
    }


def _discover_participants_info(bids_dir: Path, max_values_per_column: int = 20) -> Dict[str, Any]:
    """Collect participants.tsv metadata for dataset-level grouping and covariates."""
    default_payload = {
        'columns': [],
        'categorical_columns': [],
        'numeric_columns': [],
        'sample_values': {},
        'numeric_stats': {},
        'sample_status': 'missing-dir',
    }

    if not bids_dir.exists() or not bids_dir.is_dir():
        return default_payload

    participants_file = bids_dir / 'participants.tsv'
    if not participants_file.is_file():
        return {**default_payload, 'sample_status': 'missing-file'}

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
                return {**default_payload, 'sample_status': 'invalid-header'}

            columns = [name.strip() for name in reader.fieldnames if name and name.strip() and name.strip() != 'participant_id']
            if not columns:
                return {**default_payload, 'sample_status': 'empty'}

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
                numeric_values = [number for number in (_parse_number(value) for value in sorted_values) if number is not None]
                if numeric_values:
                    numeric_stats[column] = {'min': min(numeric_values), 'max': max(numeric_values), 'count': len(numeric_values)}
            else:
                categorical_columns.append(column)

        return {
            'columns': columns,
            'categorical_columns': categorical_columns,
            'numeric_columns': numeric_columns,
            'sample_values': sample_values,
            'numeric_stats': numeric_stats,
            'sample_status': 'present',
        }
    except Exception:
        return {**default_payload, 'sample_status': 'error'}


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
                warnings.append(f"Task '{task}' is not present in BIDS data. Close matches: {', '.join(suggestions)}")
            else:
                warnings.append(f"Task '{task}' is not present in BIDS data.")

    if replace_values and contrast_levels:
        for level in contrast_levels:
            if level in replace_values or level in transformed_columns:
                continue
            suggestions = get_close_matches(level, list(replace_values), n=3, cutoff=0.6)
            if suggestions:
                warnings.append(f"Contrast level '{level}' is not generated by Replace values. Close matches: {', '.join(suggestions)}")

    trial_type_variants = int(event_info.get('profile_variants', {}).get('trial_type', 0) or 0)
    if trial_type_variants > 1:
        warnings.append(
            f'Detected {trial_type_variants} distinct trial_type profiles across the selected task files. '
            'Editor suggestions use the most common profile to avoid mixing incompatible event codings.'
        )

    raw_value_source = event_info.get('all_values') or event_info.get('sample_values') or {}
    raw_conditions = set(raw_value_source.get('condition', [])) | set(raw_value_source.get('trial_type', []))
    if raw_conditions and not replace_values and contrast_levels:
        for level in contrast_levels:
            if level in raw_conditions or level in transformed_columns:
                continue
            suggestions = get_close_matches(level, list(raw_conditions), n=3, cutoff=0.7)
            if suggestions:
                warnings.append(f"Contrast level '{level}' does not appear in sampled event values. Close matches: {', '.join(suggestions)}")

    return warnings


def _scan_bids_for_model(bids_dir: str) -> dict:
    """Scan a BIDS directory to extract tasks and trial_type levels."""
    import re as _re

    bids_path = Path(bids_dir)
    tasks = []
    trial_types_by_task: dict = {}
    all_event_files = sorted(bids_path.glob('sub-*/ses-*/func/*_events.tsv')) + sorted(bids_path.glob('sub-*/func/*_events.tsv'))

    for event_file in all_event_files:
        match = _re.search(r'task-([^_/]+)', event_file.name)
        if not match:
            continue
        task = match.group(1)
        if task not in tasks:
            tasks.append(task)
        try:
            with event_file.open(encoding='utf-8') as file_handle:
                reader = csv.DictReader(file_handle, delimiter='\t')
                for row in reader:
                    value = (row.get('trial_type') or '').strip()
                    if value and value != 'n/a':
                        trial_types_by_task.setdefault(task, set()).add(value)
        except Exception:
            pass

    for task in trial_types_by_task:
        trial_types_by_task[task] = sorted(trial_types_by_task[task])

    return {'tasks': tasks, 'trial_types_by_task': trial_types_by_task}


def _build_default_model(tasks: list, trial_types_by_task: dict) -> dict:
    """Build a default BIDS stats model from task and trial-type information."""
    nodes = []

    for task in tasks:
        conditions = trial_types_by_task.get(task, [])
        predictors = [f'trial_type.{condition}' for condition in conditions] if conditions else ['trial_type.condition_a']
        predictors_with_intercept = predictors + [1]

        contrasts = []
        count = len(predictors)
        for index, predictor in enumerate(predictors):
            contrast_name = predictor.replace('trial_type.', '')
            if count > 1:
                weights = [-1 / (count - 1) if other_index != index else 1 for other_index in range(count)]
            else:
                weights = [1]
            contrasts.append({
                'Name': contrast_name,
                'ConditionList': predictors,
                'Weights': weights,
                'Test': 't',
            })

        node_name = f'run_level_{task}' if len(tasks) > 1 else 'run_level'
        nodes.append({
            'Level': 'Run',
            'Name': node_name,
            'GroupBy': ['run', 'subject', 'task'],
            'Model': {
                'Type': 'glm',
                'X': predictors_with_intercept,
                'HRF': {'Variables': predictors, 'Model': 'spm'},
                'Options': {
                    'HighPassFilterCutoffHz': 0.0078,
                    'Mask': {'desc': ['brain'], 'suffix': ['mask']},
                },
                'Software': {'SPM': {'Model': 'spm', 'Version': 25}},
            },
            'Contrasts': contrasts,
        })

    all_contrast_names = []
    for node in nodes:
        for contrast in node.get('Contrasts', []):
            if contrast['Name'] not in all_contrast_names:
                all_contrast_names.append(contrast['Name'])

    subject_contrasts = [{'Name': name, 'ConditionList': [name], 'Weights': [1], 'Test': 't'} for name in all_contrast_names]
    nodes.append({
        'Level': 'Subject',
        'Name': 'subject_level',
        'GroupBy': ['subject', 'contrast'],
        'Model': {'Type': 'glm', 'X': all_contrast_names or ['contrast']},
        'Contrasts': subject_contrasts,
    })

    dataset_contrasts = [{'Name': name, 'ConditionList': [name], 'Weights': [1], 'Test': 't'} for name in all_contrast_names]
    nodes.append({
        'Level': 'Dataset',
        'Name': 'dataset_level',
        'GroupBy': ['contrast'],
        'Model': {'Type': 'glm', 'X': [1]},
        'Contrasts': dataset_contrasts,
    })

    return {
        'Name': 'default-model',
        'BIDSModelVersion': '1.0.0',
        'Description': 'Default BIDS stats model – generated from dataset events files.',
        'Input': {'task': tasks},
        'Nodes': nodes,
    }


def _extract_task_name(path: str) -> str:
    file_name = os.path.basename(path)
    for part in file_name.split('_'):
        if part.startswith('task-') and len(part) > 5:
            return part[5:]
    return ''


def register_discovery_model_routes(app: Flask, resolve_fs_path: PathResolver, app_root: Path) -> None:
    @app.route('/get_bids_tasks')
    def get_bids_tasks():
        path = request.args.get('path')
        if not path or not os.path.isdir(path):
            return jsonify([])
        return jsonify(discover_tasks(Path(path)))

    @app.route('/api/bids_entities')
    def api_bids_entities():
        path = request.args.get('path')
        if not path or not os.path.isdir(path):
            return jsonify({
                'entities': [],
                'groupby_options': ['subject'],
                'values': {'task': [], 'run': [], 'session': [], 'subject': []},
                'participants': _discover_participants_info(Path('')),
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
            'trc': 'tracer',
        }
        known_datatypes = {'anat', 'func', 'dwi', 'fmap', 'perf', 'meg', 'eeg', 'ieeg', 'beh', 'pet', 'micr', 'nirs', 'motion', 'mrs'}

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
                stem = _filename_stem(file_path.name)
                tokens = [token for token in stem.split('_') if token]
                for token in tokens:
                    if '-' not in token:
                        continue
                    short_key, raw_value = token.split('-', 1)
                    _add_value(entity_aliases.get(short_key, short_key), raw_value)

                suffix_token = ''
                for token in tokens:
                    if '-' not in token:
                        suffix_token = token
                if suffix_token:
                    _add_value('suffix', suffix_token)

                for part in file_path.parts:
                    if part in known_datatypes:
                        _add_value('datatype', part)

                for part in file_path.parts[:-1]:
                    if part.startswith('sub-') and len(part) > 4:
                        _add_value('subject', part[4:])
                    elif part.startswith('ses-') and len(part) > 4:
                        _add_value('session', part[4:])

                extension = _file_extension(file_path)
                if extension:
                    _add_value('extension', extension)
        except Exception:
            pass

        try:
            for task in discover_tasks(bids_path):
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

        value_lists = {key: _sort_tokens(token_set) for key, token_set in values.items()}
        participants_info = _discover_participants_info(bids_path)

        groupby_options = ['subject']
        for candidate in ['run', 'session', 'task']:
            if candidate in entities:
                groupby_options.append(candidate)
        for candidate in participants_info.get('categorical_columns', []):
            if candidate not in groupby_options:
                groupby_options.append(candidate)

        return jsonify({
            'entities': sorted(list(entities)),
            'groupby_options': groupby_options,
            'values': value_lists,
            'participants': participants_info,
            'scanned_files': scanned,
        })

    @app.route('/get_fmriprep_spaces')
    def get_fmriprep_spaces():
        path = request.args.get('path')
        tasks = request.args.getlist('tasks')
        if not path or not os.path.isdir(path):
            return jsonify([])
        return jsonify(discover_spaces(Path(path), tasks if tasks else None))

    @app.route('/get_subjects')
    def get_subjects():
        config_path = request.args.get('config', 'config/config.json')
        if not os.path.isfile(config_path):
            return jsonify([])
        try:
            config = load_config(config_path)
            return jsonify(discover_subjects(config))
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/estimate_time', methods=['POST'])
    def api_estimate_time():
        data = request.json or {}
        config_path = data.get('config', 'config/config.json')
        actions = data.get('actions', ['smooth', 'stats'])
        try:
            config = load_config(config_path)
            subjects = config.SUBJECTS or discover_subjects(config)
            tasks = config.TASKS
            return jsonify(estimate_processing_time(subjects, actions, tasks))
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/check_environment')
    def api_check_environment():
        use_local = request.args.get('local', 'false').lower() == 'true'
        if use_local:
            capabilities = detect_matlab_environment()
            features = check_feature_availability(capabilities, using_container=False)
            return jsonify({
                'environment': capabilities.to_dict(),
                'features': {
                    'smooth': features.smooth,
                    'stats_subject': features.stats_subject,
                    'stats_dataset': features.stats_dataset,
                    'roi_analysis': features.roi_analysis,
                    'custom_contrasts': features.custom_contrasts,
                },
                'unavailable_reasons': features.unavailable_reasons,
            })

        import shutil

        docker = shutil.which('docker') is not None
        apptainer = shutil.which('apptainer') is not None
        return jsonify({'docker_available': docker, 'apptainer_available': apptainer, 'all_features_available': docker or apptainer})

    @app.route('/api/model/create', methods=['POST'])
    def api_model_create():
        data = request.json or {}
        path = data.get('path', '').strip()
        bids_dir = data.get('bids_dir', '').strip()

        if not path:
            return jsonify({'success': False, 'error': 'No path provided'}), 400

        path = os.path.abspath(path)
        if os.path.exists(path) and not data.get('overwrite', False):
            return jsonify({'success': False, 'error': 'File already exists. Set overwrite=true to replace it.'}), 409

        try:
            if bids_dir and os.path.isdir(bids_dir):
                scan = _scan_bids_for_model(bids_dir)
                model = _build_default_model(scan['tasks'], scan['trial_types_by_task'])
                source = 'bids_scan'
            else:
                model = _build_default_model([], {})
                source = 'skeleton'

            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            with open(path, 'w', encoding='utf-8') as file_handle:
                json.dump(model, file_handle, indent=2)
                file_handle.write('\n')
            return jsonify({'success': True, 'path': path, 'source': source, 'tasks': model['Input'].get('task', [])})
        except Exception as exc:
            return jsonify({'success': False, 'error': str(exc)}), 500

    @app.route('/validate_model', methods=['POST'])
    def api_validate_model():
        data = request.json or {}
        content = data.get('content')
        if not content:
            return jsonify({'valid': False, 'error': 'No content provided'}), 400

        temp_path = Path(f"config/temp_model_{secrets.token_hex(4)}.json")
        try:
            with open(temp_path, 'w', encoding='utf-8') as file_handle:
                json.dump(content, file_handle)
            return jsonify(validate_bids_model(temp_path))
        finally:
            if temp_path.exists():
                temp_path.unlink()

    @app.route('/get_model_tasks')
    def get_model_tasks():
        path = request.args.get('path')
        if not path or not os.path.isfile(path):
            return jsonify({'error': 'Invalid file path'})
        try:
            with open(path, 'r', encoding='utf-8') as file_handle:
                data = json.load(file_handle)
                return jsonify({'tasks': data.get('Input', {}).get('task', [])})
        except Exception as exc:
            return jsonify({'error': str(exc)})

    @app.route('/api/model_hints', methods=['POST'])
    def api_model_hints():
        data = request.json or {}
        model_content = data.get('model_content')
        model_path = data.get('model_path')
        bids_dir = data.get('bids_dir', '')
        fmriprep_dir = data.get('fmriprep_dir', '')

        if model_content is None and model_path:
            if not os.path.isfile(model_path):
                return jsonify({'error': f'Model file not found: {model_path}'}), 400
            try:
                with open(model_path, 'r', encoding='utf-8') as file_handle:
                    model_content = json.load(file_handle)
            except Exception as exc:
                return jsonify({'error': f'Failed to parse model file: {str(exc)}'}), 400

        if model_content is None:
            return jsonify({'error': 'No model content provided'}), 400
        if not isinstance(model_content, dict):
            return jsonify({'error': 'Model content must be a JSON object'}), 400

        model_hints = _extract_model_hints(model_content)
        bids_tasks = []
        event_info = {'files_scanned': 0, 'event_columns': [], 'sample_values': {}}
        confound_info = {'files_scanned': 0, 'columns': [], 'trans_rot_present': [], 'sample_status': 'missing-dir'}
        participants_info = {
            'columns': [],
            'categorical_columns': [],
            'numeric_columns': [],
            'sample_values': {},
            'numeric_stats': {},
            'sample_status': 'missing-dir',
        }

        if bids_dir and os.path.isdir(bids_dir):
            bids_tasks = discover_tasks(Path(bids_dir))
            event_info = _discover_event_info(Path(bids_dir), model_hints.get('model_tasks', []))
            participants_info = _discover_participants_info(Path(bids_dir))
            if event_info.get('files_scanned', 0) == 0:
                return jsonify({'error': 'No BIDS *_events.tsv files found in BIDS folder. Event files are required.'}), 400

        if fmriprep_dir and os.path.isdir(fmriprep_dir):
            confound_info = _discover_confound_info(Path(fmriprep_dir), model_hints.get('model_tasks', []))

        warnings = _build_model_warnings(model_hints, bids_tasks, event_info)
        return jsonify({
            'model': model_hints,
            'dataset': {
                'bids_tasks': bids_tasks,
                'events': event_info,
                'confounds': confound_info,
                'participants': participants_info,
            },
            'warnings': warnings,
            'ok': len(warnings) == 0,
        })

    @app.route('/api/scan_events_columns', methods=['POST'])
    def api_scan_events_columns():
        try:
            data = request.json or {}
            bids_dir = data.get('bids_dir', '').strip().strip('"\'')
            events_file = data.get('events_file', '').strip().strip('"\'')
            preview_file = data.get('preview_file', '').strip()
            task_filter = data.get('task_filter', '').strip()
            preview_max_rows = data.get('preview_max_rows', 200)

            try:
                preview_max_rows = int(preview_max_rows)
                if preview_max_rows < 0:
                    preview_max_rows = 200
            except (TypeError, ValueError):
                preview_max_rows = 200

            if events_file:
                events_file = resolve_fs_path(events_file)

            if bids_dir:
                bids_dir = resolve_fs_path(bids_dir)
                if not os.path.isdir(bids_dir):
                    return jsonify({'error': f'Directory not found: {bids_dir}'}), 404
            elif events_file:
                bids_dir = os.path.dirname(os.path.abspath(events_file)) or str(app_root)
            else:
                return jsonify({'error': 'No BIDS directory or events file specified'}), 400

            if events_file:
                if not os.path.isfile(events_file):
                    return jsonify({'error': f'Events file not found: {events_file}'}), 404
                if not events_file.lower().endswith('.tsv'):
                    return jsonify({'error': 'Selected file must be a .tsv file'}), 400

            all_event_files = []
            tasks = set()
            if events_file:
                all_event_files = [events_file]
                detected_task = _extract_task_name(events_file)
                if detected_task:
                    tasks.add(detected_task)
            else:
                for root, _dirs, files in os.walk(bids_dir):
                    for file_name in files:
                        if file_name.endswith('_events.tsv'):
                            full_path = os.path.join(root, file_name)
                            all_event_files.append(full_path)
                            detected_task = _extract_task_name(file_name)
                            if detected_task:
                                tasks.add(detected_task)

            selected_task = ''
            events_files = all_event_files[:]
            if task_filter and not events_file:
                requested_task = task_filter
                events_files = [path for path in all_event_files if _extract_task_name(path) == requested_task]
                if not events_files:
                    return jsonify({'error': f"No events files found for task '{requested_task}'.", 'tasks': sorted(list(tasks))}), 404
                selected_task = requested_task

            sample_file = None
            sample_abs_path = None
            sample_headers = []
            sample_rows = []
            sample_total_rows = 0
            sample_truncated = False
            all_columns = set()
            columns_by_type = {}
            if events_files:
                candidate_files = events_files[:]
                random.shuffle(candidate_files)

                if preview_file:
                    if os.path.isabs(preview_file):
                        preview_abs = os.path.normpath(preview_file)
                    else:
                        preview_abs = os.path.normpath(os.path.join(bids_dir, preview_file))
                    if preview_abs in events_files:
                        candidate_files = [preview_abs] + [file_path for file_path in candidate_files if file_path != preview_abs]

                for chosen in candidate_files:
                    try:
                        with open(chosen, 'r', encoding='utf-8') as file_handle:
                            reader = csv.DictReader(file_handle, delimiter='\t')
                            headers = list(reader.fieldnames or [])
                            if not headers:
                                continue

                            value_sets = {header: set() for header in headers}
                            rows = []
                            total_rows = 0
                            for row in reader:
                                total_rows += 1
                                if preview_max_rows == 0 or len(rows) < preview_max_rows:
                                    rows.append([row.get(header, '') for header in headers])
                                for header in headers:
                                    value = str(row.get(header, '')).strip()
                                    if not value or value.lower() in {'n/a', 'nan'}:
                                        continue
                                    value_sets[header].add(value)

                            sample_abs_path = os.path.abspath(chosen)
                            all_columns.update(headers)
                            for column in headers:
                                if column in ['onset', 'duration', 'framewise_displacement']:
                                    continue
                                values = sorted(list(value_sets.get(column, set())))
                                if values:
                                    columns_by_type[column] = values[:10]

                            sample_headers = headers
                            sample_rows = rows
                            sample_total_rows = total_rows
                            sample_truncated = preview_max_rows != 0 and total_rows > len(rows)
                            break
                    except Exception:
                        continue

            if sample_abs_path:
                try:
                    bids_root = os.path.abspath(bids_dir)
                    if os.path.commonpath([bids_root, sample_abs_path]) == bids_root:
                        sample_file = os.path.relpath(sample_abs_path, bids_root)
                    else:
                        sample_file = sample_abs_path
                except Exception:
                    sample_file = sample_abs_path

            if not selected_task and sample_abs_path:
                selected_task = _extract_task_name(sample_abs_path)

            return jsonify({
                'bids_dir': bids_dir,
                'events_files': len(events_files),
                'columns': sorted(list(all_columns)),
                'columns_by_type': {key: values for key, values in columns_by_type.items()},
                'tasks': sorted(list(tasks)),
                'selected_task': selected_task,
                'sample_file': sample_file,
                'sample_headers': sample_headers,
                'sample_rows': sample_rows,
                'sample_total_rows': sample_total_rows,
                'sample_truncated': sample_truncated,
            })
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500