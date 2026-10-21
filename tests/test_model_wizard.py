# tests/test_model_wizard.py
import pytest

from lib.model_wizard import NUISANCE_PRESETS, RECIPE_CATALOG, WizardError, build_model, catalog, second_level_nodes

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
    assert subject["Contrasts"] == run["Contrasts"] and dataset["DummyContrasts"]["Contrasts"] == names


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


RUN_CONTRASTS = [{"Name": "a", "ConditionList": ["trial_type.a"], "Weights": [1], "Test": "t"},
                 {"Name": "a_gt_b", "ConditionList": ["trial_type.a", "trial_type.b"], "Weights": [1, -1], "Test": "t"}]


RESULTS_ALL = {"bidspm": {"Results": [{"name": ["a", "a_gt_b"], "nidm": False, "png": False}]}}  # bidsResults reads Model.Software.bidspm.Results per node


def test_subject_and_dataset_nodes_ask_for_results_of_every_contrast():
    # without it the "SPM Results export" logs 'Specify node names and levels in "opt.results"' and writes nothing
    model = build_model(choices(), SCAN)["model"]
    run, subject, dataset = model["Nodes"]
    names = [c["Name"] for c in run["Contrasts"]]
    assert "bidspm" not in run["Model"]["Software"]
    for node in (subject, dataset):
        assert node["Model"]["Software"] == {"bidspm": {"Results": [{"name": names, "nidm": False, "png": False}]}}


def test_second_level_structure_is_the_one_verified_in_bidspm():
    # Golden: this exact structure ran to a dataset-level SPM.mat per contrast in bidspm 4.0.0 (track W report, attempt C).
    nodes, edges = second_level_nodes(RUN_CONTRASTS)
    assert nodes == [
        {"Level": "Subject", "Name": "subject_level", "GroupBy": ["subject", "contrast"],
         "Model": {"Type": "glm", "X": [1], "Software": RESULTS_ALL}, "Contrasts": RUN_CONTRASTS},
        {"Level": "Dataset", "Name": "dataset", "GroupBy": ["contrast"],
         "Model": {"Type": "glm", "X": [1], "Software": RESULTS_ALL},
         "DummyContrasts": {"Test": "t", "Contrasts": ["a", "a_gt_b"]}},
    ]
    assert edges == [{"Source": "run_level", "Destination": "subject_level"},
                     {"Source": "subject_level", "Destination": "dataset", "Filter": {"contrast": ["a", "a_gt_b"]}}]
    assert "DummyContrasts" not in nodes[0]  # Subject DummyContrasts add condition-named duplicates in bidspm
    assert nodes[0]["Contrasts"] is not RUN_CONTRASTS  # a copy, not shared with the Run node


def test_build_model_emits_the_verified_second_level_and_edges():
    model = build_model(choices(), SCAN)["model"]
    run, subject, dataset = model["Nodes"]
    assert "DummyContrasts" not in run and "DummyContrasts" not in subject
    assert subject["Contrasts"] == run["Contrasts"]
    assert model["Edges"] == second_level_nodes(run["Contrasts"])[1]


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
    assert "trial_type.item" in x and "valid_item.valid_item" in x


def test_split_by_column_makes_one_regressor_per_value_with_one_shared_first_filter():
    recipe = {"id": "split_by_column", "condition": "item", "column": "response_validity"}
    node = run_node(build_model(choices(recipes=[recipe]), SCAN))
    instr = node["Transformations"]["Instructions"]
    assert [(i["Name"], i["Output"]) for i in instr] == [
        ("Filter", "trial_item"), ("Filter", "valid_item"), ("Replace", "valid_item"),
        ("Filter", "invalid_item"), ("Replace", "invalid_item")]
    assert {"valid_item.valid_item", "invalid_item.invalid_item"} <= set(node["Model"]["X"])


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


def _scan_cols(**cols):
    return {**SCAN, "columns": {**SCAN["columns"], **cols}}


