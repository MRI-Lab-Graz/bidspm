# tests/test_model_wizard.py
import pytest

from lib.model_wizard import NUISANCE_PRESETS, RECIPE_CATALOG, WizardError, build_model, second_level_nodes

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


@pytest.mark.parametrize("bad", [
    {"contrasts": []}, {"contrasts": {"pairs": {}}}, {"contrasts": {"auto": False, "pairs": ["x"]}},
    {"recipes": {}}, {"recipes": ["x"]}, {"exclude": "b"}, {"exclude": [1]}, {"name": 5}, {"task": ["x"]},
])
def test_malformed_choice_shapes_raise_wizard_error(bad):
    with pytest.raises(WizardError):
        build_model(choices(**bad), SCAN)


@pytest.mark.parametrize("args", [("nope", SCAN), (choices(), "nope")])
def test_non_dict_choices_or_scan_raise_wizard_error(args):
    with pytest.raises(WizardError):
        build_model(*args)


@pytest.mark.parametrize("pair", [
    {"name": "x", "positive": ["trial_type.a"], "negative": ["trial_type.a", "trial_type.b"]},
    {"name": "x", "positive": ["trial_type.a", "trial_type.a"], "negative": ["trial_type.b"]},
    {"name": "x", "positive": ["trial_type.a"], "negative": ["trial_type.b", "trial_type.b"]},
])
def test_pair_overlap_or_repeat_is_rejected(pair):
    with pytest.raises(WizardError):
        build_model(choices(contrasts={"auto": False, "pairs": [pair]}), SCAN)


def test_unknown_exclude_value_is_rejected():
    with pytest.raises(WizardError):
        build_model(choices(exclude=["typo"]), SCAN)


def _scan_with(values):
    return {**SCAN, "columns": {"trial_type": values}}


def test_auto_contrast_names_are_sanitized():
    result = build_model(choices(), _scan_with(["a-b"]))
    (contrast,) = run_node(result)["Contrasts"]
    assert contrast["Name"] == "a_b" and contrast["ConditionList"] == ["trial_type.a-b"]


@pytest.mark.parametrize("values", [["a-b", "a_b"], [""]])
def test_auto_contrast_names_colliding_or_empty_are_rejected(values):
    with pytest.raises(WizardError):
        build_model(choices(), _scan_with(values))


def test_catalog_lists_the_recipes_with_param_kinds():
    ids = [r["id"] for r in RECIPE_CATALOG]
    assert "valid_only" in ids and "split_by_column" in ids
    valid = next(r for r in RECIPE_CATALOG if r["id"] == "valid_only")
    assert [p["name"] for p in valid["params"]][:3] == ["condition", "column", "value"]


def valid_only(**over):
    return {"id": "valid_only", "condition": "item", "column": "response_validity", "value": "valid", **over}


def test_valid_only_reproduces_the_141_filter_chain():
    result = build_model(choices(recipes=[valid_only()]), SCAN)
    node = run_node(result)
    assert node["Transformations"]["Instructions"] == [
        {"Name": "Filter", "Input": "trial_type", "Query": "trial_type==item", "Output": "trial_item"},
        {"Name": "Filter", "Input": "trial_item", "Query": "response_validity==valid", "Output": "valid_item"},
    ]
    assert node["Model"]["X"][:3] == ["trial_type.a", "trial_type.b", "valid_item.item"]
    assert "trial_type.item" not in node["Model"]["X"]
    assert any("invalid" in w for w in result["preview"]["warnings"])  # the dropped trials are announced


def test_valid_only_can_keep_the_original_regressor():
    x = run_node(build_model(choices(recipes=[valid_only(keep_original=True)]), SCAN))["Model"]["X"]
    assert "trial_type.item" in x and "valid_item.item" in x


def test_split_by_column_makes_one_regressor_per_value_with_one_shared_first_filter():
    recipe = {"id": "split_by_column", "condition": "item", "column": "response_validity"}
    node = run_node(build_model(choices(recipes=[recipe]), SCAN))
    instr = node["Transformations"]["Instructions"]
    assert [i["Output"] for i in instr] == ["trial_item", "valid_item", "invalid_item"]
    assert {"valid_item.item", "invalid_item.item"} <= set(node["Model"]["X"])


def test_split_by_column_respects_a_value_subset():
    recipe = {"id": "split_by_column", "condition": "item", "column": "response_validity", "values": ["invalid"]}
    x = run_node(build_model(choices(recipes=[recipe]), SCAN))["Model"]["X"]
    assert "invalid_item.item" in x and "valid_item.item" not in x


@pytest.mark.parametrize("bad", [
    valid_only(condition="nope"),                      # unknown condition
    valid_only(column="nope"),                         # unknown column
    valid_only(column="trial_type"),                   # trial_type itself
    valid_only(value="maybe"),                         # value not in the column
    valid_only(value="va lid"),                        # unsafe in a query
    {"id": "no_such_recipe"},
])
def test_invalid_recipe_params_raise(bad):
    scan = {**SCAN, "columns": {**SCAN["columns"], "response_validity": ["valid", "invalid", "va lid"]}}
    with pytest.raises(WizardError):
        build_model(choices(recipes=[bad]), scan)


def test_a_condition_used_by_an_earlier_recipe_is_no_longer_available():
    with pytest.raises(WizardError):
        build_model(choices(recipes=[valid_only(), valid_only(value="invalid")]), SCAN)


SPLIT = {"id": "split_by_column", "condition": "item", "column": "response_validity"}


@pytest.mark.parametrize("bad", [
    valid_only(condition=5), valid_only(condition=["item"]), valid_only(column=5), valid_only(column=["x"]),
    valid_only(value=1), valid_only(value=["valid"]),
    valid_only(keep_original="yes"), valid_only(keep_original=1),
    {**SPLIT, "values": "valid"}, {**SPLIT, "values": [1]}, {**SPLIT, "values": {"a": 1}},
    {**SPLIT, "condition": 5}, {**SPLIT, "column": 5}, {**SPLIT, "keep_original": "no"},
])
def test_wrongly_typed_recipe_params_raise_wizard_error(bad):
    with pytest.raises(WizardError):
        build_model(choices(recipes=[bad]), SCAN)


def test_missing_or_none_keep_original_means_false():
    x = run_node(build_model(choices(recipes=[valid_only(keep_original=None)]), SCAN))["Model"]["X"]
    assert "trial_type.item" not in x
