import json
import os
import re
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, List

from flask import Flask, jsonify, request


PathResolver = Callable[[str], str]
TokenNormalizer = Callable[[Any], List[str]]
SubjectNormalizer = Callable[[Any], List[str]]
ProjectManagerGetter = Callable[[], Any]
SubjectProcessedChecker = Callable[[Any, str, str, str], bool]


def _normalize_fwhm(value: Any) -> Any:
    """Coerce FWHM to an int when it's a whole number.

    bidspm writes ``desc-smthN`` / ``FWHM-N`` on disk using whatever numeric
    literal was in the settings JSON -- a whole-number FWHM (the common case)
    is written without a decimal point (``smth9``, not ``smth9.0``). Embedding
    a Python float here would silently never match those paths.
    """
    try:
        as_float = float(value)
    except (TypeError, ValueError):
        return value
    return int(as_float) if as_float.is_integer() else as_float


def _sort_subject_ids(values: List[str]) -> List[str]:
    def _key(value: str):
        if value.isdigit():
            return (0, int(value), value)
        return (1, value.lower(), value)

    return sorted(values, key=_key)


def _extract_task_from_name(filename: str) -> str:
    match = re.search(r'task-([^_]+)', filename)
    return match.group(1).strip() if match else ''


def _extract_subject_from_path(file_path: Path) -> str:
    for part in file_path.parts:
        if part.startswith('sub-') and len(part) > 4:
            return part[4:]
    return ''


def _scan_subject_task_map(files: List[Path], tasks_filter: List[str]) -> Dict[str, set]:
    task_filter = set(tasks_filter or [])
    subject_tasks: Dict[str, set] = {}

    for file_path in files:
        subject = _extract_subject_from_path(file_path)
        if not subject:
            continue

        task = _extract_task_from_name(file_path.name)
        if task_filter:
            if not task or task not in task_filter:
                continue
        elif not task:
            task = '*'

        subject_tasks.setdefault(subject, set()).add(task or '*')

    return subject_tasks


def _model_tasks_from_file(model_file: str, resolve_fs_path: PathResolver, normalize_token_list: TokenNormalizer) -> List[str]:
    if not model_file:
        return []

    resolved = resolve_fs_path(model_file)
    if not resolved or not os.path.isfile(resolved):
        return []

    try:
        with open(resolved, 'r', encoding='utf-8') as stream:
            model = json.load(stream)
    except Exception:
        return []

    raw_tasks = model.get('Input', {}).get('task', []) if isinstance(model, dict) else []
    return normalize_token_list(raw_tasks)


