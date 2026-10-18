"""F11/M11/M12/L6/L7: GUI write routes must not write into the BIDS tree, escape their base folder, or 500 on hostile paths."""
import json
import os

import pytest

import bidspm_gui
from bidspm_gui import app
from tests.preflight_support import make_trees


@pytest.fixture
def env(tmp_path, monkeypatch):
    bids, fmriprep = make_trees(tmp_path)
    monkeypatch.setattr(bidspm_gui, "_get_all_bids_dirs", lambda: [str(bids)])
    out = tmp_path / "out"
    out.mkdir()
    return {"bids": bids, "fmriprep": fmriprep, "out": out, "tmp": tmp_path, "c": app.test_client()}


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def wizard_body(env, **over):
    return {"bids_dir": str(env["bids"]), "fmriprep_dir": str(env["fmriprep"]), "preflight": False, "space": "MNI",
            "choices": {"task": "x", "name": "m", "recipes": [], "nuisance": "none", "exclude": [],
                        "contrasts": {"auto": True, "pairs": []}}, **over}


def is_json_error(res, status=None):
    assert res.is_json, res.data[:200]
    assert res.status_code in ((status,) if status else (400, 403)), (res.status_code, res.get_json())
    assert res.get_json().get("error")


# ---- lib helper ---------------------------------------------------------------------------------
def test_safe_target_unit(tmp_path):
    from lib.safe_paths import UnsafePath, safe_target
    assert safe_target(str(tmp_path / "a.json")) == os.path.realpath(tmp_path / "a.json")
    for bad in ("", "a\x00b", str(tmp_path / ".." / "x.json"), str(tmp_path / "dataset_description.json"),
                str(tmp_path / "participants.tsv"), str(tmp_path / "sub-01_task-x_events.tsv")):
        with pytest.raises(UnsafePath):
            safe_target(bad)
    with pytest.raises(UnsafePath):
        safe_target("../x.json", base=tmp_path)
    with pytest.raises(UnsafePath):
        safe_target("/etc/passwd", base=tmp_path)
    assert safe_target("ok.json", base=tmp_path) == os.path.realpath(tmp_path / "ok.json")


# ---- wizard build -------------------------------------------------------------------------------
def test_wizard_never_overwrites_dataset_description_even_with_overwrite(env):
    target = env["bids"] / "dataset_description.json"
    before = target.read_bytes()
    res = env["c"].post("/api/wizard/build", json=wizard_body(env, save_path=str(target), overwrite=True))
    is_json_error(res)
    assert target.read_bytes() == before


def test_wizard_refuses_new_file_inside_bids_tree(env):
    before = snapshot(env["bids"])
    is_json_error(env["c"].post("/api/wizard/build", json=wizard_body(env, save_path=str(env["bids"] / "sub-01" / "m.json"))))
    assert snapshot(env["bids"]) == before and not (env["bids"] / "sub-01" / "m.json").exists()


def test_wizard_refuses_symlink_into_bids_and_symlink_inside_tree_pointing_out(env):
    link = env["tmp"] / "bidslink"
    link.symlink_to(env["bids"], target_is_directory=True)
    is_json_error(env["c"].post("/api/wizard/build", json=wizard_body(env, save_path=str(link / "m.json"))))
    out_link = env["bids"] / "outlink"
    out_link.symlink_to(env["out"], target_is_directory=True)
    is_json_error(env["c"].post("/api/wizard/build", json=wizard_body(env, save_path=str(out_link / "m.json"))))
    assert not (env["out"] / "m.json").exists() and not (env["bids"] / "m.json").exists()


def test_wizard_nul_and_dotdot_save_path(env):
    is_json_error(env["c"].post("/api/wizard/build", json=wizard_body(env, save_path=str(env["out"]) + "/a\x00b.json")))
    is_json_error(env["c"].post("/api/wizard/build", json=wizard_body(env, save_path=str(env["out"]) + "/../x.json")))


def test_wizard_saves_into_a_normal_folder(env):
    res = env["c"].post("/api/wizard/build", json=wizard_body(env, save_path=str(env["out"] / "models" / "m.json")))
    assert res.status_code == 200 and (env["out"] / "models" / "m.json").is_file()


# ---- other write routes -------------------------------------------------------------------------
def test_model_create_refuses_bids_tree_and_dotdot(env):
    is_json_error(env["c"].post("/api/model/create", json={"path": str(env["bids"] / "new.json"), "overwrite": True}))
    is_json_error(env["c"].post("/api/model/create", json={"path": str(env["out"]) + "/../../esc/m.json"}))
    is_json_error(env["c"].post("/api/model/create", json={"path": str(env["bids"] / "dataset_description.json"), "overwrite": True}))
    assert json.loads((env["bids"] / "dataset_description.json").read_text())["Name"] == "t"


def test_save_settings_guards(env):
    c = env["c"]
    is_json_error(c.post("/save_settings", json={"filepath": str(env["bids"] / "s.json"), "content": {"a": 1}}))
    is_json_error(c.post("/save_settings", json={"filepath": str(env["bids"] / "dataset_description.json"), "content": {"a": 1}}))
    is_json_error(c.post("/save_settings", json={"filepath": str(env["out"]) + "/a\x00.json", "content": {}}))
    is_json_error(c.post("/save_settings", json={"filepath": str(env["out"] / "profile.sh"), "content": {}}))  # only .json
    assert not (env["bids"] / "s.json").exists() and not (env["out"] / "profile.sh").exists()
    assert c.post("/save_settings", json={"filepath": str(env["out"] / "ok.json"), "content": {"a": 1}}).status_code == 200