@pytest.mark.parametrize("bad, cols", [
    (valid_only(value="0.5"), {"response_validity": ["0.5", "x"]}),          # '.' corrupts column.value names
    (valid_only(condition="a.b"), {}),
    (valid_only(column="a-b"), {"a-b": ["x", "y"]}),                         # '-' is not allowed in a column
    (valid_only(value="-"), {"response_validity": ["-", "x"]}),              # nothing left after coercion
    (valid_only(value="a<b"), {"response_validity": ["a<b", "x"]}),          # Filter query operators
    (valid_only(value="a~b"), {"response_validity": ["a~b", "x"]}),
    (valid_only(value="a|b"), {"response_validity": ["a|b", "x"]}),          # right side is a regex
    (valid_only(value="a*"), {"response_validity": ["a*", "x"]}),
])
def test_names_outside_word_characters_are_rejected(bad, cols):
    scan = _scan_cols(**cols)
    scan["columns"]["trial_type"] = ["a", "b", "item", "a.b"]
    with pytest.raises(WizardError):
        build_model(choices(recipes=[bad]), scan)


def test_split_by_column_on_a_numeric_column_needs_explicit_values():
    recipe = {"id": "split_by_column", "condition": "item", "column": "rt"}
    with pytest.raises(WizardError, match="numeric"):
        build_model(choices(recipes=[recipe]), SCAN)


def test_output_names_clashing_with_events_columns_are_rejected():
    scan = _scan_cols(trial_item=["1"])
    with pytest.raises(WizardError):
        build_model(choices(recipes=[valid_only()]), scan)
    scan = _scan_cols(valid_item=["1"])
    with pytest.raises(WizardError):
        build_model(choices(recipes=[valid_only()]), scan)


def test_first_filter_is_not_chained_onto_a_foreign_instruction_with_the_same_output():
    scan = _scan_cols(c=["trial_a", "z"])
    scan["columns"]["trial_type"] = ["b", "a_b"]
    first = {"id": "split_by_column", "condition": "b", "column": "c", "values": ["trial_a"]}  # output trial_a_b
    second = {"id": "split_by_column", "condition": "a_b", "column": "c", "values": ["z"]}     # first filter trial_a_b
    with pytest.raises(WizardError):
        build_model(choices(recipes=[first, second]), scan)


def test_valid_only_with_keep_original_does_not_warn():
    result = build_model(choices(recipes=[valid_only(keep_original=True)]), SCAN)
    assert result["preview"]["warnings"] == []


def test_duplicate_split_values_are_deduped():
    recipe = {**SPLIT, "values": ["valid", "valid", "invalid"]}
    instr = run_node(build_model(choices(recipes=[recipe]), SCAN))["Transformations"]["Instructions"]
    assert [i["Output"] for i in instr if i["Name"] == "Filter"] == ["trial_item", "valid_item", "invalid_item"]


def test_catalog_returns_a_deep_copy():
    c = catalog()
    c[0]["params"][0]["name"] = "mutated"
    c.append("x")
    assert catalog()[0]["params"][0]["name"] != "mutated" and len(catalog()) == len(RECIPE_CATALOG)


HY_SCAN = {**SCAN, "columns": {**SCAN["columns"], "trial_type": ["a", "face-happy"],
                               "response_validity": ["valid-trial", "invalid"]}}


def test_hyphenated_names_keep_raw_query_and_coerced_outputs():
    result = build_model(choices(recipes=[valid_only(condition="face-happy", value="valid-trial")]), HY_SCAN)
    node = run_node(result)
    assert node["Transformations"]["Instructions"] == [
        {"Name": "Filter", "Input": "trial_type", "Query": "trial_type==face-happy", "Output": "trial_facehappy"},
        {"Name": "Filter", "Input": "trial_facehappy", "Query": "response_validity==valid-trial",
         "Output": "validtrial_facehappy"},
    ]
    assert node["Model"]["X"][:2] == ["trial_type.a", "validtrial_facehappy.face-happy"]
    assert [c["Name"] for c in node["Contrasts"]] == ["a", "validtrial_facehappy_face_happy"]
    assert result["preview"]["contrasts"] == ["a", "validtrial_facehappy_face_happy"]


def test_names_that_collide_after_coercion_are_rejected():
    scan = {**HY_SCAN, "columns": {**HY_SCAN["columns"], "trial_type": ["face-happy", "facehappy"]}}
    recipes = [valid_only(condition="face-happy", value="valid-trial", keep_original=True),
               valid_only(condition="facehappy", value="valid-trial")]
    with pytest.raises(WizardError):
        build_model(choices(recipes=recipes), scan)


