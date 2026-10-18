"""F12/L1/M14: project import validation and project routes with hostile values."""
import json

import pytest

import bidspm_gui
from bidspm_gui import app
from lib.project_manager import ProjectManager


@pytest.fixture
def env(tmp_path, monkeypatch):
    manager = ProjectManager(projects_dir=tmp_path / "projects")
    monkeypatch.setattr(bidspm_gui, "project_manager", manager)
    project = manager.create_project("p", "", {"bids_folder": "/keep/bids", "tasks": ["t"], "fwhm": 8.0, "verbosity": 1})
    return {"manager": manager, "id": project.id, "c": app.test_client(), "tmp": tmp_path}


def do_import(env, text):
    f = env["tmp"] / "imp.json"
    f.write_text(text, encoding="utf-8")
    return env["c"].post(f"/api/projects/{env['id']}/import", json={"path": str(f)})


def config_of(env):
    return env["manager"].load_project(env["id"]).config.to_dict()


@pytest.mark.parametrize("text", ['{"BIDS_DIR": "/x", "FWHM": NaN}', '{"FWHM": Infinity}', '{"FWHM": -Infinity}', "[]", "5", '"str"', "null", "",
                                  "{bad", '{"BIDS_DIR": 5}', '{"BIDS_DIR": null}', '{"TASKS": "motor"}', '{"TASKS": [1]}', '{"FWHM": "x"}',
                                  '{"FWHM": true}', '{"VERBOSITY": 1.5}', '{"VERBOSITY": "2"}', '{"container_type": ["a"]}',
                                  '{"pilot": "no"}'])
def test_bad_import_is_a_400_and_leaves_the_config_unchanged(env, text):
    before = config_of(env)
    res = do_import(env, text)
    assert res.is_json and res.status_code == 400, (text, res.status_code, res.data[:100])
    assert res.get_json()["error"]
    assert config_of(env) == before
    assert env["c"].get(f"/api/projects/{env['id']}").status_code == 200  # still loadable


def test_error_names_the_offending_field(env):
    assert "FWHM" in do_import(env, '{"FWHM": "x"}').get_json()["error"]
    assert "TASKS" in do_import(env, '{"TASKS": "motor"}').get_json()["error"]


def test_good_import_ignores_unknown_keys_and_accepts_bom(env):
    res = do_import(env, '﻿{"BIDS_DIR": "/new/bids", "FWHM": 4, "TASKS": ["a", "b"], "VERBOSITY": 0, "bogus": [1], "to_dict": 2}')
    assert res.status_code == 200
    cfg = config_of(env)
    assert cfg["bids_folder"] == "/new/bids" and cfg["fwhm"] == 4 and cfg["tasks"] == ["a", "b"] and cfg["verbosity"] == 0


def test_import_directory_is_400(env):
    res = env["c"].post(f"/api/projects/{env['id']}/import", json={"path": str(env["tmp"])})
    assert res.is_json and res.status_code == 400


@pytest.mark.parametrize("name", [None, 5, ["x"], {"a": 1}, True])
def test_non_string_names_are_400(env, name):
    res = env["c"].post("/api/projects", json={"name": name})
    assert res.is_json and res.status_code == 400
    before = env["manager"].load_project(env["id"]).name
    res = env["c"].put(f"/api/projects/{env['id']}", json={"name": name})
    assert res.is_json and res.status_code == 400
    assert env["manager"].load_project(env["id"]).name == before


def test_non_string_description_is_400(env):
    assert env["c"].post("/api/projects", json={"name": "ok", "description": 5}).status_code == 400
    assert env["c"].put(f"/api/projects/{env['id']}", json={"description": ["x"]}).status_code == 400


@pytest.mark.parametrize("bad", [5, "a\x00b", ["x"], {"a": 1}, True])
def test_card_preflight_survives_a_bad_bids_folder(env, bad):
    # the stored value is bad (hand-edited project.json, older version): bypass the API's own validation
    project = env["manager"].load_project(env["id"])
    project.config.bids_folder = bad
    project.config.fmriprep_folder = bad
    env["manager"].save_project(project)
    res = env["c"].get(f"/api/projects/{env['id']}/preflight")
    assert res.status_code == 200 and res.is_json
    body = res.get_json()
    assert body["bids_folder"]["status"] == "error" and "invalid" in body["bids_folder"]["message"].lower()
    assert body["fmriprep_folder"]["status"] == "error"
    assert env["c"].get("/api/projects").status_code == 200
