"""Review round: <bids>/derivatives/** is outside the protected BIDS tree; dataset files stay protected everywhere."""
import bidspm_gui
from tests.test_path_safety import env, is_json_error, wizard_body  # noqa: F401


def test_derivatives_inside_bids_are_writable(env):  # noqa: F811
    c = env["c"]
    models = env["bids"] / "derivatives" / "models"
    res = c.post("/api/wizard/build", json=wizard_body(env, save_path=str(models / "m.json")))
    assert res.status_code == 200 and (models / "m.json").is_file()
    assert c.post("/api/model/create", json={"path": str(models / "c.json")}).get_json()["success"]
    assert c.post("/mkdir", json={"path": str(env["bids"] / "derivatives" / "new")}).status_code == 200
    assert c.post("/file_content", json={"path": str(models / "f.json"), "content": "{}"}).get_json()["success"]
    assert c.post("/save_settings", json={"filepath": str(models / "s.json"), "content": {}}).status_code == 200


def test_dataset_files_under_derivatives_stay_protected(env):  # noqa: F811
    d = env["bids"] / "derivatives" / "x"
    d.mkdir(parents=True)
    (d / "dataset_description.json").write_text("{}")
    for name in ("dataset_description.json", "Dataset_Description.JSON", "Participants.TSV", "sub-01_task-x_EVENTS.TSV"):
        is_json_error(env["c"].post("/file_content", json={"path": str(d / name), "content": "x"}))
    assert (d / "dataset_description.json").read_text() == "{}"


def test_symlink_from_outside_into_bids_refused_but_derivatives_through_it_allowed(env):  # noqa: F811
    link = env["tmp"] / "bidslink"
    link.symlink_to(env["bids"], target_is_directory=True)
    is_json_error(env["c"].post("/file_content", json={"path": str(link / "sub-01" / "z.json"), "content": "{}"}))
    assert env["c"].post("/file_content", json={"path": str(link / "derivatives" / "z.json"), "content": "{}"}).get_json()["success"]


def test_bids_folder_registered_as_root_does_not_block_everything(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(bidspm_gui, "_get_all_bids_dirs", lambda: ["/"])
    assert env["c"].post("/file_content", json={"path": str(env["out"] / "m.json"), "content": "{}"}).get_json()["success"]
    is_json_error(env["c"].post("/file_content", json={"path": str(env["out"] / "participants.tsv"), "content": "x"}))
