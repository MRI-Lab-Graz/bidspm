import json
from unittest.mock import MagicMock, patch

from bidspm_gui import app
from tests.preflight_support import make_trees

BLOCKED = {"verdict": "blocked", "checks": [{"id": "bids_dir", "severity": "error", "subject": None, "message": "m", "fix": "f"}]}


def cfg(tmp_path, **over):
    bids, fmriprep = make_trees(tmp_path)
    return {"BIDS_DIR": str(bids), "FMRIPREP_DIR": str(fmriprep), "SPACE": "MNI", "TASKS": ["x"], **over}


def test_api_preflight_returns_the_report(tmp_path):
    res = app.test_client().post("/api/preflight", json={"config": cfg(tmp_path), "validator": "skip"})
    assert res.status_code == 200 and res.get_json()["verdict"] == "warnings"


def test_api_preflight_reports_blocking_problems(tmp_path):
    res = app.test_client().post("/api/preflight", json={"config": cfg(tmp_path, SPACE="T1w"), "validator": "skip"})
    assert res.get_json()["verdict"] == "blocked"


def test_api_preflight_tolerates_non_dict_config():
    res = app.test_client().post("/api/preflight", json={"config": "oops", "validator": "skip"})
    assert res.status_code == 200 and res.get_json()["verdict"] == "blocked"


def test_run_refuses_to_start_when_preflight_is_blocked(tmp_path):
    settings = tmp_path / "s.json"
    settings.write_text(json.dumps(cfg(tmp_path)))
    with patch("webapp.web_execution_api.run_preflight_from_config", return_value=BLOCKED), \
         patch("webapp.web_execution_api.subprocess.Popen") as popen:
        res = app.test_client().post("/run", json={"actions": ["stats"], "settings": str(settings)})
    assert res.status_code == 400 and res.get_json()["preflight"]["verdict"] == "blocked"
    popen.assert_not_called()


def test_run_does_not_gate_report_or_bms_actions(tmp_path):
    settings = tmp_path / "s.json"
    settings.write_text(json.dumps(cfg(tmp_path)))
    with patch("webapp.web_execution_api.run_preflight_from_config") as pf, \
         patch("webapp.web_execution_api.subprocess.Popen", return_value=MagicMock(pid=4242)), \
         patch("webapp.web_execution_api.threading.Thread"):
        app.test_client().post("/run", json={"actions": ["report"], "settings": str(settings)})
    pf.assert_not_called()


READY = {"verdict": "ready", "checks": []}


def _post_run(client, **body):
    return client.post("/run", json=body)


def test_blocked_run_leaves_no_generated_settings(tmp_path):
    import bidspm_gui
    from lib.project_manager import ProjectManager
    pm = ProjectManager(tmp_path / "projects")
    project = pm.create_project("p", config={"output_folder": str(tmp_path / "out"), "tasks": ["x"]})
    with patch.object(bidspm_gui, "project_manager", pm), \
         patch("webapp.web_execution_api.run_preflight_from_config", return_value=BLOCKED):
        res = _post_run(app.test_client(), actions=["stats"], project_id=project.id, subjects_override=["01"])
    assert res.status_code == 400
    assert not list(pm.get_project_configs_dir(project.id).glob("run_settings*"))


def test_model_validation_failure_leaves_no_generated_settings(tmp_path):
    import bidspm_gui
    from lib.project_manager import ProjectManager
    pm = ProjectManager(tmp_path / "projects")
    project = pm.create_project("p", config={"output_folder": str(tmp_path / "out"), "tasks": ["x"]})
    res_model = tmp_path / "missing.json"
    with patch.object(bidspm_gui, "project_manager", pm):
        res = _post_run(app.test_client(), actions=["stats"], project_id=project.id, model=str(res_model))
    assert res.status_code == 400
    assert not list(pm.get_project_configs_dir(project.id).glob("run_settings*"))


def test_run_settings_that_is_not_an_object_is_a_400(tmp_path):
    settings = tmp_path / "s.json"
    settings.write_text("[]")
    res = _post_run(app.test_client(), actions=["stats"], settings=str(settings))
    assert res.status_code == 400 and "settings" in res.get_json()["error"]


def test_run_without_settings_gates_on_default_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.json").write_text(json.dumps({"BIDS_DIR": "x"}))
    with patch("webapp.web_execution_api.run_preflight_from_config", return_value=BLOCKED) as pf, \
         patch("webapp.web_execution_api.subprocess.Popen") as popen:
        res = _post_run(app.test_client(), actions=["stats"])
    assert res.status_code == 400 and pf.call_args.args[0] == {"BIDS_DIR": "x"}
    popen.assert_not_called()


def test_run_without_settings_and_no_default_skips_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with patch("webapp.web_execution_api.run_preflight_from_config") as pf, \
         patch("webapp.web_execution_api.subprocess.Popen", return_value=MagicMock(pid=1)), \
         patch("webapp.web_execution_api.threading.Thread"):
        _post_run(app.test_client(), actions=["stats"])
    pf.assert_not_called()


def test_run_passes_validator_through(tmp_path):
    settings = tmp_path / "s.json"
    settings.write_text("{}")
    with patch("webapp.web_execution_api.run_preflight_from_config", return_value=BLOCKED) as pf:
        _post_run(app.test_client(), actions=["stats"], settings=str(settings), validator="skip")
        assert pf.call_args.kwargs["validator"] == "skip"
        _post_run(app.test_client(), actions=["stats"], settings=str(settings))
        assert pf.call_args.kwargs["validator"] == "prism"


def test_run_with_bogus_validator_is_blocked(tmp_path):
    settings = tmp_path / "s.json"
    settings.write_text(json.dumps(cfg(tmp_path)))
    with patch("webapp.web_execution_api.subprocess.Popen") as popen:
        res = _post_run(app.test_client(), actions=["stats"], settings=str(settings), validator="bogus")
    assert res.status_code == 400 and res.get_json()["preflight"]["verdict"] == "blocked"
    popen.assert_not_called()
