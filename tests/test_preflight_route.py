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
