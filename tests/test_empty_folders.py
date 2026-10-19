"""Derivatives Folder is optional (defaults to the working directory); empty WD/fMRIPrep must be a JSON 400, not a crash."""
import json
from unittest.mock import patch

from bidspm_gui import app
from lib.config import load_config
from lib.preflight import run_preflight_from_config
from lib.project_manager import ProjectManager

EMPTY = {"WD": "", "BIDS_DIR": "", "DERIVATIVES_DIR": "", "FMRIPREP_DIR": "", "SPACE": "MNI", "FWHM": 6, "TASKS": ["x"]}


def test_load_config_defaults_empty_derivatives_to_the_working_directory(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({**EMPTY, "WD": str(tmp_path / "wd"), "BIDS_DIR": "b", "FMRIPREP_DIR": "f"}))
    assert load_config(str(path)).DERIVATIVES_DIR == tmp_path / "wd"


def test_preflight_from_config_copes_with_empty_derivatives_and_folders():
    report = run_preflight_from_config(EMPTY, validator="skip")
    assert report["verdict"] == "blocked"


def test_exported_project_settings_with_empty_derivatives_load(tmp_path):
    pm = ProjectManager(tmp_path / "projects")
    project = pm.create_project("p", config={"output_folder": str(tmp_path / "wd"), "tasks": ["x"], "space": "MNI"})
    exported = pm.export_config(project.id)
    assert exported["DERIVATIVES_DIR"] in ("", None)
    path = tmp_path / "c.json"
    path.write_text(json.dumps(exported))
    assert load_config(str(path)).DERIVATIVES_DIR == tmp_path / "wd"


def test_run_with_empty_folders_is_a_json_400_preflight_report(tmp_path):
    settings = tmp_path / "s.json"
    settings.write_text(json.dumps(EMPTY))
    with patch("webapp.web_execution_api.subprocess.Popen") as popen, \
            patch("lib.config.auto_select_container_config", return_value=None):  # its docker probe is a Popen too
        res = app.test_client().post("/run", json={"actions": ["smooth"], "settings": str(settings), "validator": "skip"})
    assert res.status_code == 400 and res.is_json
    assert res.get_json()["preflight"]["verdict"] == "blocked"
    popen.assert_not_called()
