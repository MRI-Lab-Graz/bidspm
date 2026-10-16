import json
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from lib import core
from lib.preflight import check_validator, run_preflight, run_preflight_from_config, _model_needs, _verdict
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


def _only(result, id):
    return [c for c in result["checks"] if c["id"] == id]


def test_healthy_trees_have_no_errors(tmp_path):
    result = run(tmp_path)
    assert ids(result, "error") == set()
    assert result["verdict"] == "warnings"


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


REPORT = {"valid": False, "issues": [
    {"code": "PRISM301", "severity": "ERROR", "message": "schema error: 'Authors' is a required property\nmore", "file_path": "/d/dataset_description.json"},
    {"code": "BIDS_NO_AUTHORS", "severity": "WARNING", "message": "[BIDS] NO_AUTHORS", "file_path": "/d/x"},
    {"code": "BIDS_README_FILE_MISSING", "severity": "WARNING", "message": "[BIDS] README", "file_path": "/d/y"}]}


@pytest.fixture
def fake_exe(tmp_path_factory):
    """A stand-in prism-validator next to a fake interpreter, so the fake-run tests never need the real tool."""
    bindir = tmp_path_factory.mktemp("bin")
    (bindir / "prism-validator").write_text("")
    with patch("lib.preflight.sys.executable", str(bindir / "python")):
        yield


def fake_run(stdout, returncode=1, calls=None):
    def run(cmd, **kw):
        if calls is not None:
            calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")
    return run


def test_validator_errors_block_and_warnings_are_summarised(tmp_path, fake_exe):
    out = check_validator(tmp_path, "prism", run=fake_run("banner\n" + json.dumps(REPORT)))
    assert [(c["severity"], c["id"]) for c in out] == [("error", "validator"), ("warn", "validator")]
    assert "PRISM301" in out[0]["message"] and "more" not in out[0]["message"]
    assert "2 validator warning" in out[1]["message"]


def test_plain_bids_mode_passes_no_prism_and_never_fix_or_plugins(tmp_path, fake_exe):
    calls = []
    check_validator(tmp_path, "bids", run=fake_run(json.dumps({"issues": []}), 0, calls))
    cmd = calls[0]
    assert "--no-prism" in cmd and "--json" in cmd
    assert not {"--fix", "--plugins"} & set(cmd)


def test_skip_mode_warns_and_does_not_run(tmp_path, fake_exe):
    calls = []
    out = check_validator(tmp_path, "skip", run=fake_run("", 0, calls))
    assert [c["severity"] for c in out] == ["warn"] and calls == []


def test_unparseable_output_with_clean_exit_degrades_to_a_warning(tmp_path, fake_exe):
    out = check_validator(tmp_path, "prism", run=fake_run("Traceback ...", 0))
    assert [c["severity"] for c in out] == ["warn"]


def test_crashed_validator_blocks(tmp_path, fake_exe):
    out = check_validator(tmp_path, "prism", run=fake_run("Traceback ...", 2))
    assert [(c["severity"], c["id"]) for c in out] == [("error", "validator")]
    assert "crashed" in out[0]["message"] and "exit 2" in out[0]["message"] and "skip" in out[0]["fix"]


@pytest.mark.parametrize("stdout", ["[]", "null", '"x"'])
def test_non_object_report_is_unparseable(tmp_path, fake_exe, stdout):
    out = check_validator(tmp_path, "prism", run=fake_run(stdout, 1))
    assert [c["severity"] for c in out] == ["error"]


def test_invalid_report_without_listed_errors_blocks(tmp_path, fake_exe):
    out = check_validator(tmp_path, "prism", run=fake_run(json.dumps({"valid": False, "issues": []}), 1))
    assert [c["severity"] for c in out] == ["error"] and "listed no errors" in out[0]["message"]


def test_timeout_and_oserror_stay_warnings(tmp_path, fake_exe):
    for exc in (subprocess.TimeoutExpired("x", 1), OSError("boom")):
        def run(cmd, **kw):
            raise exc
        assert [c["severity"] for c in check_validator(tmp_path, "prism", run=run)] == ["warn"]


def test_missing_binary_stays_a_warning(tmp_path):
    with patch("lib.preflight.sys.executable", str(tmp_path / "python")), patch("lib.preflight.shutil.which", return_value=None):
        out = check_validator(tmp_path, "prism", run=fake_run("", 0))
    assert [c["severity"] for c in out] == ["warn"] and "not installed" in out[0]["message"]


@pytest.mark.parametrize("report", [
    {"issues": None}, {"issues": "oops"}, {"issues": 5}, {"issues": [{"severity": "ERROR"}]},
    {"issues": [{"severity": "ERROR", "code": "X", "message": ""}]}, {"issues": [{"severity": "WARNING"}]}, {"issues": [1]}])
def test_malformed_issues_never_raise(tmp_path, fake_exe, report):
    check_validator(tmp_path, "prism", run=fake_run(json.dumps(report), 1))