def test_merge_rename_emits_a_replace_and_swaps_the_regressors():
    recipe = {"id": "merge_rename", "sources": ["a", "b"], "target": "ab"}
    node = run_node(build_model(choices(recipes=[recipe]), SCAN))
    assert node["Transformations"]["Instructions"] == [
        {"Name": "Replace", "Input": "trial_type", "Output": "trial_type",
         "Replace": [{"key": "^a$", "value": "ab"}, {"key": "^b$", "value": "ab"}]}]
    assert node["Model"]["X"] == ["trial_type.item", "trial_type.ab", 1]


def test_rename_a_single_condition():
    recipe = {"id": "merge_rename", "sources": ["item"], "target": "word"}
    x = run_node(build_model(choices(recipes=[recipe]), SCAN))["Model"]["X"]
    assert "trial_type.word" in x and "trial_type.item" not in x


def test_filter_after_merge_uses_the_new_name():
    recipes = [{"id": "merge_rename", "sources": ["item"], "target": "word"}, valid_only(condition="word")]
    instr = run_node(build_model(choices(recipes=recipes), SCAN))["Transformations"]["Instructions"]
    assert instr[1]["Query"] == "trial_type==word"


def test_merge_dedupes_sources_and_allows_hyphens():
    recipe = {"id": "merge_rename", "sources": ["a", "a"], "target": "a-b"}
    node = run_node(build_model(choices(recipes=[recipe]), SCAN))
    assert node["Transformations"]["Instructions"][0]["Replace"] == [{"key": "^a$", "value": "a-b"}]


@pytest.mark.parametrize("bad", [
    {"id": "merge_rename", "sources": [], "target": "x"},
    {"id": "merge_rename", "sources": ["nope"], "target": "x"},
    {"id": "merge_rename", "sources": ["a"], "target": "bad name"},
    {"id": "merge_rename", "sources": ["a"], "target": "a.b"},
    {"id": "merge_rename", "sources": ["a"], "target": ""},
    {"id": "merge_rename", "sources": ["a"], "target": 5},
    {"id": "merge_rename", "sources": ["a"], "target": None},
    {"id": "merge_rename", "sources": "a", "target": "x"},
    {"id": "merge_rename", "sources": None, "target": "x"},
    {"id": "merge_rename", "sources": [1], "target": "x"},
])
def test_invalid_merge_raises(bad):
    with pytest.raises(WizardError):
        build_model(choices(recipes=[bad]), SCAN)


def pmod(**over):
    return {"id": "parametric_modulator", "regressor": "trial_type.item", "column": "ai_rating", **over}


def test_parametric_modulator_matches_the_141_format_and_adds_contrasts():
    recipes = [valid_only(), pmod(regressor="valid_item.item", polynomial=2)]
    result = build_model(choices(recipes=recipes), SCAN)
    node = run_node(result)
    assert node["Model"]["Software"]["SPM"]["ParametricModulations"] == [
        {"Name": "ai_rating_mod", "Conditions": ["valid_item.item"], "Values": ["ai_rating"], "PolynomialExpansion": 2}]
    by_name = {c["Name"]: c for c in node["Contrasts"]}
    assert by_name["valid_item_item_ai_rating_mod_lin"]["ConditionList"] == ["valid_item.item:ai_rating_mod^1"]
    assert by_name["valid_item_item_ai_rating_mod_quad"]["ConditionList"] == ["valid_item.item:ai_rating_mod^2"]


def test_pmod_contrast_names_do_not_end_in_a_digit():
    # bidspm (BidsModel.validateConditionNames) warns that names ending in _<digit> may break results
    result = build_model(choices(recipes=[pmod(polynomial=3), pmod(polynomial=1)]), SCAN)
    names = result["preview"]["contrasts"]
    assert "item_ai_rating_mod_cub" in names and "item_ai_rating_mod2_lin" in names
    assert not [n for n in names if n[-1].isdigit()] and len(set(names)) == len(names)


