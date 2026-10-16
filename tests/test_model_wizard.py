# tests/test_model_wizard.py
import pytest

from lib.model_wizard import NUISANCE_PRESETS, WizardError, build_model, second_level_nodes

SCAN = {
    "tasks": ["x"],
    "columns": {"trial_type": ["a", "b", "item"], "response_validity": ["valid", "invalid"],
                "rt": ["0.5", "0.7"], "ai_rating": ["1", "2"]},
    "numeric": ["rt", "ai_rating"],
    "confound_columns": ["trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z", "framewise_displacement"],
}


def choices(**over):
    base = {"task": "x", "name": "m", "recipes": [], "nuisance": "none", "exclude": [],
            "contrasts": {"auto": True, "pairs": []}}
    base.update(over)
    return base


def run_node(result):
    return next(n for n in result["model"]["Nodes"] if n["Level"] == "Run")


def test_base_model_has_run_subject_dataset_nodes():
    model = build_model(choices(), SCAN)["model"]
    assert [n["Level"] for n in model["Nodes"]] == ["Run", "Subject", "Dataset"]
    assert model["Input"] == {"task": ["x"]} and model["Name"] == "m"


def test_run_node_models_every_condition_plus_intercept():
    node = run_node(build_model(choices(), SCAN))
    assert node["Model"]["X"] == ["trial_type.a", "trial_type.b", "trial_type.item", 1]
    assert node["Model"]["HRF"]["Variables"] == ["trial_type.a", "trial_type.b", "trial_type.item"]
    assert node["Name"] == "run_level" and node["Model"]["Software"]["SPM"]["SerialCorrelation"] == "FAST"
    assert "Transformations" not in node


def test_exclude_drops_conditions():
    node = run_node(build_model(choices(exclude=["b"]), SCAN))
    assert "trial_type.b" not in node["Model"]["X"]


def test_auto_contrasts_one_per_regressor_and_second_level_mirrors_them():
    result = build_model(choices(), SCAN)
    names = result["preview"]["contrasts"]
    assert names == ["a", "b", "item"]
    run = run_node(result)
    assert run["Contrasts"][0] == {"Name": "a", "ConditionList": ["trial_type.a"], "Weights": [1], "Test": "t"}
    subject, dataset = result["model"]["Nodes"][1:]
    assert subject["Model"]["X"] == names and [c["Name"] for c in dataset["Contrasts"]] == names


def test_pair_contrast_weights_are_balanced():
    pairs = [{"name": "a_gt_bi", "positive": ["trial_type.a"], "negative": ["trial_type.b", "trial_type.item"]}]
    run = run_node(build_model(choices(contrasts={"auto": False, "pairs": pairs}), SCAN))
    (contrast,) = run["Contrasts"]
    assert contrast["ConditionList"] == ["trial_type.a", "trial_type.b", "trial_type.item"]
    assert contrast["Weights"] == [1, -0.5, -0.5]


@pytest.mark.parametrize("pair", [
    {"name": "bad name", "positive": ["trial_type.a"], "negative": ["trial_type.b"]},      # not [A-Za-z0-9_]+
    {"name": "x", "positive": ["trial_type.nope"], "negative": ["trial_type.b"]},          # unknown regressor
    {"name": "x", "positive": [], "negative": ["trial_type.b"]},                           # empty side
])
def test_invalid_pair_is_rejected(pair):
    with pytest.raises(WizardError):
        build_model(choices(contrasts={"auto": False, "pairs": [pair]}), SCAN)


def test_duplicate_contrast_names_are_rejected():
    pair = {"name": "a", "positive": ["trial_type.a"], "negative": ["trial_type.b"]}  # clashes with auto "a"
    with pytest.raises(WizardError):
        build_model(choices(contrasts={"auto": True, "pairs": [pair]}), SCAN)


def test_nuisance_presets_and_custom_list():
    assert "framewise_displacement" in NUISANCE_PRESETS["motion6_fd"] and len(NUISANCE_PRESETS["motion24"]) == 24
    x = run_node(build_model(choices(nuisance="motion6"), SCAN))["Model"]["X"]
    assert x[-6:] == NUISANCE_PRESETS["motion6"] and 1 in x
    x = run_node(build_model(choices(nuisance=["trans_x", "csf"]), SCAN))["Model"]["X"]
    assert x[-2:] == ["trans_x", "csf"]


@pytest.mark.parametrize("bad", [
    {"task": "nope"}, {"nuisance": "everything"}, {"exclude": ["a", "b", "item"]},
])
def test_invalid_choices_raise_wizard_error(bad):
    with pytest.raises(WizardError):
        build_model(choices(**bad), SCAN)


def test_missing_trial_type_column_raises():
    with pytest.raises(WizardError):
        build_model(choices(), {**SCAN, "columns": {"rt": ["1"]}})


def test_second_level_nodes_shape():
    subject, dataset = second_level_nodes(["a"])
    assert subject["GroupBy"] == ["subject", "contrast"] and dataset["Model"]["X"] == [1]
    assert second_level_nodes([])[0]["Model"]["X"] == ["contrast"]
