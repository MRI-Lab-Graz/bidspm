"""`~` in BIDS_DIR / FMRIPREP_DIR / MODELS_FILE: every entry point (job, sync route, CLI, /run gate) agrees."""
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from bidspm_gui import app
from lib.preflight import signature
from tests.preflight_support import make_trees, write_model
from tests.test_preflight_jobs import WAIT, parse
from webapp import web_preflight_api as api

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def tilde_cfg(home):
    make_trees(home / "proj")
    write_model(home / "proj")
    return {"BIDS_DIR": "~/proj/bids", "FMRIPREP_DIR": " ~/proj/fmriprep ", "SPACE": "MNI", "TASKS": ["x"],
            "MODELS_FILE": "~/proj/model.json"}


def test_sync_route_accepts_tilde_paths(home):
    report = app.test_client().post("/api/preflight", json={"config": tilde_cfg(home), "validator": "skip"}).get_json()
    assert report["verdict"] != "blocked", report["checks"]


def test_job_route_accepts_tilde_paths(home):
    client = app.test_client()
    job_id = client.post("/api/preflight/start", json={"config": tilde_cfg(home), "validator": "skip"}).get_json()["id"]
    events = parse(client.get(f"/api/preflight/stream/{job_id}").get_data(as_text=True))
    assert events[-1][1]["report"]["verdict"] != "blocked", events[-1][1]["report"]["checks"]


def test_cli_preflight_accepts_tilde_paths(home):
    path = home / "cfg.json"
    path.write_text(json.dumps(tilde_cfg(home)))
    proc = subprocess.run([sys.executable, "bidspm.py", "--preflight", "--skip-validator", "-s", str(path)],
                          cwd=ROOT, capture_output=True, text=True, env={**os.environ, "HOME": str(home)})
    assert proc.returncode == 0, proc.stdout
    assert json.loads(proc.stdout)["verdict"] != "blocked"


def test_signature_is_equal_for_tilde_and_absolute_paths(home):
    tilde = tilde_cfg(home)
    absolute = {**tilde, "BIDS_DIR": str(home / "proj/bids"), "FMRIPREP_DIR": str(home / "proj/fmriprep"),
                "MODELS_FILE": str(home / "proj/model.json")}
    args = ("", "skip", ["stats"], False)
    assert signature(tilde, *args) == signature(absolute, *args)
    assert signature(tilde, "~/proj/model.json", "skip", ["stats"], False) == signature(absolute, *args[:1], *args[1:])


def test_form_job_then_run_gate_with_tilde_vs_absolute_reuses_the_result(home, tmp_path):
    tilde = tilde_cfg(home)
    absolute = {**tilde, "BIDS_DIR": str(home / "proj/bids"), "FMRIPREP_DIR": str(home / "proj/fmriprep"),
                "MODELS_FILE": str(home / "proj/model.json")}
    client = app.test_client()
    body = {"config": tilde, "validator": "skip", "actions": ["stats"], "skip_model_validation": True}
    job_id = client.post("/api/preflight/start", json=body).get_json()["id"]
    client.get(f"/api/preflight/stream/{job_id}").get_data()
    api._JOBS[job_id].thread.join(WAIT)
    settings = home / "export.json"
    settings.write_text(json.dumps(absolute))
    with patch("webapp.web_execution_api.run_preflight_from_config") as rerun, \
         patch("webapp.web_execution_api.subprocess.Popen"):
        client.post("/run", json={"actions": ["stats"], "settings": str(settings), "validator": "skip",
                                  "skip_validation": True})
    rerun.assert_not_called()