def test_polynomial_one_omits_the_expansion_key():
    node = run_node(build_model(choices(recipes=[pmod()]), SCAN))
    assert "PolynomialExpansion" not in node["Model"]["Software"]["SPM"]["ParametricModulations"][0]


SCAN_HYPHEN_COLUMN = {**SCAN, "columns": {**SCAN["columns"], "ai-rating": ["1", "2"]},
                      "numeric": ["rt", "ai_rating", "ai-rating"]}


@pytest.mark.parametrize("bad", [
    pmod(regressor="trial_type.nope"),          # not a current regressor
    pmod(column="response_validity"),           # not numeric
    pmod(polynomial=0), pmod(polynomial=4),     # out of range 1..3
    pmod(polynomial=True), pmod(polynomial="2"), pmod(polynomial=1.5),
    pmod(regressor=None), pmod(regressor=["trial_type.item"]),
    pmod(column=None), pmod(column=3), pmod(column=["rt"]),
])
def test_invalid_pmod_raises(bad):
    with pytest.raises(WizardError):
        build_model(choices(recipes=[bad]), SCAN)


def test_pmod_column_with_non_word_characters_is_rejected():
    with pytest.raises(WizardError, match="rename"):
        build_model(choices(recipes=[pmod(column="ai-rating")]), SCAN_HYPHEN_COLUMN)


def test_two_pmods_on_the_same_column_get_unique_names():
    recipes = [pmod(), pmod(regressor="trial_type.a")]
    names = [m["Name"] for m in run_node(build_model(choices(recipes=recipes), SCAN))["Model"]["Software"]["SPM"]["ParametricModulations"]]
    assert len(set(names)) == 2


def test_merge_consuming_a_pmod_regressor_is_rejected():
    recipes = [pmod(), {"id": "merge_rename", "sources": ["item"], "target": "word"}]
    with pytest.raises(WizardError, match="parametric"):
        build_model(choices(recipes=recipes), SCAN)


def test_split_dropping_a_pmod_regressor_is_rejected_unless_kept():
    split = {"id": "split_by_column", "condition": "item", "column": "response_validity"}
    with pytest.raises(WizardError, match="parametric"):
        build_model(choices(recipes=[pmod(), split]), SCAN)
    build_model(choices(recipes=[pmod(), {**split, "keep_original": True}]), SCAN)


def merge(sources, target):
    return {"id": "merge_rename", "sources": sources, "target": target}


def test_merge_target_consumed_by_an_earlier_recipe_is_rejected():
    with pytest.raises(WizardError, match="already"):
        build_model(choices(recipes=[valid_only(condition="item"), merge(["a"], "item")]), SCAN)


def test_merge_target_excluded_is_rejected():
    with pytest.raises(WizardError, match="already"):
        build_model(choices(exclude=["b"], recipes=[merge(["a"], "b")]), SCAN)


def test_merge_onto_an_existing_regressor_is_allowed():
    node = run_node(build_model(choices(recipes=[merge(["a"], "b")]), SCAN))
    assert node["Model"]["X"] == ["trial_type.b", "trial_type.item", 1]


def test_merge_target_onto_a_regressor_with_a_pmod_is_rejected():
    with pytest.raises(WizardError, match="parametric"):
        build_model(choices(recipes=[pmod(regressor="trial_type.b"), merge(["a"], "b")]), SCAN)


def test_stale_first_filter_after_a_merge_is_not_reused():
    recipes = [valid_only(condition="a", keep_original=True), merge(["b"], "a"), valid_only(condition="a", value="invalid", keep_original=True)]
    with pytest.raises(WizardError, match="clash|earlier|stale"):
        build_model(choices(recipes=recipes), SCAN)


def test_merge_target_coercing_to_another_regressor_name_is_rejected():
    scan = {**SCAN, "columns": {**SCAN["columns"], "trial_type": ["face-happy", "a", "b"]}}
    with pytest.raises(WizardError, match="coerce|clash"):
        build_model(choices(recipes=[merge(["a"], "facehappy")]), scan)


SCAN_DIGITS = {**SCAN, "columns": {**SCAN["columns"], "response_validity": ["1", "2"]}}


