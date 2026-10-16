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
