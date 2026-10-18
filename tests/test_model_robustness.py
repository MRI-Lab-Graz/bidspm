"""M1/M2: a broken model path or body is a check item / JSON 4xx, never an exception, an HTML 500 or leaked internals."""
import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from bidspm_gui import app
from lib.core import validate_bids_model
from lib.preflight import check_model, run_preflight
from tests.preflight_support import make_trees, write_model
from tests.test_preflight_jobs import RUNNER, finished, parse, start  # noqa: F401  (helpers + registry fixture below)
from tests.test_preflight_jobs import clean_registry  # noqa: F401


def broken_models(tmp_path):
    d = tmp_path / "broken"
    d.mkdir()
    (d / "dir.json").mkdir()
    (d / "binary.json").write_bytes(b"\xff\xfe\x00{bad")
    (d / "array.json").write_text("[]")
    (d / "scalar.json").write_text("5")
    (d / "null.json").write_text("null")
    (d / "deep.json").write_text("[" * 200000 + "]" * 200000)
    loop = d / "loop.json"
    loop.symlink_to(loop)
    models = {n: d / n for n in ("dir.json", "binary.json", "array.json", "scalar.json", "null.json", "deep.json", "loop.json")}
    if os.geteuid() != 0:
        (d / "private.json").write_text("{}")
        (d / "private.json").chmod(0)
        models["private.json"] = d / "private.json"
    return models


@pytest.fixture
def broken(tmp_path):
    models = broken_models(tmp_path)
    yield models
    for p in models.values():
        if p.exists() and not p.is_symlink() and p.is_file():
            p.chmod(0o644)


def test_validate_bids_model_never_raises(broken):
    for name, path in broken.items():
        result = validate_bids_model(path)
        assert result["valid"] is False and result["error"], name


def test_check_model_gives_a_model_item(broken):
    for name, path in broken.items():
        items = check_model(path)
        assert [i["id"] for i in items] == ["model"] and items[0]["severity"] == "error", name


def test_run_preflight_with_broken_models(tmp_path, broken):
    bids, fmriprep = make_trees(tmp_path)
    for name, path in broken.items():
        report = run_preflight(bids, fmriprep, model_file=path, tasks=["x"], space="MNI", validator="skip")
        assert report["verdict"] == "blocked" and "model" in {c["id"] for c in report["checks"]}, name


def test_sync_route_is_json_not_500(tmp_path, broken):
    bids, fmriprep = make_trees(tmp_path)
    client = app.test_client()
    for name, path in broken.items():
        res = client.post("/api/preflight", json={"config": {"BIDS_DIR": str(bids), "FMRIPREP_DIR": str(fmriprep), "SPACE": "MNI", "TASKS": ["x"]},
                                                  "model": str(path), "validator": "skip"})
        assert res.status_code == 200 and res.is_json, name
        assert "model" in {c["id"] for c in res.get_json()["checks"]}, name


def test_job_route_reports_a_model_item(tmp_path, broken):
    bids, fmriprep = make_trees(tmp_path)
    client = app.test_client()
    for name, path in broken.items():
        job = start(client, {"config": {"BIDS_DIR": str(bids), "FMRIPREP_DIR": str(fmriprep), "SPACE": "MNI", "TASKS": ["x"]},
                             "model": str(path), "validator": "skip"})
        events = parse(client.get(f"/api/preflight/stream/{job}").get_data(as_text=True))
        last = events[-1][1]
        assert last["phase"] == "done", (name, last)
        assert "model" in {c["id"] for c in last["report"]["checks"]}, name
        assert finished(job)


def test_job_failure_does_not_leak_exception_text_but_logs_it(caplog):
    client = app.test_client()
    with caplog.at_level(logging.ERROR), patch(RUNNER, side_effect=RuntimeError("secret /home/u/x")):
        job = start(client, {"config": {}})
        events = parse(client.get(f"/api/preflight/stream/{job}").get_data(as_text=True))
        assert finished(job)
    last = events[-1][1]
    assert last["phase"] == "error" and last["state"] == "done"
    assert "secret" not in last["message"] and "RuntimeError" not in last["message"]
    assert "error id" in last["message"]
    error_id = last["message"].rsplit(" ", 1)[-1].strip(").")
    assert any(error_id in r.getMessage() and r.exc_info and "secret /home/u/x" in str(r.exc_info[1]) for r in caplog.records)


def test_sync_route_unexpected_failure_is_json_without_internals():
    client = app.test_client()
    with patch("webapp.web_preflight_api.run_preflight_from_config", side_effect=RuntimeError("secret /home/u/x")):
        res = client.post("/api/preflight", json={"config": {}})
    assert res.status_code == 500 and res.is_json and "secret" not in res.get_data(as_text=True)


# ---- M2 /validate_model -------------------------------------------------------------------------
@pytest.mark.parametrize("body", ['[1]', '"x"', '5', 'null', '{"content": 5}', '{"content": "str"}', '{"content": [1]}', '{}', '[' * 200000 + ']' * 200000,
                                  '{"content": ' + '[' * 100000 + ']' * 100000 + '}'])
def test_validate_model_hostile_bodies_are_json_400(body):
    res = app.test_client().post("/validate_model", data=body, content_type="application/json")
    assert res.is_json and res.status_code == 400, (body[:30], res.status_code)
    assert res.get_json()["valid"] is False


def test_validate_model_temp_file_is_outside_cwd_config_and_removed(tmp_path):
    seen = []

    def fake(path):
        seen.append(Path(path))
        assert Path(path).is_file()
        return {"valid": True}
    before = sorted(p.name for p in Path("config").glob("temp_model_*"))
    with patch("webapp.web_discovery_model_api.validate_bids_model", side_effect=fake):
        res = app.test_client().post("/validate_model", json={"content": {"Name": "m", "Nodes": []}})
    assert res.status_code == 200 and res.get_json() == {"valid": True}
    assert seen and Path("config").resolve() not in seen[0].resolve().parents
    assert not seen[0].exists()
    assert sorted(p.name for p in Path("config").glob("temp_model_*")) == before


def test_validate_model_removes_the_temp_file_when_validation_raises():
    seen = []

    def boom(path):
        seen.append(Path(path))
        raise RuntimeError("x")
    with patch("webapp.web_discovery_model_api.validate_bids_model", side_effect=boom):
        res = app.test_client().post("/validate_model", json={"content": {"Name": "m"}})
    assert res.is_json and res.status_code == 500 and "RuntimeError" not in res.get_data(as_text=True)
    assert seen and not seen[0].exists()


def test_deeply_nested_body_with_nul_is_not_a_500():
    body = '{"path": "a\\u0000b", "x": ' + '[' * 100000 + ']' * 100000 + '}'
    res = app.test_client().post("/check_paths", data=body, content_type="application/json")
    assert res.status_code < 500
