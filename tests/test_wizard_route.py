import json
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

from bidspm_gui import app
from lib.model_wizard import scan_events
from tests.preflight_support import make_trees


def post(path, body):
    return app.test_client().post(path, json=body)


def paths(tmp_path, **kw):
    bids, fmriprep = make_trees(tmp_path, **kw)
    return {"bids_dir": str(bids), "fmriprep_dir": str(fmriprep)}


def choices(**over):
    return {"task": "x", "name": "m", "recipes": [], "nuisance": "motion6", "exclude": [],
            "contrasts": {"auto": True, "pairs": []}, **over}


def test_scan_returns_tasks_columns_catalog_and_presets(tmp_path):
    res = post("/api/wizard/scan", paths(tmp_path))
    data = res.get_json()
    assert res.status_code == 200 and data["tasks"] == ["x"] and data["task"] == "x"
    assert set(data["columns"]["trial_type"]) == {"a", "b"}
    assert "trans_x" in data["confound_columns"]
    assert {r["id"] for r in data["catalog"]} >= {"valid_only", "split_by_column", "merge_rename", "parametric_modulator"}
    assert "motion6" in data["nuisance_presets"]


def test_scan_unknown_task_falls_back_to_first(tmp_path):
    assert post("/api/wizard/scan", {**paths(tmp_path), "task": "zzz"}).get_json()["task"] == "x"


def test_scan_missing_bids_is_404_and_non_dict_400(tmp_path):
    assert post("/api/wizard/scan", {"bids_dir": str(tmp_path / "nope")}).status_code == 404
    assert app.test_client().post("/api/wizard/scan", data="[]", content_type="application/json").status_code == 400


def test_build_returns_model_preview_and_preflight_without_validator_noise(tmp_path):
    full = "trans_x\ttrans_y\ttrans_z\trot_x\trot_y\trot_z\n0\t0\t0\t0\t0\t0\n"  # motion6 needs all six
    res = post("/api/wizard/build", {**paths(tmp_path, confounds=full), "space": "MNI", "choices": choices()})
    data = res.get_json()
    assert res.status_code == 200 and data["preview"]["regressors"] == ["trial_type.a", "trial_type.b"]
    assert data["preflight"]["verdict"] in ("ready", "warnings")
    assert all(c["id"] != "validator" for c in data["preflight"]["checks"])


def test_build_preflight_flags_a_missing_confound_column(tmp_path):
    res = post("/api/wizard/build", {**paths(tmp_path), "space": "MNI", "choices": choices(nuisance=["csf"])})
    assert "confound_columns" in {c["id"] for c in res.get_json()["preflight"]["checks"] if c["severity"] == "error"}


def test_build_wizard_error_is_a_400(tmp_path):
    res = post("/api/wizard/build", {**paths(tmp_path), "choices": choices(recipes=[{"id": "nope"}])})
    assert res.status_code == 400 and "unknown recipe" in res.get_json()["error"]


def test_build_null_optional_keys_equal_omitted(tmp_path):
    p = {**paths(tmp_path), "space": "MNI"}
    nulls = post("/api/wizard/build", {**p, "choices": choices(exclude=None, recipes=None, contrasts=None)})
    omitted = choices()
    for k in ("exclude", "recipes", "contrasts"):
        del omitted[k]
    plain = post("/api/wizard/build", {**p, "choices": omitted})
    assert nulls.status_code == 200 and nulls.get_json()["model"] == plain.get_json()["model"]


@pytest.mark.parametrize("bad", ["[]", '{"choices": []}', '{"choices": "x"}', '{"choices": null}'])
def test_build_malformed_body_is_400(bad):
    assert app.test_client().post("/api/wizard/build", data=bad, content_type="application/json").status_code == 400


def test_build_unknown_task_is_400(tmp_path):
    res = post("/api/wizard/build", {**paths(tmp_path), "choices": choices(task="nope")})
    assert res.status_code == 400 and "not found" in res.get_json()["error"]


@pytest.mark.parametrize("task", [None, ["x"], 5])
def test_build_odd_task_is_400(tmp_path, task):
    assert post("/api/wizard/build", {**paths(tmp_path), "choices": choices(task=task)}).status_code == 400


@pytest.mark.parametrize("bids", ["", None, "MISSING"])
def test_build_bad_bids_dir_is_404(tmp_path, bids):
    body = {**paths(tmp_path), "choices": choices()}
    if bids == "MISSING":
        del body["bids_dir"]
    else:
        body["bids_dir"] = bids
    assert post("/api/wizard/build", body).status_code == 404


@pytest.mark.parametrize("mode", ["missing", "notdir"])
def test_build_without_fmriprep_dir_still_builds(tmp_path, mode):
    body = {**paths(tmp_path), "space": "MNI", "choices": choices(nuisance="none")}
    if mode == "missing":
        del body["fmriprep_dir"]
    else:
        body["fmriprep_dir"] = str(tmp_path / "bids" / "dataset_description.json")
    assert post("/api/wizard/scan", body).get_json()["confound_columns"] == []
    assert post("/api/wizard/build", body).status_code == 200


