"""M4/M10/L5: custom nuisance, non-ASCII trial_type values and model names in the wizard engine and its route."""
import pytest

from bidspm_gui import app
from lib.model_wizard import WizardError, build_model
from tests.preflight_support import confounds_for, make_trees
from tests.test_model_wizard import SCAN, choices, run_node

UNI = {**SCAN, "columns": {**SCAN["columns"], "trial_type": ["a", "b", "é"]}}


def x_of(result):
    return run_node(result)["Model"]["X"]


# ---- M4 -----------------------------------------------------------------------------------------
def test_custom_nuisance_is_deduplicated_keeping_order():
    x = x_of(build_model(choices(nuisance=["trans_x", "csf", "trans_x", "csf"]), SCAN))
    assert x[-2:] == ["trans_x", "csf"] and x.count("trans_x") == 1


@pytest.mark.parametrize("bad", [["1"], ["0"], ["trial_type.a"], ["trial_type."], ["trans_x", "trial_type.zzz"], ["  "], [" 1 "]])
def test_custom_nuisance_rejects_intercept_and_condition_references(bad):
    with pytest.raises(WizardError, match="nuisance"):
        build_model(choices(nuisance=bad), SCAN)


def test_custom_nuisance_equal_to_a_regressor_is_rejected():
    with pytest.raises(WizardError, match="regressor"):
        build_model(choices(nuisance=["trial_type.a"]), SCAN)
    result = build_model(choices(recipes=[{"id": "merge_rename", "sources": ["a", "b"], "target": "ab"}], nuisance=["ab", "csf"]), SCAN)
    assert "ab" in x_of(result)  # a bare name is a confound column, not the regressor trial_type.ab


def test_unknown_confound_column_is_a_warning_not_an_error():
    scan = {**SCAN, "confound_columns": ["trans_x", "a_comp_cor_00", "a_comp_cor_01"]}
    result = build_model(choices(nuisance=["trans_x", "csf", "a_comp_cor_*"]), scan)
    warnings = result["preview"]["warnings"]
    assert any("csf" in w and "confound" in w for w in warnings)
    assert not any("trans_x" in w for w in warnings) and not any("a_comp_cor_*" in w for w in warnings)
    assert x_of(result)[-3:] == ["trans_x", "csf", "a_comp_cor_*"]


def test_no_confound_warning_when_the_columns_are_unknown():
    assert build_model(choices(nuisance=["csf"]), SCAN | {"confound_columns": []})["preview"]["warnings"] == []


def test_route_reads_confound_columns_for_a_custom_list(tmp_path):
    bids, fmriprep = make_trees(tmp_path, confounds=confounds_for(100))
    body = {"bids_dir": str(bids), "fmriprep_dir": str(fmriprep), "space": "MNI", "preflight": False,
            "choices": choices(nuisance=["trans_x", "csf"])}
    warnings = app.test_client().post("/api/wizard/build", json=body).get_json()["preview"]["warnings"]
    assert [w for w in warnings if "csf" in w] and not [w for w in warnings if "trans_x" in w]


def test_route_adds_scan_warnings_to_the_preview(tmp_path):
    bids, fmriprep = make_trees(tmp_path, events="onset\tduration\ttrial_type\ttrial_type\n1\t1\ta\tb\n5\t1\tb\tb\n")
    body = {"bids_dir": str(bids), "fmriprep_dir": str(fmriprep), "space": "MNI", "preflight": False, "choices": choices()}
    warnings = app.test_client().post("/api/wizard/build", json=body).get_json()["preview"]["warnings"]
    assert any("duplicate column trial_type" in w for w in warnings)


# ---- M10 (relaxed after review: only what really fails is refused) -----------------------------
def scan_with(*values):
    return {**SCAN, "columns": {**SCAN["columns"], "trial_type": list(values)}}


def test_non_ascii_only_value_gets_a_clear_contrast_name_message():
    with pytest.raises(WizardError) as exc:
        build_model(choices(), UNI)
    msg = str(exc.value)
    assert "'é'" in msg and "contrast name" in msg and "MATLAB" not in msg
    assert "rename it in the events" in msg and "Merge" in msg and "uncheck it in step 1" in msg


@pytest.mark.parametrize("value", ["a b", "x.y", "naïve", "a/b"])
def test_spaces_dots_and_partly_non_ascii_values_build_as_plain_regressors(value):
    result = build_model(choices(), scan_with("a", value))
    assert result["preview"]["regressors"] == ["trial_type.a", f"trial_type.{value}"]
    names = result["preview"]["contrasts"]
    assert len(set(names)) == len(names) and all(n.replace("_", "").isalnum() for n in names)


def test_values_that_sanitise_to_the_same_contrast_name_are_still_caught():
    with pytest.raises(WizardError, match="duplicate contrast names"):
        build_model(choices(), scan_with("a b", "a_b"))
    assert build_model(choices(contrasts={"auto": False, "pairs": [{"name": "p", "positive": ["trial_type.a b"], "negative": ["trial_type.a_b"]}]}),
                       scan_with("a b", "a_b"))["preview"]["regressors"] == ["trial_type.a b", "trial_type.a_b"]


def test_excluded_unsupported_condition_does_not_block():
    result = build_model(choices(exclude=["é"]), UNI)
    assert result["preview"]["regressors"] == ["trial_type.a", "trial_type.b"]


def test_unsupported_value_without_auto_contrasts_builds():
    result = build_model(choices(contrasts={"auto": False, "pairs": [{"name": "p", "positive": ["trial_type.a"], "negative": ["trial_type.b"]}]}), UNI)
    assert "trial_type.é" in result["preview"]["regressors"]


@pytest.mark.parametrize("recipe", [
    {"id": "valid_only", "condition": "a b", "column": "response_validity", "value": "valid"},
    {"id": "split_by_column", "condition": "a b", "column": "response_validity"},
    {"id": "merge_rename", "sources": ["a b"], "target": "t"},
])
def test_value_reaching_a_filter_or_replace_is_rejected_naming_the_recipe(recipe):
    with pytest.raises(WizardError) as exc:
        build_model(choices(recipes=[recipe]), scan_with("a b", "b"))
    msg = str(exc.value)
    assert "'a b'" in msg and recipe["id"] in msg and "uncheck it in step 1" in msg


def test_hyphen_and_underscore_values_are_fine():
    assert build_model(choices(), scan_with("a-1", "b_2"))["preview"]["regressors"] == ["trial_type.a-1", "trial_type.b_2"]


# ---- L5 -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["-x", "1abc", "../../etc/x", "ünï", "a b"])
def test_model_names_are_labels_any_text_is_allowed(name):
    assert build_model(choices(name=name), SCAN)["model"]["Name"] == name


@pytest.mark.parametrize("name", ["a\x00b", "a\nb", "x" * 201, "a\tb"])
def test_model_name_with_control_characters_or_absurd_length_is_rejected(name):
    with pytest.raises(WizardError, match="name"):
        build_model(choices(name=name), SCAN)