def test_save_config_filename_cannot_escape_folder(env):
    c = env["c"]
    folder = env["out"] / "cfgs"
    for name in ("../escaped.json", str(env["tmp"] / "abs.json"), "sub/../../e2.json"):
        is_json_error(c.post("/save_config", json={"config": {"a": 1}, "folder": str(folder), "filename": name}))
    assert not (env["out"] / "escaped.json").exists() and not (env["tmp"] / "abs.json").exists()
    assert c.post("/save_config", json={"config": {"a": 1}, "folder": str(folder), "filename": "ok.json"}).status_code == 200
    is_json_error(c.post("/save_config", json={"config": {}, "folder": str(env["bids"]), "filename": "c.json"}))


def test_mkdir_guards(env):
    c = env["c"]
    is_json_error(c.post("/mkdir", json={"path": str(env["out"]) + "/../../mk"}))
    is_json_error(c.post("/mkdir", json={"path": str(env["out"]) + "/a\x00b"}))
    link = env["tmp"] / "bidslink"
    link.symlink_to(env["bids"], target_is_directory=True)
    is_json_error(c.post("/mkdir", json={"path": str(link / "newdir")}))
    assert not (env["bids"] / "newdir").exists()
    assert c.post("/mkdir", json={"path": str(env["out"] / "fine")}).status_code == 200


def test_file_content_post_symlink_bypass_and_protected_names(env):
    c = env["c"]
    link = env["tmp"] / "bidslink"
    link.symlink_to(env["bids"], target_is_directory=True)
    is_json_error(c.post("/file_content", json={"path": str(link / "z.json"), "content": "{}"}))
    is_json_error(c.post("/file_content", json={"path": str(env["out"] / "participants.tsv"), "content": "x"}))
    is_json_error(c.post("/file_content", json={"path": str(env["out"]) + "/a\x00b", "content": "x"}))
    assert not (env["bids"] / "z.json").exists()
    assert c.post("/file_content", json={"path": str(env["out"] / "m.json"), "content": "{}"}).get_json()["success"]


def test_is_inside_bids_dir_resolves_symlinks(env):
    link = env["tmp"] / "bidslink"
    link.symlink_to(env["bids"], target_is_directory=True)
    assert bidspm_gui._is_inside_bids_dir(str(link / "z.json"))


# ---- L6 / L7 / M11 ------------------------------------------------------------------------------
@pytest.mark.parametrize("url", ["/browse?path=a%00b", "/file_content?path=a%00b", "/load_config_file?path=a%00b",
                                 "/get_bids_tasks?path=a%00b", "/get_model_tasks?path=a%00b"])
def test_nul_in_query_paths_is_json_400(env, url):
    is_json_error(env["c"].get(url), 400)


def test_nul_in_json_body_is_json_400(env):
    for url, body in (("/api/wizard/scan", {"bids_dir": "a\x00b"}), ("/check_paths", {"BIDS_DIR": "a\x00b"}),
                      ("/api/scan_events_columns", {"bids_dir": "a\x00b"})):
        is_json_error(env["c"].post(url, json=body), 400)


def test_file_content_get_is_plain_text_sandboxed(env):
    f = env["out"] / "x.html"
    f.write_text("<script>alert(1)</script>")
    res = env["c"].get("/file_content", query_string={"path": str(f)})
    assert res.status_code == 200 and res.data == b"<script>alert(1)</script>"
    assert res.headers["Content-Type"].startswith("text/plain") and "utf-8" in res.headers["Content-Type"].lower()
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in res.headers["Content-Security-Policy"]


def test_load_config_file_never_500s(env):
    c = env["c"]
    (env["out"] / "bad.json").write_text("{bad")
    (env["out"] / "arr.json").write_text("[1]")
    for p in (str(env["out"]), str(env["out"] / "bad.json"), str(env["out"]) + "/../out/bad.json"):
        res = c.get("/load_config_file", query_string={"path": p})
        assert res.is_json and res.status_code in (400, 404, 415, 422), (p, res.status_code)
    assert c.get("/load_config_file", query_string={"path": str(env["out"] / "arr.json")}).get_json() == [1]
    # missing keeps the documented default payload
    assert c.get("/load_config_file", query_string={"path": str(env["out"] / "none.json")}).status_code == 200


def test_load_config_legacy_traversal_and_errors(env):
    c = env["c"]
    folder = env["out"] / "cfgs"
    folder.mkdir()
    (env["out"] / "secret.json").write_text('{"s": 1}')
    (folder / "bad.json").write_text("{bad")
    (folder / "ok.json").write_text('{"a": 1}')
    for fn in ("../secret.json", str(env["out"] / "secret.json")):
        res = c.get("/load_config", query_string={"folder": str(folder), "filename": fn})
        assert res.is_json and res.status_code in (400, 403), (fn, res.status_code)
    res = c.get("/load_config", query_string={"folder": str(folder), "filename": "bad.json"})
    assert res.is_json and res.status_code == 422
    res = c.get("/load_config", query_string={"folder": str(folder), "filename": "."})
    assert res.is_json and res.status_code in (400, 404, 422)
    assert c.get("/load_config", query_string={"folder": str(folder), "filename": "ok.json"}).get_json() == {"a": 1}


def test_wizard_default_save_folder_is_the_projects_models_folder():
    """The page hands the wizard <derivatives>/models (what Pipeline resolves a relative MODELS_FILE against)."""
    from webapp.web_pages import wizard_models_dir
    assert wizard_models_dir("/d/derivatives", "/d/wd") == "/d/derivatives/models"
    assert wizard_models_dir("", "/d/wd") == "/d/wd/models"
    assert wizard_models_dir("", "") == ""