def test_digit_leading_value_gets_a_v_prefix():
    result = build_model(choices(recipes=[valid_only(value="1")]), SCAN_DIGITS)
    node = run_node(result)
    assert node["Transformations"]["Instructions"][1] == {
        "Name": "Filter", "Input": "trial_item", "Query": "response_validity==1", "Output": "v1_item"}
    assert "v1_item.item" in node["Model"]["X"]


def test_split_by_column_with_digit_values():
    split = {"id": "split_by_column", "condition": "item", "column": "response_validity", "values": ["1", "2"]}
    node = run_node(build_model(choices(recipes=[split]), SCAN_DIGITS))
    assert [i["Output"] for i in node["Transformations"]["Instructions"] if i["Name"] == "Filter"] == ["trial_item", "v1_item", "v2_item"]
    assert node["Model"]["X"] == ["trial_type.a", "trial_type.b", "v1_item.v1_item", "v2_item.v2_item", 1]


def test_prefixed_output_still_clashes_with_an_events_column():
    scan = {**SCAN_DIGITS, "columns": {**SCAN_DIGITS["columns"], "v1_item": ["x"]}}
    with pytest.raises(WizardError, match="clash"):
        build_model(choices(recipes=[valid_only(value="1")]), scan)


def test_merge_after_a_split():
    split = {"id": "split_by_column", "condition": "item", "column": "response_validity", "values": ["valid"]}
    node = run_node(build_model(choices(recipes=[split, merge(["a", "b"], "ab")]), SCAN))
    assert node["Model"]["X"] == ["valid_item.item", "trial_type.ab", 1]


def test_chained_merges_apply_in_order():
    node = run_node(build_model(choices(recipes=[merge(["a"], "b"), merge(["b"], "c")]), SCAN))
    instr = node["Transformations"]["Instructions"]
    assert [i["Replace"][0]["key"] for i in instr] == ["^a$", "^b$"]
    assert node["Model"]["X"] == ["trial_type.item", "trial_type.c", 1]


import json
from pathlib import Path

GOLDEN = Path(__file__).resolve().parent.parent / "studies" / "141_fix_pmod.json"


@pytest.mark.skipif(not GOLDEN.is_file(), reason="studies/141_fix_pmod.json not present")
def test_wizard_reproduces_the_141_run_node():
    ref = next(n for n in json.loads(GOLDEN.read_text())["Nodes"] if n["Level"] == "Run")
    scan = {"tasks": ["crom"],
            "columns": {"trial_type": ["button_press", "fixation", "item", "rating", "verbal_response"],
                        "response_validity": ["valid", "invalid"], "ai_rating": ["1", "2"]},
            "numeric": ["ai_rating"], "confound_columns": []}
    recipes = [valid_only(), pmod(regressor="valid_item.item", polynomial=2)]
    mine = run_node(build_model(choices(task="crom", name="crom", recipes=recipes, exclude=["fixation"],
                                        nuisance="motion6"), scan))
    assert mine["Transformations"] == ref["Transformations"]
    assert mine["Model"]["Software"]["SPM"]["ParametricModulations"] == ref["Model"]["Software"]["SPM"]["ParametricModulations"]
    assert {str(x) for x in mine["Model"]["X"]} == {str(x) for x in ref["Model"]["X"]}
    assert set(mine["Model"]["HRF"]["Variables"]) == set(ref["Model"]["HRF"]["Variables"])
    ref_pmod_conditions = {c["ConditionList"][0] for c in ref["Contrasts"] if ":" in c["ConditionList"][0]}
    assert ref_pmod_conditions <= {c["ConditionList"][0] for c in mine["Contrasts"]}


def test_dataset_node_is_named_dataset():
    # bidspm looks the Dataset node up by exact name; preflight warns otherwise
    assert second_level_nodes(RUN_CONTRASTS)[0][1]["Name"] == "dataset"


def spm_names(node):
    """The name bidspm gives the SPM condition: everything after the first '.' of the regressor."""
    return [r.split(".", 1)[1] for r in node["Model"]["X"] if isinstance(r, str) and "." in r]