def test_validator_errors_are_capped_at_twenty(tmp_path, fake_exe):
    issues = [{"code": f"E{n}", "severity": "ERROR", "message": "m", "file_path": "f"} for n in range(25)]
    out = check_validator(tmp_path, "prism", run=fake_run(json.dumps({"issues": issues})))
    assert len(out) == 21 and {c["severity"] for c in out} == {"error"} and "+5 more" in out[-1]["message"]


def test_unknown_mode_blocks_without_running(tmp_path, fake_exe):
    calls = []
    out = check_validator(tmp_path, "strict", run=fake_run("", 0, calls))
    assert [(c["severity"], c["id"]) for c in out] == [("error", "validator")] and "unknown" in out[0]["message"] and calls == []


def test_validator_error_blocks_the_whole_preflight(tmp_path, fake_exe):
    bids, fmriprep = make_trees(tmp_path)
    with patch("lib.preflight.subprocess.run", fake_run(json.dumps(REPORT))):
        result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="prism")
    assert result["verdict"] == "blocked" and "validator" in ids(result, "error")


@pytest.mark.skipif(not (Path(sys.executable).parent / "prism-validator").exists() and not shutil.which("prism-validator"),
                    reason="prism-validator not installed")
def test_real_prism_validator_flags_an_incomplete_dataset(tmp_path):
    bids, _ = make_trees(tmp_path)  # no Authors, no sidecars -> PRISM errors
    assert any(c["severity"] == "error" for c in check_validator(bids, "prism"))
    assert not any(c["severity"] == "error" for c in check_validator(bids, "bids"))


