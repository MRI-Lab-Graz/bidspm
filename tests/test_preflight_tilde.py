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
    events = parse(client.get(f"/api/preflight/stream/{job_id}").get_data(as_text=True))
    assert events[-1][1]["report"]["verdict"] in ("ready", "warnings"), events[-1][1]["report"]
    api._JOBS[job_id].thread.join(WAIT)
    settings = home / "export.json"
    settings.write_text(json.dumps(absolute))
    with patch("webapp.web_execution_api.run_preflight_from_config") as rerun, \
         patch("webapp.web_execution_api.subprocess.Popen") as popen:
        popen.return_value.pid = 4242
        client.post("/run", json={"actions": ["stats"], "settings": str(settings), "validator": "skip",
                                  "skip_validation": True})
    rerun.assert_not_called()


# --- relative MODELS_FILE: ONE resolver shared by the Pipeline and the readiness check ---
def _rel_cfg(tmp_path, deriv="derivatives", **extra):
    make_trees(tmp_path / "ds")
    cfg = {"BIDS_DIR": str(tmp_path / "ds" / "bids"), "FMRIPREP_DIR": str(tmp_path / "ds" / "fmriprep"),
           "SPACE": "MNI", "TASKS": ["x"], "WD": str(tmp_path / "wd"), "MODELS_FILE": "m.json", **extra}
    if deriv:
        cfg["DERIVATIVES_DIR"] = str(tmp_path / deriv)
    return cfg


def _bad_model(folder):
    folder.mkdir(parents=True)
    (folder / "m.json").write_text("not json")


def test_relative_model_is_found_under_derivatives_models_by_preflight_and_signature(tmp_path, monkeypatch):
    from lib.preflight import run_preflight_from_config
    monkeypatch.chdir(tmp_path)  # cwd has no m.json
    cfg = _rel_cfg(tmp_path)
    _bad_model(tmp_path / "derivatives" / "models")
    report = run_preflight_from_config(cfg, validator="skip")
    assert any(c["id"].startswith("model") for c in report["checks"]), report["checks"]  # the file's content was read
    assert not any("not found" in c["message"] for c in report["checks"]), report["checks"]
    a = signature(cfg, "", "skip", None, False)
    (tmp_path / "derivatives" / "models" / "m.json").write_text("{}")
    assert signature(cfg, "", "skip", None, False) != a  # hashes the same file the check read


def test_empty_derivatives_falls_back_to_wd_like_load_config(tmp_path, monkeypatch):
    from lib.model_path import resolve_model_file
    monkeypatch.chdir(tmp_path)
    (tmp_path / "wd" / "models").mkdir(parents=True)
    (tmp_path / "wd" / "models" / "m.json").write_text("{}")
    cfg = _rel_cfg(tmp_path, deriv=None, DERIVATIVES_DIR="  ")
    from lib.preflight import model_path_from_config
    assert model_path_from_config(cfg) == str(tmp_path / "wd" / "models" / "m.json")
    assert resolve_model_file("m.json", tmp_path / "wd") == tmp_path / "wd" / "models" / "m.json"


def test_pipeline_uses_the_same_resolver(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from lib.core import Pipeline
    monkeypatch.chdir(tmp_path)
    (tmp_path / "derivatives" / "models").mkdir(parents=True)
    (tmp_path / "derivatives" / "models" / "m.json").write_text("{}")
    p = Pipeline.__new__(Pipeline)
    p.options = SimpleNamespace(model_file=None, actions=[])
    p.config = SimpleNamespace(MODELS_FILE="m.json", DERIVATIVES_DIR=tmp_path / "derivatives")
    p._log_error = lambda *a, **k: None
    p.warnings = []
    try:
        p._resolve_model_file()
    except Exception:
        pass
    assert p.model_file_path == tmp_path / "derivatives" / "models" / "m.json"


def test_absolute_tilde_and_cwd_paths_are_unchanged(tmp_path, monkeypatch):
    from lib.model_path import resolve_model_file
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    assert resolve_model_file("~/a.json", tmp_path / "d") == tmp_path / "a.json"
    assert resolve_model_file(str(tmp_path / "x.json"), tmp_path / "d") == tmp_path / "x.json"
    (tmp_path / "m.json").write_text("{}")  # config order: derivatives first, cwd as fallback
    assert resolve_model_file("m.json", tmp_path / "d") == (tmp_path / "m.json").resolve()
    (tmp_path / "d" / "models").mkdir(parents=True)
    (tmp_path / "d" / "models" / "m.json").write_text("{}")
    assert resolve_model_file("m.json", tmp_path / "d") == tmp_path / "d" / "models" / "m.json"
    assert resolve_model_file("m.json", tmp_path / "d", cwd_first=True) == (tmp_path / "m.json").resolve()