def test_split_regressors_are_distinct_spm_conditions_with_a_rename_per_value():
    recipe = {"id": "split_by_column", "condition": "item", "column": "response_validity"}
    node = run_node(build_model(choices(recipes=[recipe]), SCAN))
    assert {"Name": "Replace", "Input": "valid_item", "Output": "valid_item",
            "Replace": [{"key": "^item$", "value": "valid_item"}]} in node["Transformations"]["Instructions"]
    assert len(set(spm_names(node))) == len(spm_names(node)) == 4
    assert [c["Name"] for c in node["Contrasts"]][-2:] == ["valid_item", "invalid_item"]


def test_keep_original_renames_the_split_regressor():
    node = run_node(build_model(choices(recipes=[valid_only(keep_original=True)]), SCAN))
    assert spm_names(node) == ["a", "b", "item", "valid_item"]


def test_single_value_split_keeps_the_141_form():
    node = run_node(build_model(choices(recipes=[valid_only()]), SCAN))
    assert "valid_item.item" in node["Model"]["X"]
    assert not any(i["Name"] == "Replace" for i in node["Transformations"]["Instructions"])


def test_hyphenated_condition_split_renames_with_an_escaped_key():
    recipe = {"id": "split_by_column", "condition": "face-happy", "column": "response_validity"}
    node = run_node(build_model(choices(recipes=[recipe]), HY_SCAN))
    replace = [i for i in node["Transformations"]["Instructions"] if i["Name"] == "Replace"]
    assert replace[0]["Replace"] == [{"key": "^face\\-happy$", "value": replace[0]["Output"]}]
    assert len(set(spm_names(node))) == len(spm_names(node))


def test_pmod_on_one_split_regressor_and_pair_contrast():
    recipe = {"id": "split_by_column", "condition": "item", "column": "response_validity"}
    pmod = {"id": "parametric_modulator", "regressor": "valid_item.valid_item", "column": "rt"}
    pair = {"name": "valid_gt_invalid", "positive": ["valid_item.valid_item"], "negative": ["invalid_item.invalid_item"]}
    node = run_node(build_model(choices(recipes=[recipe, pmod], contrasts={"auto": True, "pairs": [pair]}), SCAN))
    assert node["Model"]["Software"]["SPM"]["ParametricModulations"][0]["Conditions"] == ["valid_item.valid_item"]
    assert node["Contrasts"][-1]["ConditionList"] == ["valid_item.valid_item", "invalid_item.invalid_item"]
    assert "valid_item.valid_item:rt_mod^1" in [c["ConditionList"][0] for c in node["Contrasts"]]


def test_clashing_spm_condition_names_are_rejected():
    # a merge target equal to the renamed split regressor's SPM name would give two columns the same condition
    with pytest.raises(WizardError, match="same name"):
        build_model(choices(recipes=[valid_only(keep_original=True), merge(["a", "b"], "valid_item")]), SCAN)


def test_auto_false_without_pairs_is_rejected():
    with pytest.raises(WizardError, match="no contrasts"):
        build_model(choices(contrasts={"auto": False, "pairs": []}), SCAN)


@pytest.mark.parametrize("pair", [
    {"name": "x", "positive": [["trial_type.a"]], "negative": ["trial_type.b"]},
    {"name": "x", "positive": [{"a": 1}], "negative": ["trial_type.b"]},
    {"name": "x", "positive": ["trial_type.a"], "negative": [5]},
])
def test_pair_items_must_be_strings(pair):
    with pytest.raises(WizardError):
        build_model(choices(contrasts={"auto": False, "pairs": [pair]}), SCAN)


@pytest.mark.parametrize("bad", [{"id": 5}, {"id": ["valid_only"]}, {"id": {}}])
def test_recipe_id_must_be_a_string(bad):
    with pytest.raises(WizardError):
        build_model(choices(recipes=[bad]), SCAN)


def test_pair_item_error_does_not_say_recipe():
    pair = {"name": "x", "positive": [5], "negative": ["trial_type.b"]}
    with pytest.raises(WizardError) as e:
        build_model(choices(contrasts={"auto": False, "pairs": [pair]}), SCAN)
    assert "contrast positive" in str(e.value) and "recipe" not in str(e.value)
    with pytest.raises(WizardError, match="recipe values"):
        build_model(choices(recipes=[{"id": "split_by_column", "condition": "item", "column": "response_validity", "values": [5]}]), SCAN)