def _build_stats_subject_coverage_report(
    bids_dir: str,
    fmriprep_dir: str,
    tasks: List[str],
    selected_subjects: List[str],
    model_file: str,
    resolve_fs_path: PathResolver,
    normalize_token_list: TokenNormalizer,
    normalize_subject_ids: SubjectNormalizer,
) -> Dict[str, Any]:
    tasks_considered = normalize_token_list(tasks)
    if not tasks_considered:
        tasks_considered = _model_tasks_from_file(model_file, resolve_fs_path, normalize_token_list)

    selected = normalize_subject_ids(selected_subjects)
    messages: List[str] = []

    resolved_bids = resolve_fs_path(bids_dir) if bids_dir else ''
    resolved_fmriprep = resolve_fs_path(fmriprep_dir) if fmriprep_dir else ''

    bids_path = Path(resolved_bids) if resolved_bids and os.path.isdir(resolved_bids) else None
    fmriprep_path = Path(resolved_fmriprep) if resolved_fmriprep and os.path.isdir(resolved_fmriprep) else None

    if not bids_path:
        messages.append('BIDS folder is missing or not accessible.')
    if not fmriprep_path:
        messages.append('fMRIPrep folder is missing or not accessible.')

    bids_subjects = set()
    fmriprep_subjects = set()
    events_by_subject: Dict[str, set] = {}
    preproc_by_subject: Dict[str, set] = {}

    if bids_path:
        bids_subjects = {
            sub_dir.name[4:]
            for sub_dir in bids_path.glob('sub-*')
            if sub_dir.is_dir() and len(sub_dir.name) > 4
        }

        events_files = sorted(bids_path.glob('sub-*/ses-*/func/*_events.tsv')) + sorted(bids_path.glob('sub-*/func/*_events.tsv'))
        events_by_subject = _scan_subject_task_map(list(dict.fromkeys(events_files)), tasks_considered)

    if fmriprep_path:
        fmriprep_subjects = {
            sub_dir.name[4:]
            for sub_dir in fmriprep_path.glob('sub-*')
            if sub_dir.is_dir() and len(sub_dir.name) > 4
        }

        preproc_files = sorted(fmriprep_path.glob('sub-*/ses-*/func/*desc-preproc_bold.nii*')) + sorted(fmriprep_path.glob('sub-*/func/*desc-preproc_bold.nii*'))
        preproc_by_subject = _scan_subject_task_map(list(dict.fromkeys(preproc_files)), tasks_considered)

    expected_subjects = set(selected) if selected else (
        bids_subjects |
        fmriprep_subjects |
        set(events_by_subject.keys()) |
        set(preproc_by_subject.keys())
    )

    if not expected_subjects:
        messages.append('No subjects detected from BIDS/fMRIPrep folders.')

    ready_subjects = []
    missing_subjects = []

    for subject in _sort_subject_ids(list(expected_subjects)):
        issues = []

        if subject not in bids_subjects:
            issues.append('missing BIDS subject folder')

        if subject not in fmriprep_subjects:
            issues.append('missing fMRIPrep subject folder')

        event_tasks = events_by_subject.get(subject, set())
        preproc_tasks = preproc_by_subject.get(subject, set())

        if tasks_considered:
            missing_event_tasks = [task for task in tasks_considered if task not in event_tasks]
            missing_preproc_tasks = [task for task in tasks_considered if task not in preproc_tasks]

            if missing_event_tasks:
                issues.append(f"missing events for task(s): {', '.join(missing_event_tasks)}")
            if missing_preproc_tasks:
                issues.append(f"missing fMRIPrep preproc for task(s): {', '.join(missing_preproc_tasks)}")
        else:
            if not event_tasks:
                issues.append('no events files found')
            if not preproc_tasks:
                issues.append('no fMRIPrep preproc BOLD files found')

        if issues:
            missing_subjects.append({'subject': subject, 'issues': issues})
        else:
            ready_subjects.append(subject)

    missing_subject_ids = [entry['subject'] for entry in missing_subjects]

    return {
        'ok': len(missing_subjects) == 0 and len(expected_subjects) > 0,
        'non_blocking': True,
        'tasks_considered': tasks_considered,
        'selected_subjects': selected,
        'paths': {
            'bids_dir': resolved_bids,
            'fmriprep_dir': resolved_fmriprep,
            'model_file': resolve_fs_path(model_file) if model_file else '',
        },
        'source_subject_counts': {
            'bids': len(bids_subjects),
            'fmriprep': len(fmriprep_subjects),
            'events': len(events_by_subject),
            'preproc': len(preproc_by_subject),
        },
        'summary': {
            'total_subjects': len(expected_subjects),
            'ready_subjects': len(ready_subjects),
            'missing_subjects': len(missing_subjects),
        },
        'ready_subjects': ready_subjects,
        'missing_subjects': missing_subjects,
        'missing_subject_ids': missing_subject_ids,
        'messages': messages,
    }


