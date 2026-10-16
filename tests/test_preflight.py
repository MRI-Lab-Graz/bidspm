import shutil

import pytest

from lib.preflight import run_preflight, _verdict
from tests.preflight_support import make_trees


def ids(result, severity):
    return {c["id"] for c in result["checks"] if c["severity"] == severity}


def run(tmp_path, **kw):
    bids, fmriprep = make_trees(tmp_path)
    args = dict(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    args.update(kw)
    return run_preflight(**args)


def test_healthy_trees_have_no_errors(tmp_path):
    result = run(tmp_path)
    assert ids(result, "error") == set()
    assert result["verdict"] in ("ready", "warnings")  # strict "warnings" restored in Task 6 (skipped validator warns)


def test_verdict_levels():
    assert _verdict([]) == "ready"
    assert _verdict([{"severity": "warn"}]) == "warnings"
    assert _verdict([{"severity": "warn"}, {"severity": "error"}]) == "blocked"


def test_missing_folders_block_and_stop_early(tmp_path):
    result = run_preflight(bids_dir=tmp_path / "nope", fmriprep_dir=tmp_path / "nada", validator="skip")
    assert ids(result, "error") == {"bids_dir", "fmriprep_dir"}
    assert result["verdict"] == "blocked"


def test_folder_without_dataset_description_blocks(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    (fmriprep / "dataset_description.json").unlink()
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, validator="skip")
    assert "fmriprep_dir" in ids(result, "error")


def test_selected_subject_missing_from_fmriprep_blocks(tmp_path):
    result = run(tmp_path, subjects=["01", "99"])
    errors = [c for c in result["checks"] if c["id"] == "subject_missing"]
    assert {c["subject"] for c in errors} == {"99"}
    assert len(errors) == 2  # absent from both BIDS and fMRIPrep


def test_subject_labels_may_carry_the_sub_prefix(tmp_path):
    assert "subject_missing" not in ids(run(tmp_path, subjects=["sub-01"]), "error")


def test_folder_without_subjects_blocks(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    for p in fmriprep.glob("sub-*"):
        shutil.rmtree(p)
    assert "fmriprep_dir" in ids(run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, validator="skip"), "error")


@pytest.mark.parametrize("unset", [None, ""])
def test_unset_folder_blocks_as_not_set(tmp_path, unset):
    bids, _ = make_trees(tmp_path)
    result = run_preflight(bids_dir=bids, fmriprep_dir=unset, validator="skip")
    (item,) = [c for c in result["checks"] if c["id"] == "fmriprep_dir"]
    assert "not set" in item["message"]


def _only(result, id):
    return [c for c in result["checks"] if c["id"] == id]


def test_missing_preproc_blocks_with_a_fix_hint(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    next(fmriprep.rglob("*desc-preproc_bold.nii.gz")).unlink()
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    (item,) = _only(result, "preproc_missing")
    assert item["subject"] == "01" and "MNI" in item["message"] and item["fix"]


def test_wrong_space_counts_as_missing_preproc(tmp_path):
    assert "preproc_missing" in ids(run(tmp_path, space="T1w"), "error")


def test_missing_events_block(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    next(bids.rglob("*_events.tsv")).unlink()
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    assert "events_missing" in ids(result, "error")


@pytest.mark.parametrize("events,expected", [
    ("onset\ttrial_type\n1\ta\n", "events_columns"),                          # no duration column
    ("onset\tduration\ttrial_type\nsoon\t1\ta\n", "events_values"),           # non-numeric onset
    ("onset\tduration\ttrial_type\n1\t-2\ta\n", "events_values"),             # negative duration
])
def test_bad_events_block(tmp_path, events, expected):
    bids, fmriprep = make_trees(tmp_path, events=events)
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    assert expected in ids(result, "error")


def test_tasks_default_to_those_found_in_bids(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    next(fmriprep.rglob("*desc-preproc_bold.nii.gz")).unlink()
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, space="MNI", validator="skip")
    assert "preproc_missing" in ids(result, "error")
