"""Project create/PUT type-check the config like the import does; bad bodies are 400 JSON, never 500."""
import pytest

import bidspm_gui
from bidspm_gui import app
from lib.project_manager import ProjectManager
from webapp.web_projects_api import _build_project_preflight_results


@pytest.fixture
def env(tmp_path, monkeypatch):
    manager = ProjectManager(projects_dir=tmp_path / "projects")
    monkeypatch.setattr(bidspm_gui, "project_manager", manager)
    project = manager.create_project("p", "", {"bids_folder": "/keep/bids", "fwhm": 8.0})
    return {"manager": manager, "id": project.id, "c": app.test_client()}


BAD = [("fwhm", "abc"), ("bids_folder", 7), ("tasks", "motor"), ("verbosity", [1]), ("pilot", "no")]


@pytest.mark.parametrize("field,value", BAD)
def test_create_refuses_a_wrongly_typed_config_value(env, field, value):
    res = env["c"].post("/api/projects", json={"name": "n", "config": {field: value}})
    assert res.status_code == 400 and res.is_json and field in res.get_json()["error"]
    assert len(env["manager"].list_projects()) == 1


@pytest.mark.parametrize("field,value", BAD)
def test_put_refuses_a_wrongly_typed_config_value(env, field, value):
    res = env["c"].put(f"/api/projects/{env['id']}", json={"config": {field: value}})
    assert res.status_code == 400 and res.is_json and field in res.get_json()["error"]
    assert env["manager"].load_project(env["id"]).config.fwhm == 8.0


@pytest.mark.parametrize("body", [[1, 2], "str", 5])
def test_non_object_bodies_are_400_json(env, body):
    for res in (env["c"].post("/api/projects", json=body), env["c"].put(f"/api/projects/{env['id']}", json=body)):
        assert res.status_code == 400 and res.is_json


@pytest.mark.parametrize("config", ["str", [1], 5])
def test_non_object_config_is_400_json(env, config):
    assert env["c"].put(f"/api/projects/{env['id']}", json={"config": config}).status_code == 400
    assert env["c"].post("/api/projects", json={"name": "n", "config": config}).status_code == 400


def test_non_json_body_is_400_json(env):
    for res in (env["c"].post("/api/projects", data="not json", content_type="application/json"),
                env["c"].put(f"/api/projects/{env['id']}", data="{bad", content_type="application/json")):
        assert res.status_code == 400 and res.is_json


def test_good_config_still_saves(env):
    res = env["c"].put(f"/api/projects/{env['id']}", json={"config": {"fwhm": 4, "tasks": ["a"], "bids_folder": "/x"}})
    assert res.status_code == 200
    assert env["manager"].load_project(env["id"]).config.tasks == ["a"]


def test_card_preflight_survives_a_name_over_255_characters(env):
    config = env["manager"].load_project(env["id"]).config
    config.bids_folder = "/" + "a" * 300
    config.fmriprep_folder = "/tmp/" + "b" * 300
    config.derivatives_folder = "/tmp/" + "c" * 300
    r = _build_project_preflight_results(config)
    assert r["bids_folder"] == {"status": "error", "message": "Path invalid"}
    assert r["fmriprep_folder"]["message"] == "Path invalid"


def test_null_config_on_put_is_400_and_on_create_is_allowed(env):
    assert env["c"].put(f"/api/projects/{env['id']}", json={"config": None}).status_code == 400
    assert env["c"].post("/api/projects", json={"name": "n", "config": None}).status_code == 201