def _build_participants_status_report(
    bids_dir: str,
    fmriprep_dir: str,
    derivatives_dir: str,
    actions: List[str],
    tasks: List[str],
    space: str,
    fwhm: Any,
    model_file: str,
    resolve_fs_path: PathResolver,
    normalize_token_list: TokenNormalizer,
    check_subject_processed: SubjectProcessedChecker,
) -> Dict[str, Any]:
    """Report, per discovered participant, whether outputs already exist for the
    selected actions/tasks (``computed``) or still need to be run (``missing``).

    Mirrors the skip-if-processed logic in ``lib.core.Pipeline`` so the GUI's
    picture of "done" matches what a real run would actually skip.
    """
    tasks_considered = normalize_token_list(tasks)
    if not tasks_considered:
        tasks_considered = _model_tasks_from_file(model_file, resolve_fs_path, normalize_token_list)

    per_subject_actions = [a for a in normalize_token_list(actions) if a in ('smooth', 'stats')]

    resolved_bids = resolve_fs_path(bids_dir) if bids_dir else ''
    resolved_fmriprep = resolve_fs_path(fmriprep_dir) if fmriprep_dir else ''
    resolved_derivatives = resolve_fs_path(derivatives_dir) if derivatives_dir else ''

    bids_path = Path(resolved_bids) if resolved_bids and os.path.isdir(resolved_bids) else None
    fmriprep_path = Path(resolved_fmriprep) if resolved_fmriprep and os.path.isdir(resolved_fmriprep) else None

    bids_subjects = {
        sub_dir.name[4:]
        for sub_dir in bids_path.glob('sub-*')
        if sub_dir.is_dir() and len(sub_dir.name) > 4
    } if bids_path else set()

    fmriprep_subjects = {
        sub_dir.name[4:]
        for sub_dir in fmriprep_path.glob('sub-*')
        if sub_dir.is_dir() and len(sub_dir.name) > 4
    } if fmriprep_path else set()

    all_subjects = _sort_subject_ids(list(bids_subjects | fmriprep_subjects))

    can_evaluate = bool(per_subject_actions) and bool(tasks_considered) and bool(resolved_derivatives)
    fake_config = SimpleNamespace(
        DERIVATIVES_DIR=Path(resolved_derivatives) if resolved_derivatives else Path('.'),
        SPACE=space or '',
        FWHM=fwhm,
    )

    computed_subjects: List[str] = []
    missing_subjects: List[str] = []
    details: List[Dict[str, Any]] = []

    for subject in all_subjects:
        if not can_evaluate:
            details.append({'subject': subject, 'status': 'unknown', 'pending': []})
            continue

        pending = [
            f'{action}:{task}'
            for action in per_subject_actions
            for task in tasks_considered
            if not check_subject_processed(fake_config, subject, task, action)
        ]

        if pending:
            missing_subjects.append(subject)
            details.append({'subject': subject, 'status': 'missing', 'pending': pending})
        else:
            computed_subjects.append(subject)
            details.append({'subject': subject, 'status': 'computed', 'pending': []})

    return {
        'evaluable': can_evaluate,
        'tasks_considered': tasks_considered,
        'actions_considered': per_subject_actions,
        'paths': {
            'bids_dir': resolved_bids,
            'fmriprep_dir': resolved_fmriprep,
            'derivatives_dir': resolved_derivatives,
        },
        'subjects': all_subjects,
        'computed_subjects': computed_subjects,
        'missing_subjects': missing_subjects,
        'details': details,
        'summary': {
            'total': len(all_subjects),
            'computed': len(computed_subjects),
            'missing': len(missing_subjects),
        },
    }


