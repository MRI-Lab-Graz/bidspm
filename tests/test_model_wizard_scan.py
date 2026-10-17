from lib.model_wizard import scan_events


def write(root, rel, text, mode="w", enc="utf-8"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding=enc)
    return p


def ev(*rows, header="onset\tduration\ttrial_type\trt"):
    return header + "\n" + "".join("\t".join(map(str, r)) + "\n" for r in rows)


def test_union_across_subjects_numeric_and_na(tmp_path):
    write(tmp_path, "sub-01/func/sub-01_task-x_events.tsv", ev((1, 1, "a", "0.5"), (2, 1, "n/a", "nan")))
    write(tmp_path, "sub-02/ses-1/func/sub-02_ses-1_task-x_events.tsv", ev((1, 1, "b", "0.7")))
    write(tmp_path, "sub-02/func/sub-02_task-other_events.tsv", ev((1, 1, "zzz", "1")))
    r = scan_events(tmp_path, "x")
    assert r["columns"] == {"trial_type": ["a", "b"], "rt": ["0.5", "0.7"]}
    assert r["numeric"] == ["rt"] and r["files"] == 2 and r["truncated"] == []


def test_bom_unreadable_and_dataset_level(tmp_path):
    write(tmp_path, "sub-01/func/sub-01_task-x_events.tsv", "﻿" + ev((1, 1, "a", "1")))
    (tmp_path / "sub-02/func").mkdir(parents=True)
    (tmp_path / "sub-02/func/sub-02_task-x_events.tsv").write_bytes(b"\xff\xfe\x00bad")
    write(tmp_path, "task-x_events.tsv", ev((1, 1, "c", "2")))
    r = scan_events(tmp_path, "x")
    assert r["columns"]["trial_type"] == ["a", "c"] and r["files"] == 2


def test_truncation_reported(tmp_path):
    write(tmp_path, "sub-01/func/sub-01_task-x_events.tsv", ev(*[(i, 1, f"c{i}", "1") for i in range(5)]))
    r = scan_events(tmp_path, "x", max_values=3)
    assert len(r["columns"]["trial_type"]) == 3 and "trial_type" in r["truncated"] and "rt" not in r["truncated"]


def test_files_truncated_reported(tmp_path):
    for s in ("01", "02", "03"):
        write(tmp_path, f"sub-{s}/func/sub-{s}_task-x_events.tsv", ev((1, 1, "a", "1")))
    assert scan_events(tmp_path, "x", max_files=2)["files_truncated"] is True
    assert scan_events(tmp_path, "x")["files_truncated"] is False


def test_bids_tasks_matches_discover_tasks_without_walking_imaging_folders(tmp_path):
    from lib.core import discover_tasks
    from lib.model_wizard import bids_tasks
    write(tmp_path, "sub-01/func/sub-01_task-x_bold.nii.gz", "")
    write(tmp_path, "sub-02/ses-1/func/sub-02_ses-1_task-y_events.tsv", "")
    write(tmp_path, "sub-02/anat/sub-02_T1w.nii.gz", "")
    write(tmp_path, "sub-02/anat/sub-02_task-nope_T1w.nii.gz", "")
    assert bids_tasks(tmp_path) == discover_tasks(tmp_path) == ["x", "y"]