def test_build_events_without_trial_type_is_400(tmp_path):
    p = paths(tmp_path, events="onset\tduration\n1\t1\n")
    res = post("/api/wizard/build", {**p, "choices": choices()})
    assert res.status_code == 400 and "trial_type" in res.get_json()["error"]


def test_save_writes_the_model_and_refuses_to_overwrite(tmp_path):
    target = tmp_path / "models" / "m.json"
    body = {**paths(tmp_path), "space": "MNI", "choices": choices(), "save_path": str(target)}
    first = post("/api/wizard/build", body)
    assert first.status_code == 200 and json.loads(target.read_text())["Name"] == "m"
    assert post("/api/wizard/build", body).status_code == 409
    assert post("/api/wizard/build", {**body, "overwrite": True}).status_code == 200


def test_save_path_must_be_json(tmp_path):
    target = tmp_path / "m.txt"
    res = post("/api/wizard/build", {**paths(tmp_path), "choices": choices(), "save_path": str(target)})
    assert res.status_code == 400 and not target.exists()


def test_non_dict_body_is_a_400_not_a_500():
    res = app.test_client().post("/api/wizard/build", data="[]", content_type="application/json")
    assert res.status_code == 400


def test_preflight_removes_temp_model_even_when_it_raises(tmp_path):
    from webapp.web_wizard_api import _preflight
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    with mock.patch.object(tempfile, "tempdir", str(tmpdir)), \
            mock.patch("webapp.web_wizard_api.run_preflight_from_config", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            _preflight({"Name": "m"}, "b", "f", "MNI", "x")
    assert list(Path(tmpdir).iterdir()) == []


MULTI = ("onset\tduration\ttrial_type\tresponse_validity\trt\n"
         "1\t1\titem\tvalid\t0.5\n5\t1\titem\tinvalid\t0.6\n9\t1\tb\tvalid\t0.7\n")


def test_valid_only_and_split_build_through_real_scan(tmp_path):
    p = paths(tmp_path, events=MULTI)
    recipes = [{"id": "valid_only", "condition": "item", "column": "response_validity", "value": "valid"},
               {"id": "split_by_column", "condition": "b", "column": "response_validity", "values": ["valid"]}]
    scan = post("/api/wizard/scan", p).get_json()
    assert scan["numeric"] == ["rt"] and scan["truncated"] == [] and scan["events_files"] == 1
    assert "response_validity" in scan["columns"]
    for r in recipes:
        res = post("/api/wizard/build", {**p, "choices": choices(nuisance="none", recipes=[r])})
        assert res.status_code == 200, res.get_json()


def test_condition_in_one_subject_only_is_offered(tmp_path):
    p = paths(tmp_path, subjects=("01", "02"))
    f = tmp_path / "bids/sub-02/func/sub-02_task-x_events.tsv"
    f.write_text(f.read_text() + "9\t1\trare\n")
    assert "rare" in post("/api/wizard/scan", p).get_json()["columns"]["trial_type"]


def test_truncated_trial_type_adds_preview_warning(tmp_path):
    p = paths(tmp_path)
    with mock.patch("webapp.web_wizard_api.scan_events",
                    return_value={"columns": {"trial_type": ["a", "b"]}, "numeric": [], "files": 1, "truncated": ["trial_type"]}):
        res = post("/api/wizard/build", {**p, "choices": choices(nuisance="none")})
    assert any("trial_type has more than" in w for w in res.get_json()["preview"]["warnings"])


def test_preflight_exception_is_json_500(tmp_path):
    with mock.patch("webapp.web_wizard_api.run_preflight_from_config", side_effect=RuntimeError("boom")):
        res = post("/api/wizard/build", {**paths(tmp_path), "choices": choices(nuisance="none")})
    assert res.status_code == 500 and "boom" in res.get_json()["error"]


def test_preview_build_without_preflight_skips_it_and_the_confound_scan(tmp_path):
    with mock.patch("webapp.web_wizard_api.run_preflight_from_config") as pre, \
            mock.patch("webapp.web_wizard_api._discover_confound_info") as conf:
        res = post("/api/wizard/build", {**paths(tmp_path), "choices": choices(nuisance="none"), "preflight": False})
    assert res.status_code == 200 and "preflight" not in res.get_json()
    pre.assert_not_called()
    conf.assert_not_called()


def test_build_runs_preflight_by_default_but_not_on_save_with_preflight_false(tmp_path):
    report = {"checks": []}
    with mock.patch("webapp.web_wizard_api.run_preflight_from_config", return_value=report) as pre:
        post("/api/wizard/build", {**paths(tmp_path), "choices": choices(nuisance="none")})
        post("/api/wizard/build", {**paths(tmp_path), "choices": choices(nuisance="none"), "preflight": False,
                                   "save_path": str(tmp_path / "m.json")})
    assert pre.call_count == 1  # saving does not repeat it: its result was never shown


def test_scan_refreshes_and_the_next_build_sees_edited_events(tmp_path):
    p = paths(tmp_path)
    body = {**p, "choices": choices(nuisance="none"), "preflight": False}
    assert "rare" not in post("/api/wizard/scan", p).get_json()["columns"]["trial_type"]
    assert "trial_type.rare" not in post("/api/wizard/build", body).get_json()["preview"]["regressors"]
    f = next((tmp_path / "bids").glob("sub-*/**/*_events.tsv"))
    f.write_text(f.read_text() + "9\t1\trare\n")
    # ponytail: builds may be up to the scan TTL stale; the scan route (page load / task change) always refreshes
    assert "rare" in post("/api/wizard/scan", p).get_json()["columns"]["trial_type"]
    assert "trial_type.rare" in post("/api/wizard/build", body).get_json()["preview"]["regressors"]


def test_warm_builds_do_not_reread_the_events_files(tmp_path):
    p = paths(tmp_path)
    body = {**p, "choices": choices(nuisance="none"), "preflight": False}
    with mock.patch("webapp.web_wizard_api.scan_events", wraps=scan_events) as spy:
        post("/api/wizard/scan", p)
        post("/api/wizard/build", body)
        post("/api/wizard/build", body)
        assert spy.call_count == 1  # one scan; both builds used its result
        post("/api/wizard/scan", p)
        assert spy.call_count == 2  # the scan route always refreshes


def test_a_build_without_a_prior_scan_scans_once_then_stays_warm(tmp_path):
    body = {**paths(tmp_path), "choices": choices(nuisance="none"), "preflight": False}
    with mock.patch("webapp.web_wizard_api.scan_events", wraps=scan_events) as spy:
        post("/api/wizard/build", body)
        post("/api/wizard/build", body)
    assert spy.call_count == 1


def test_cache_entries_expire_after_the_ttl(tmp_path):
    from webapp import web_wizard_api
    body = {**paths(tmp_path), "choices": choices(nuisance="none"), "preflight": False}
    post("/api/wizard/build", body)
    with mock.patch("webapp.web_wizard_api.scan_events", wraps=scan_events) as spy, \
            mock.patch.object(web_wizard_api.time, "monotonic", return_value=time.monotonic() + web_wizard_api.SCAN_TTL + 1):
        post("/api/wizard/build", body)
    assert spy.call_count == 1


def test_a_build_does_not_leak_a_cached_scan_between_folders(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    pa, pb = paths(a), paths(b, events="onset\tduration\ttrial_type\n1\t1\tzz\n")
    for p, cond in ((pa, "trial_type.a"), (pb, "trial_type.zz")):
        res = post("/api/wizard/build", {**p, "choices": choices(nuisance="none"), "preflight": False})
        assert cond in res.get_json()["preview"]["regressors"]


def test_files_truncated_adds_preview_warning(tmp_path):
    with mock.patch("webapp.web_wizard_api.scan_events", return_value={
            "columns": {"trial_type": ["a"]}, "numeric": [], "files": 300, "truncated": [], "files_truncated": True}):
        res = post("/api/wizard/build", {**paths(tmp_path), "choices": choices(nuisance="none"), "preflight": False})
    assert any("only the first 300" in w for w in res.get_json()["preview"]["warnings"])


def test_scan_response_carries_files_truncated(tmp_path):
    assert post("/api/wizard/scan", paths(tmp_path)).get_json()["files_truncated"] is False


def test_save_failure_is_json_400(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    res = post("/api/wizard/build", {**paths(tmp_path), "choices": choices(nuisance="none"),
                                     "save_path": str(blocker / "sub" / "m.json")})
    assert res.status_code == 400 and "could not save" in res.get_json()["error"]


def test_malformed_pair_items_and_recipe_id_are_400_through_the_route(tmp_path):
    bad_pair = {"name": "x", "positive": [{"a": 1}], "negative": ["trial_type.b"]}
    for ch in (choices(contrasts={"auto": True, "pairs": [bad_pair]}), choices(recipes=[{"id": {}}])):
        res = post("/api/wizard/build", {**paths(tmp_path), "choices": ch, "preflight": False})
        assert res.status_code == 400


def test_build_preflight_uses_validator_off(tmp_path):
    with mock.patch("webapp.web_wizard_api.run_preflight_from_config", return_value={"verdict": "ready", "checks": []}) as pf:
        res = post("/api/wizard/build", {**paths(tmp_path), "space": "MNI", "choices": choices()})
    assert res.status_code == 200 and pf.call_args.kwargs["validator"] == "off"


def test_scan_returns_the_resolved_folders_for_a_tilde_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    make_trees(tmp_path / "data")
    res = post("/api/wizard/scan", {"bids_dir": "~/data/bids", "fmriprep_dir": "~/data/fmriprep"})
    assert res.status_code == 200
    assert res.get_json()["bids_dir"] == str(tmp_path / "data" / "bids")
    assert res.get_json()["fmriprep_dir"] == str(tmp_path / "data" / "fmriprep")