# ---- final fix wave ----
def pf(tmp_path, bids, fmriprep, **kw):
    args = dict(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    args.update(kw)
    return run_preflight(**args)


def test_string_intercept_is_not_a_nuisance_regressor(tmp_path):
    model = write_model(tmp_path, x=("trial_type.a", "trans_x", "1", "0"))
    assert "confound_columns" not in ids(run(tmp_path, model_file=model), "error")


@pytest.mark.parametrize("content", ["[]", '{"Model": null, "Nodes": null}', '{"Nodes": [1, "a"]}',
                                     '{"Nodes": [{"Level": "Run", "Model": null}]}',
                                     '{"Nodes": [{"Level": "Run", "Model": {"X": "trans_x"}}]}'])
def test_malformed_models_do_not_crash_needs(tmp_path, content):
    f = tmp_path / "m.json"
    f.write_text(content)
    assert _model_needs(f)[1] == []
    assert run(tmp_path, model_file=f)["verdict"]


def test_corrupt_nifti_and_null_tr_do_not_crash(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    nii = next(fmriprep.rglob("*desc-preproc_bold.nii.gz"))
    nii.write_bytes(b"not gzip")
    assert pf(tmp_path, bids, fmriprep)["verdict"]
    bids, fmriprep = make_trees(tmp_path / "b", tr=2.0)
    next(fmriprep.rglob("*desc-preproc_bold.json")).write_text('{"RepetitionTime": null}')
    assert pf(tmp_path, bids, fmriprep)["verdict"]


def test_non_string_validator_fields_do_not_crash(tmp_path, fake_exe):
    rep = {"valid": False, "issues": [{"severity": "ERROR", "code": 5, "message": ["x"], "file_path": "f"},
                                       {"severity": "WARNING", "code": 7, "message": 1}]}
    assert check_validator(tmp_path, "prism", run=fake_run(json.dumps(rep), 1))


def test_skip_model_validation_skips_only_the_model_check(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    model = write_model(tmp_path)
    with patch("lib.core.validate_bids_model", return_value={"valid": False, "error": "bad"}) as v:
        assert "model" in ids(pf(tmp_path, bids, fmriprep, model_file=model), "error")
        result = pf(tmp_path, bids, fmriprep, model_file=model, skip_model_validation=True)
    assert "model" not in ids(result, "error") and v.call_count == 1


def test_smooth_only_skips_events_and_model_checks(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    for f in bids.rglob("*_events.tsv"):
        f.unlink()
    model = write_model(tmp_path)
    with patch("lib.core.validate_bids_model", return_value={"valid": False, "error": "bad"}):
        smooth = pf(tmp_path, bids, fmriprep, model_file=model, actions=["smooth"])
        stats = pf(tmp_path, bids, fmriprep, model_file=model, actions=["stats"])
    assert ids(smooth, "error") == set()
    assert "events_missing" in ids(stats, "error") and "model" in ids(stats, "error")


def test_smooth_only_still_checks_preproc(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    next(fmriprep.rglob("*desc-preproc_bold.nii.gz")).unlink()
    assert "preproc_missing" in ids(pf(tmp_path, bids, fmriprep, actions=["smooth"]), "error")


def test_dataset_action_runs_full_checks(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    for f in bids.rglob("*_events.tsv"):
        f.unlink()
    assert "events_missing" in ids(pf(tmp_path, bids, fmriprep, actions=["smooth", "dataset"]), "error")


EV_RT = "onset\tduration\ttrial_type\tRT\n1\t1\ta\t0.5\n"


def test_event_columns_are_not_nuisance_regressors(tmp_path):
    bids, fmriprep = make_trees(tmp_path, events=EV_RT)
    model = write_model(tmp_path, x=("trial_type.a", "RT", 1))
    assert "confound_columns" not in ids(pf(tmp_path, bids, fmriprep, model_file=model), "error")


def test_transformation_outputs_are_not_nuisance_regressors(tmp_path):
    model = write_model(tmp_path, x=("trial_type.a", "rt_scaled", 1), transformations=True)
    data = json.loads(model.read_text())
    data["Nodes"][0]["Transformations"]["Instructions"][0]["Output"] = ["rt_scaled"]
    model.write_text(json.dumps(data))
    assert "confound_columns" not in ids(run(tmp_path, model_file=model), "error")


def test_unmatched_name_with_transformations_is_only_a_warning(tmp_path):
    model = write_model(tmp_path, x=("trial_type.a", "mystery", 1), transformations=True)
    result = run(tmp_path, model_file=model)
    assert "confound_columns" not in ids(result, "error") and "confound_columns" in ids(result, "warn")


def test_transformations_without_instructions_count_as_none(tmp_path):
    model = write_model(tmp_path, x=("trial_type.zzz", 1))
    data = json.loads(model.read_text())
    data["Nodes"][0]["Transformations"] = {"Transformer": "bidspm", "Instructions": []}
    model.write_text(json.dumps(data))
    assert "condition_missing" in ids(run(tmp_path, model_file=model), "error")


def test_negative_onset_only_warns(tmp_path):
    bids, fmriprep = make_trees(tmp_path, events="onset\tduration\ttrial_type\n-1\t1\ta\n")
    result = pf(tmp_path, bids, fmriprep)
    assert "events_values" not in ids(result, "error") and "events_values" in ids(result, "warn")


def test_dataset_level_events_file_is_inherited(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    (bids / "sub-01" / "func" / "sub-01_task-x_events.tsv").rename(bids / "task-x_events.tsv")
    result = pf(tmp_path, bids, fmriprep, model_file=write_model(tmp_path))
    assert ids(result, "error") == set()
    (bids / "task-x_events.tsv").write_text("onset\tduration\ttrial_type\nsoon\t1\ta\n")
    assert "events_values" in ids(pf(tmp_path, bids, fmriprep), "error")


def test_validator_json_tolerates_banner_braces_and_trailing_text(tmp_path, fake_exe):
    out = check_validator(tmp_path, "prism", run=fake_run("using {cfg}\n" + json.dumps(REPORT) + "\ndone {x}\n"))
    assert "PRISM301" in out[0]["message"]


def test_validator_gets_the_resolved_bids_path(tmp_path, fake_exe, monkeypatch):
    calls = []
    sub = tmp_path / "d"
    sub.mkdir()
    monkeypatch.chdir(tmp_path)
    check_validator("d", "prism", run=fake_run(json.dumps({"issues": []}), 0, calls))
    assert calls[0][1] == str(sub.resolve())


def test_string_tasks_and_subjects_are_single_items(tmp_path):
    bids, fmriprep = make_trees(tmp_path, subjects=("01", "02"))
    cfg = {"BIDS_DIR": str(bids), "FMRIPREP_DIR": str(fmriprep), "SPACE": "MNI", "TASKS": "x", "SUBJECTS": "01"}
    result = run_preflight_from_config(cfg, validator="skip")
    assert ids(result, "error") == set()
    assert run_preflight_from_config({**cfg, "TASKS": None, "SUBJECTS": None}, validator="skip")["verdict"]


def test_validator_errors_are_grouped_by_code_and_message(tmp_path, fake_exe):
    issues = [{"code": "PRISM301", "severity": "ERROR", "message": "'Keywords' is required\nx", "file_path": f"/d/f{n}"} for n in range(527)]
    out = check_validator(tmp_path, "prism", run=fake_run(json.dumps({"issues": issues})))
    assert len(out) == 1
    assert "PRISM301 x527" in out[0]["message"] and "'Keywords' is required" in out[0]["message"] and "e.g. /d/f0" in out[0]["message"]
    assert "--validator bids" in out[0]["fix"] and "'skip'" in out[0]["fix"]


def test_validator_group_cap_counts_groups(tmp_path, fake_exe):
    issues = [{"code": f"E{n % 25}", "severity": "ERROR", "message": "m", "file_path": "f"} for n in range(100)]
    out = check_validator(tmp_path, "prism", run=fake_run(json.dumps({"issues": issues})))
    assert len(out) == 21 and "+5 more" in out[-1]["message"]
