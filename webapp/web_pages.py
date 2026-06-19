from typing import Callable, List, Optional, Tuple

from flask import Flask, redirect, render_template


ProjectManagerGetter = Callable[[], object]


def _load_page_context(
    project_id: Optional[str],
    get_project_manager: ProjectManagerGetter,
) -> Tuple[Optional[object], List[object]]:
    manager = get_project_manager()
    project = manager.load_project(project_id) if project_id else None
    projects = manager.list_projects()
    return project, projects


def register_page_routes(app: Flask, get_project_manager: ProjectManagerGetter) -> None:
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
        """Render analysis page, optionally with a project loaded."""
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