def register_utility_stats_routes(
    app: Flask,
    get_project_manager: ProjectManagerGetter,
    resolve_fs_path: PathResolver,
    normalize_token_list: TokenNormalizer,
    normalize_subject_ids: SubjectNormalizer,
    check_subject_processed: SubjectProcessedChecker,
) -> None:
    @app.route('/api/detect-spaces', methods=['POST'])
    def api_detect_spaces():
        try:
            data = request.json or {}
            fmriprep_path = data.get('path', '').strip()

            if not fmriprep_path:
                return jsonify({'spaces': [], 'error': 'No path provided'})

            path = Path(fmriprep_path)
            if not path.exists():
                return jsonify({'spaces': [], 'error': 'Path not found'})

            available_spaces = []
            space_patterns = [
                'MNI152NLin2009cAsym', 'MNI152NLin6Asym', 'MNI152NLin2009cSym',
                'MNI152NLin6Sym', 'MNIPediatricAsym', 'T1w', 'fsaverage',
                'fsLR', 'fsnative', 'anat',
            ]

            for space in space_patterns:
                if list(path.glob(f'**/*space-{space}*.nii*')):
                    available_spaces.append(space)

            return jsonify({'spaces': available_spaces})
        except Exception as exc:
            return jsonify({'spaces': [], 'error': str(exc)})

    @app.route('/api/scan_masks', methods=['GET'])
    def api_scan_masks():
        preproc_path = request.args.get('path', '').strip()
        if not preproc_path:
            return jsonify({'error': 'path parameter required'}), 400
        path = Path(preproc_path)
        if not path.exists():
            return jsonify({'error': f'Path not found: {preproc_path}'}), 404

        masks: dict = {}
        for nii in path.glob('**/*desc-brain_mask.nii*'):
            datatype = nii.parent.name
            if datatype not in ('func', 'anat'):
                datatype = 'unknown'

            entities = {}
            for entity in ('task', 'acq', 'space'):
                match = re.search(rf'{entity}-([^_]+)', nii.name)
                if match:
                    entities[entity] = match.group(1)

            if datatype not in masks:
                masks[datatype] = {'datatype': datatype, 'entities': entities, 'example': nii.name, 'count': 0}
            masks[datatype]['count'] += 1

        return jsonify(list(masks.values()))

    @app.route('/api/preflight/tools', methods=['GET'])
    def api_preflight_tools():
        results = {}
        for tool in ('docker', 'apptainer', 'singularity', 'octave'):
            path = shutil.which(tool)
            results[tool] = {'available': path is not None, 'path': path or ''}
        return jsonify(results)

    @app.route('/api/stats_subject_coverage', methods=['POST'])
    def api_stats_subject_coverage():
        try:
            data = request.json or {}
            project_id = str(data.get('project_id') or '').strip()
            project_manager = get_project_manager()
            project = project_manager.load_project(project_id) if project_id else None

            if project_id and not project:
                return jsonify({'error': 'Project not found'}), 404

            config = project.config if project else None

            bids_dir = str(data.get('bids_dir') or '').strip() if 'bids_dir' in data else (config.bids_folder if config else '')
            fmriprep_dir = str(data.get('fmriprep_dir') or '').strip() if 'fmriprep_dir' in data else (config.fmriprep_folder if config else '')
            model_file = str(data.get('model_file') or '').strip() if 'model_file' in data else (config.models_file if config else '')

            if 'tasks' in data:
                tasks = normalize_token_list(data.get('tasks'))
            else:
                tasks = normalize_token_list(config.tasks if config else [])

            subjects = normalize_subject_ids(data.get('subjects')) if 'subjects' in data else []

            report = _build_stats_subject_coverage_report(
                bids_dir=bids_dir,
                fmriprep_dir=fmriprep_dir,
                tasks=tasks,
                selected_subjects=subjects,
                model_file=model_file,
                resolve_fs_path=resolve_fs_path,
                normalize_token_list=normalize_token_list,
                normalize_subject_ids=normalize_subject_ids,
            )
            report['project_id'] = project_id or None
            return jsonify(report)
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500

    @app.route('/api/participants_status', methods=['POST'])
    def api_participants_status():
        try:
            data = request.json or {}
            project_id = str(data.get('project_id') or '').strip()
            project_manager = get_project_manager()
            project = project_manager.load_project(project_id) if project_id else None

            if project_id and not project:
                return jsonify({'error': 'Project not found'}), 404

            config = project.config if project else None

            bids_dir = str(data.get('bids_dir') or '').strip() if 'bids_dir' in data else (config.bids_folder if config else '')
            fmriprep_dir = str(data.get('fmriprep_dir') or '').strip() if 'fmriprep_dir' in data else (config.fmriprep_folder if config else '')
            derivatives_dir = str(data.get('derivatives_dir') or '').strip() if 'derivatives_dir' in data else (
                (config.derivatives_folder or config.output_folder) if config else ''
            )
            model_file = str(data.get('model_file') or '').strip() if 'model_file' in data else (config.models_file if config else '')

            actions = normalize_token_list(data.get('actions')) if 'actions' in data else normalize_token_list(config.actions if config else [])
            tasks = normalize_token_list(data.get('tasks')) if 'tasks' in data else normalize_token_list(config.tasks if config else [])
            space = str(data.get('space') or '').strip() or (config.space if config else '') or 'MNI152NLin2009cAsym'

            raw_fwhm = data.get('fwhm') if data.get('fwhm') not in (None, '') else (config.fwhm if config else 6)
            fwhm = _normalize_fwhm(raw_fwhm)

            report = _build_participants_status_report(
                bids_dir=bids_dir,
                fmriprep_dir=fmriprep_dir,
                derivatives_dir=derivatives_dir,
                actions=actions,
                tasks=tasks,
                space=space,
                fwhm=fwhm,
                model_file=model_file,
                resolve_fs_path=resolve_fs_path,
                normalize_token_list=normalize_token_list,
                check_subject_processed=check_subject_processed,
            )
            report['project_id'] = project_id or None
            return jsonify(report)
        except Exception as exc:
            return jsonify({'error': str(exc)}), 500
