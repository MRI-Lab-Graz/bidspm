import shutil
from unittest.mock import patch

import pytest

from lib import core
from lib.preflight import run_preflight, _verdict
from tests.preflight_support import make_trees, write_model


_real_validate = core.validate_bids_model


@pytest.fixture(autouse=True)
def _no_network_validation():
    with patch("lib.core.validate_bids_model", return_value={"valid": True}):
        yield


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


def test_condition_absent_everywhere_blocks(tmp_path):
    model = write_model(tmp_path, x=("trial_type.a", "trial_type.zzz", 1))
    result = run(tmp_path, model_file=model)
    (item,) = _only(result, "condition_missing")
    assert item["severity"] == "error" and "zzz" in item["message"]


def test_condition_absent_for_one_subject_only_warns(tmp_path):
    bids, fmriprep = make_trees(tmp_path, subjects=("01", "02"))
    (bids / "sub-02" / "func" / "sub-02_task-x_events.tsv").write_text("onset\tduration\ttrial_type\n1\t1\ta\n")
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip",
                           model_file=write_model(tmp_path))
    (item,) = _only(result, "condition_missing")
    assert item["severity"] == "warn" and item["subject"] == "02" and "b" in item["message"]


def test_condition_check_is_skipped_when_the_model_transforms_events(tmp_path):
    model = write_model(tmp_path, x=("trial_type.zzz", 1), transformations=True)
    assert "condition_missing" not in ids(run(tmp_path, model_file=model), "error")


def test_trial_type_column_required_when_model_uses_conditions(tmp_path):
    bids, fmriprep = make_trees(tmp_path, events="onset\tduration\n1\t1\n")
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip",
                           model_file=write_model(tmp_path))
    assert "events_trial_type" in ids(result, "error")


def test_model_nuisance_regressor_must_exist_in_confounds(tmp_path):
    model = write_model(tmp_path, x=("trial_type.a", "trans_x", "framewise_displacement", 1))
    result = run(tmp_path, model_file=model)
    (item,) = _only(result, "confound_columns")
    assert "framewise_displacement" in item["message"] and "trans_x" not in item["message"]


def test_missing_confounds_file_blocks_only_when_model_needs_it(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    next(fmriprep.rglob("*confounds_timeseries.tsv")).unlink()
    base = dict(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    assert "confounds_missing" not in ids(run_preflight(**base, model_file=write_model(tmp_path)), "error")
    needs = write_model(tmp_path, x=("trial_type.a", "trans_x", 1))
    assert "confounds_missing" in ids(run_preflight(**base, model_file=needs), "error")


def test_events_beyond_the_scan_warn(tmp_path):
    bids, fmriprep = make_trees(tmp_path, tr=2.0, nvols=10, events="onset\tduration\ttrial_type\n100\t1\ta\n")
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    assert "scan_length" in ids(result, "warn")


def test_events_file_with_excel_bom_is_read(tmp_path):
    bids, fmriprep = make_trees(tmp_path, events="\ufeffonset\tduration\ttrial_type\n1\t1\ta\n")
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    assert "events_columns" not in ids(result, "error")


def test_undecodable_events_file_is_an_error_not_a_crash(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    next(bids.rglob("*_events.tsv")).write_bytes(b"onset\tduration\n1\t1\xe9\xff\n")
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    assert "events_columns" in ids(result, "error")


def test_undecodable_confounds_file_is_an_error_not_a_crash(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    next(fmriprep.rglob("*confounds_timeseries.tsv")).write_bytes(b"trans_x\n\xe9\xff\n")
    model = write_model(tmp_path, x=("trial_type.a", "trans_x", 1))
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip",
                           model_file=model)
    assert "confound_columns" in ids(result, "error")


def test_no_tasks_found_blocks(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    for f in bids.rglob("*_events.tsv"):
        f.unlink()
    result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, space="MNI", validator="skip")
    assert "no_tasks" in ids(result, "error")


def test_invalid_model_blocks_with_the_validators_message(tmp_path):
    with patch("lib.core.validate_bids_model", return_value={"valid": False, "error": "Empty contrast issues: x"}):
        result = run(tmp_path, model_file=write_model(tmp_path))
    (item,) = _only(result, "model")
    assert item["severity"] == "error" and "Empty contrast" in item["message"]


def test_model_warning_is_a_warn_and_valid_model_adds_nothing(tmp_path):
    model = write_model(tmp_path)
    with patch("lib.core.validate_bids_model", return_value={"valid": True, "warning": "Normalized model"}):
        assert [c["severity"] for c in _only(run(tmp_path, model_file=model), "model")] == ["warn"]
    with patch("lib.core.validate_bids_model", return_value={"valid": True}):
        assert _only(run(tmp_path, model_file=model), "model") == []


def test_missing_container_runtime_warns(tmp_path):
    with patch("shutil.which", return_value=None):
        assert "container" in ids(run(tmp_path, container_type="docker"), "warn")
    assert "container" not in ids(run(tmp_path, container_type=""), "warn")


def test_offline_schema_fetch_is_a_warning_not_an_error(tmp_path):
    import requests
    with patch("lib.core.validate_bids_model", _real_validate), \
            patch("lib.core._fetch_bids_stats_schema", side_effect=requests.ConnectionError("offline")):
        result = run(tmp_path, model_file=write_model(tmp_path))
    (item,) = _only(result, "model")
    assert item["severity"] == "warn" and "schema" in item["message"]
