import os
from typing import Callable, List, Optional, Tuple

from flask import Flask, redirect, render_template


ProjectManagerGetter = Callable[[], object]


def _load_page_context(
    project_id: Optional[str],
    get_project_manager: ProjectManagerGetter,
) -> Tuple[Optional[object], List[object]]:
    manager = get_project_manager()
    project = manager.load_project(project_id) if project_id else None
    if project:
        manager.set_current_project_id(project_id)
    projects = manager.list_projects()
    return project, projects


def register_page_routes(app: Flask, get_project_manager: ProjectManagerGetter) -> None:
    @app.route('/')
    @app.route('/projects')
    def projects_page():
        """Render projects management page."""
        projects = get_project_manager().list_projects()
        return render_template(
            'projects.html',
            projects=projects,
            project_count=len(projects),
        )

    @app.route('/analysis')
    @app.route('/analysis/<project_id>')
    def analysis_page(project_id: Optional[str] = None):
        """Render analysis page, optionally with a project loaded.

        With no project id in the URL, resume the last project opened
        (tracked in ~/.bidspm/current_project.json) if one still exists.
        """
        manager = get_project_manager()
        if not project_id:
            last_project_id = manager.get_current_project_id()
            if last_project_id and manager.load_project(last_project_id):
                return redirect(f'/analysis/{last_project_id}')
        project, projects = _load_page_context(project_id, get_project_manager)
        return render_template(
            'analysis.html',
            project=project,
            projects=projects,
            current_project_id=project_id,
            current_project=project,
        )

    @app.route('/model_editor')
    @app.route('/model_editor/<project_id>')
    def model_editor_page(project_id: Optional[str] = None):
        """Retired standalone model editor -- the Model Workspace on /analysis is
        now the single editing surface. Kept registered (as a redirect) so old
        links/bookmarks don't 404.
        """
        target = f'/analysis/{project_id}' if project_id else '/analysis'
        return redirect(target)

    @app.route('/transformer-builder')
    @app.route('/transformer-builder/<project_id>')
    def transformer_builder_page(project_id: Optional[str] = None):
        """Visual transformer builder for creating BIDS model transformations."""
        project, projects = _load_page_context(project_id, get_project_manager)
        return render_template(
            'transformer_builder.html',
            project=project,
            projects=projects,
            current_project_id=project_id,
            current_project=project,
        )

    @app.route('/model-wizard')
    @app.route('/model-wizard/<project_id>')
    def model_wizard_page(project_id: Optional[str] = None):
        """Guided model builder; the work happens in /api/wizard/*."""
        project, projects = _load_page_context(project_id, get_project_manager)
        cfg = project.config if project else None
        models_file = (cfg.models_file if cfg else '') or ''
        return render_template(
            'model_wizard.html',
            project=project,
            projects=projects,
            current_project_id=project_id,
            current_project=project,
            wizard_context={
                'projectId': project_id or '',
                'bidsDir': (cfg.bids_folder if cfg else '') or '',
                'fmriprepDir': (cfg.fmriprep_folder if cfg else '') or '',
                'space': (cfg.space if cfg else '') or '',
                'modelsDir': os.path.dirname(models_file) if models_file else '',
            },
        )
