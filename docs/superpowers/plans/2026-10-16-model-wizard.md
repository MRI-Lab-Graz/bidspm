# Model Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A guided wizard (Python engine + stepper page) that builds a valid BIDS-StatsModel from the scanned events/confounds: task, conditions, transformer recipes, nuisance regressors, contrasts, preview + preflight, save.

**Architecture:** `lib/model_wizard.py` is a pure-Python, data-driven recipe engine: `build_model(choices, scan) -> {"model", "preview"}`. `webapp/web_wizard_api.py` is a thin wrapper (scan = existing `_discover_*` helpers; build = engine + preflight on the proposed model + optional save). `/model-wizard/<project_id>` is a stepper page that only renders and collects choices; "New model" on the analysis page opens it.

**Tech Stack:** Python 3.12 (uv), Flask, pytest, vanilla JS + Bootstrap (existing), Playwright for the browser test. No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-10-16-model-wizard-design.md` (amended in Task 1). Reference model: `studies/141_fix_pmod.json`.
- TDD always: failing test first, see it fail, then the code (CLAUDE.md). Pipeline logic belongs in `lib/`, not `webapp/` or JS.
- The wizard never writes a model bidspm would silently ignore: unsupported inputs raise `WizardError` (a `ValueError`) with a plain-language message; the route turns it into `400 {"error": ...}`.
- Formats (verified against bidspm 4.0.0 and the repo's studies): Filter `{"Name":"Filter","Input":"trial_type","Query":"trial_type==item","Output":"trial_item"}` (Input/Output are strings, Query values unquoted); Replace `{"Name":"Replace","Input":"trial_type","Output":"trial_type","Replace":[{"key":"^a$","value":"b"}]}`; regressor names are `<column>.<value>` (e.g. `valid_item.item`); parametric modulation is `Model.Software.SPM.ParametricModulations: [{"Name","Conditions":[ref],"Values":[column],"PolynomialExpansion"(only if >1)}]`; pmod contrast ConditionList entry `<ref>:<Name>^<k>`; intercept is the integer `1` in `X`; Run node name `run_level`; `Software.SPM.SerialCorrelation` is `"FAST"`.
- Per-trial splitting (`LabelIdenticalRows`/`Concatenate`) is OUT of v1: its regressor names depend on trial counts, so X cannot be enumerated (amended into the spec in Task 1).
- Tests: `.bidspm/bin/python -m pytest -q tests`; browser tests must really run (check `-rs`). Known flake: `tests/test_new_features.py::test_analysis_page_renders_second_level_add_node_menu` (rerun alone). Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Before merging to main: `/ponytail:ponytail-review` on the branch diff (Task 7). Do not bump the version.

## File Structure

- Create `lib/model_wizard.py` — `WizardError`, `NUISANCE_PRESETS`, `RECIPES`, `RECIPE_CATALOG`, `second_level_nodes`, `build_model`.
- Create `webapp/web_wizard_api.py` — `register_wizard_routes(app, resolve_fs_path)`.
- Create `templates/model_wizard.html`, `static/js/model_wizard.js`.
- Create `tests/test_model_wizard.py` (engine), `tests/test_wizard_route.py`, `tests/test_wizard_browser.py`.
- Modify `webapp/web_discovery_model_api.py` (use `second_level_nodes`), `webapp/web_pages.py` (page route), `bidspm_gui.py` (register), `static/js/analysis_api_actions.js` (`createNewModel` opens the wizard), `README.md`, the spec.

---

### Task 1: Engine core (base model, nuisance, contrasts) + spec amendment

**Files:**
- Create: `lib/model_wizard.py`, `tests/test_model_wizard.py`
- Modify: `webapp/web_discovery_model_api.py` (`_build_default_model` tail), `docs/superpowers/specs/2026-10-16-model-wizard-design.md`

**Interfaces:**
- Produces: `WizardError(ValueError)`; `NUISANCE_PRESETS: dict[str, list[str]]` (`none`, `motion6`, `motion24`, `motion6_fd`); `second_level_nodes(names: list[str]) -> list[dict]`; `build_model(choices: dict, scan: dict) -> {"model": dict, "preview": {"regressors": list[str], "nuisance": list[str], "contrasts": list[str], "transformations": list[dict], "warnings": list[str]}}`.
- `scan` shape: `{"tasks": [str], "columns": {column: [values]}, "numeric": [column], "confound_columns": [str]}`.
- `choices` shape: `{"task", "name", "recipes": [{"id", ...params}], "nuisance": "none"|preset|list[str], "exclude": [trial_type values], "contrasts": {"auto": bool, "pairs": [{"name", "positive": [ref], "negative": [ref]}]}}`.
- Engine internals later tasks extend: `state = {"regressors": [ref], "instructions": [], "pmods": [], "warnings": [], "columns": dict, "numeric": set}`; recipes are `fn(state, params)` registered in `RECIPES`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run, verify fail** — `.bidspm/bin/python -m pytest -q tests/test_model_wizard.py` → FAIL (`ModuleNotFoundError: lib.model_wizard`).

- [ ] **Step 3: Implement `lib/model_wizard.py`**

```python
"""Model wizard: build a BIDS-StatsModel from the scanned events/confounds plus the user's choices.

Pure functions, no Flask. Recipes (Task 2+) are small functions registered in RECIPES that rewrite the working state:
state = {"regressors": ["column.value", ...], "instructions": [...], "pmods": [...], "warnings": [...],
         "columns": {column: [values]}, "numeric": {columns}}.
"""
import re

NAME_RE = re.compile(r"[A-Za-z0-9_]+")
MOTION6 = ["trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z"]
NUISANCE_PRESETS = {
    "none": [],
    "motion6": MOTION6,
    "motion24": MOTION6 + [f"{n}_{s}" for s in ("derivative1", "power2", "derivative1_power2") for n in MOTION6],
    "motion6_fd": MOTION6 + ["framewise_displacement"],
}
RECIPES = {}


class WizardError(ValueError):
    """The choices cannot be turned into a model bidspm would run correctly."""


def _t_contrast(name, conditions, weights):
    return {"Name": name, "ConditionList": conditions, "Weights": weights, "Test": "t"}


def _contrast_name(ref):
    return ref.removeprefix("trial_type.").replace(".", "_")


def second_level_nodes(names):
    """Default Subject and Dataset nodes: one pass-through contrast per run-level contrast name."""
    def contrasts():
        return [_t_contrast(n, [n], [1]) for n in names]
    return [
        {"Level": "Subject", "Name": "subject_level", "GroupBy": ["subject", "contrast"],
         "Model": {"Type": "glm", "X": list(names) or ["contrast"]}, "Contrasts": contrasts()},
        {"Level": "Dataset", "Name": "dataset_level", "GroupBy": ["contrast"],
         "Model": {"Type": "glm", "X": [1]}, "Contrasts": contrasts()},
    ]


def _nuisance(value):
    if isinstance(value, str):
        if value not in NUISANCE_PRESETS:
            raise WizardError(f"unknown nuisance preset {value!r}; choose one of {', '.join(NUISANCE_PRESETS)} or a list of columns")
        return list(NUISANCE_PRESETS[value])
    if isinstance(value, list) and all(isinstance(v, str) and v for v in value):
        return list(value)
    raise WizardError("nuisance must be a preset name or a list of confound column names")


def _run_contrasts(regressors, pmods, spec):
    out = []
    if spec.get("auto", True):
        out += [_t_contrast(_contrast_name(r), [r], [1]) for r in regressors]
        for pm in pmods:
            ref = pm["Conditions"][0]
            for k in range(1, pm.get("PolynomialExpansion", 1) + 1):
                out.append(_t_contrast(f"{_contrast_name(ref)}_{pm['Name']}_{k}", [f"{ref}:{pm['Name']}^{k}"], [1]))
    for pair in spec.get("pairs") or []:
        name, pos, neg = pair.get("name") or "", list(pair.get("positive") or []), list(pair.get("negative") or [])
        if not NAME_RE.fullmatch(name):
            raise WizardError(f"contrast name {name!r}: use letters, digits and underscores only")
        unknown = [r for r in pos + neg if r not in regressors]
        if not pos or not neg or unknown:
            raise WizardError(f"contrast {name!r} needs regressors on both sides" + (f"; unknown: {', '.join(unknown)}" if unknown else ""))
        out.append(_t_contrast(name, pos + neg, [1 / len(pos)] * len(pos) + [-1 / len(neg)] * len(neg)))
    names = [c["Name"] for c in out]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise WizardError(f"duplicate contrast names: {', '.join(dupes)}")
    return out


def build_model(choices, scan):
    task = choices.get("task")
    if task not in scan.get("tasks", []):
        raise WizardError(f"task {task!r} was not found in the dataset (found: {', '.join(scan.get('tasks', [])) or 'none'})")
    conditions = scan.get("columns", {}).get("trial_type", [])
    if not conditions:
        raise WizardError(f"the events of task-{task} have no trial_type values; the wizard needs a trial_type column")
    exclude = set(choices.get("exclude") or [])
    state = {"regressors": [f"trial_type.{c}" for c in conditions if c not in exclude], "instructions": [],
             "pmods": [], "warnings": [], "columns": scan["columns"], "numeric": set(scan.get("numeric", []))}
    for recipe in choices.get("recipes") or []:
        fn = RECIPES.get(recipe.get("id"))
        if fn is None:
            raise WizardError(f"unknown recipe {recipe.get('id')!r}")
        fn(state, recipe)
    regressors = state["regressors"]
    if not regressors:
        raise WizardError("the model has no regressors left")
    nuisance = _nuisance(choices.get("nuisance", "none"))
    contrasts = _run_contrasts(regressors, state["pmods"], choices.get("contrasts") or {})
    spm = {"SerialCorrelation": "FAST"}  # lab default (as in studies/141*.json); bidspm's own default is AR(1)
    if state["pmods"]:
        spm["ParametricModulations"] = state["pmods"]
    run = {"Level": "Run", "Name": "run_level", "GroupBy": ["run", "subject"],
           "Model": {"Type": "glm", "X": regressors + [1] + nuisance,
                     "HRF": {"Variables": list(regressors), "Model": "spm"},
                     "Options": {"HighPassFilterCutoffHz": 0.0078, "Mask": {"desc": ["brain"], "suffix": ["mask"]}},
                     "Software": {"SPM": spm}},
           "Contrasts": contrasts}
    if state["instructions"]:
        run["Transformations"] = {"Transformer": "bidspm", "Instructions": state["instructions"]}
    names = [c["Name"] for c in contrasts]
    model = {"Name": choices.get("name") or "wizard-model", "BIDSModelVersion": "1.0.0",
             "Description": "Generated by the model wizard.", "Input": {"task": [task]},
             "Nodes": [run, *second_level_nodes(names)]}
    return {"model": model, "preview": {"regressors": list(regressors), "nuisance": nuisance, "contrasts": names,
                                        "transformations": state["instructions"], "warnings": state["warnings"]}}
```
Then in `webapp/web_discovery_model_api.py` `_build_default_model`: replace the hand-built Subject and Dataset node construction (from `subject_contrasts = ...` through the dataset node append) with `nodes.extend(second_level_nodes(all_contrast_names))` (import `from lib.model_wizard import second_level_nodes`). Existing tests for `/api/model/create` must pass unchanged (the node dicts are identical).

Spec amendment (edit `docs/superpowers/specs/2026-10-16-model-wizard-design.md`): remove the "per-trial via `LabelIdenticalRows`…" alternative from the split recipe and add it to Out of scope with the reason (regressor names depend on trial counts); say parametric modulators are not mean-centred by the wizard (SPM centres them); say the default Run node name is `run_level` and the intercept is the integer 1.

- [ ] **Step 4: Run** — `.bidspm/bin/python -m pytest -q tests/test_model_wizard.py tests/test_web_discovery_model_hints_extra.py tests/test_web_routes.py` → PASS.
- [ ] **Step 5: Commit** — `feat(wizard): recipe engine core (base model, nuisance presets, contrasts); share second_level_nodes`.

---

### Task 2: Recipes `valid_only` and `split_by_column`

**Files:** Modify `lib/model_wizard.py`, `tests/test_model_wizard.py`.

**Interfaces:**
- Consumes: Task 1 engine.
- Produces: `recipe(id, title, description, params)` decorator filling `RECIPES` and `RECIPE_CATALOG` (list of `{"id","title","description","params":[{"name","kind","label","required"}]}`; kinds: `condition`, `conditions`, `column`, `value`, `values`, `regressor`, `numeric_column`, `int`, `text`, `bool`); helpers `_safe`, `_need_condition`, `_first_filter`, `_second_filter`, `_split`.

- [ ] **Step 1: Failing tests** (append)

```python
from lib.model_wizard import RECIPE_CATALOG


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
```
The last case must fail because `trial_type.item` was consumed (removed) by the first recipe; applying a second filter on the same condition is done by `split_by_column` (or `keep_original`).

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** (append to `lib/model_wizard.py`, before `build_model` or after — keep `RECIPES` populated before use)

```python
RECIPE_CATALOG = []
NA = {"n/a", "N/A", "nan", "NaN", ""}
UNSAFE = re.compile(r"[\s'\"=]")


def recipe(id, title, description, params):
    def register(fn):
        RECIPES[id] = fn
        RECIPE_CATALOG.append({"id": id, "title": title, "description": description, "params": params})
        return fn
    return register


def _safe(label, value):
    if not value or UNSAFE.search(str(value)):
        raise WizardError(f"{label} {value!r} cannot be used in a transformer query (spaces, quotes and '=' are not supported); rename it in the events first")


def _need_condition(state, condition):
    if f"trial_type.{condition}" not in state["regressors"]:
        raise WizardError(f"condition {condition!r} is not available (unknown, excluded, or already used by an earlier recipe)")


def _first_filter(state, condition):
    out = f"trial_{condition}"
    if not any(i.get("Output") == out for i in state["instructions"]):
        state["instructions"].append({"Name": "Filter", "Input": "trial_type", "Query": f"trial_type=={condition}", "Output": out})
    return out


def _second_filter(state, source, column, value, condition):
    out = f"{value}_{condition}"
    if any(i.get("Output") == out for i in state["instructions"]):
        raise WizardError(f"the output name {out!r} is already used by another recipe")
    state["instructions"].append({"Name": "Filter", "Input": source, "Query": f"{column}=={value}", "Output": out})
    return f"{out}.{condition}"


def _split(state, condition, column, values, keep_original):
    _need_condition(state, condition)
    if column == "trial_type" or column not in state["columns"]:
        raise WizardError(f"column {column!r} is not an events column that can split a condition")
    if not values:
        raise WizardError(f"column {column!r} has no values to split by")
    unknown = [v for v in values if v not in state["columns"][column]]
    if unknown:
        raise WizardError(f"column {column!r} has no value {', '.join(map(repr, unknown))}")
    for label, v in [("condition", condition), ("column", column)] + [("value", v) for v in values]:
        _safe(label, v)
    source = _first_filter(state, condition)
    state["regressors"] += [_second_filter(state, source, column, v, condition) for v in values]
    if not keep_original:
        state["regressors"].remove(f"trial_type.{condition}")


@recipe("valid_only", "Only valid/correct trials",
        "Model only the trials of one condition where a column has a given value (e.g. response_validity == valid).",
        [{"name": "condition", "kind": "condition", "label": "Condition", "required": True},
         {"name": "column", "kind": "column", "label": "Column", "required": True},
         {"name": "value", "kind": "value", "label": "Keep rows where it equals", "required": True},
         {"name": "keep_original", "kind": "bool", "label": "Keep the original condition too", "required": False}])
def valid_only(state, p):
    _split(state, p.get("condition"), p.get("column"), [p.get("value")], bool(p.get("keep_original")))
    others = [v for v in state["columns"][p["column"]] if v != p["value"] and v not in NA]
    if others:
        state["warnings"].append(f"{p['condition']}: trials with {p['column']} = {', '.join(others)} are not modelled")


@recipe("split_by_column", "Split a condition by a column",
        "One regressor per value of a column (e.g. item -> valid_item / invalid_item).",
        [{"name": "condition", "kind": "condition", "label": "Condition", "required": True},
         {"name": "column", "kind": "column", "label": "Column", "required": True},
         {"name": "values", "kind": "values", "label": "Values (default: all)", "required": False},
         {"name": "keep_original", "kind": "bool", "label": "Keep the original condition too", "required": False}])
def split_by_column(state, p):
    column = p.get("column")
    values = p.get("values") or [v for v in state["columns"].get(column, []) if v not in NA]
    _split(state, p.get("condition"), column, list(values), bool(p.get("keep_original")))
```
Because `build_model` looks up `RECIPES` at call time, no reordering is needed; keep the `recipe` decorator definitions above `build_model` for readability.

- [ ] **Step 4: Run** — `.bidspm/bin/python -m pytest -q tests/test_model_wizard.py` → PASS.
- [ ] **Step 5: Commit** — `feat(wizard): valid_only and split_by_column recipes`.

---

### Task 3: Recipes `merge_rename` and `parametric_modulator`

**Files:** Modify `lib/model_wizard.py`, `tests/test_model_wizard.py`.

**Interfaces:** Consumes Task 2 helpers. Produces recipe ids `merge_rename` (params `sources` conditions, `target` text) and `parametric_modulator` (params `regressor`, `column` numeric_column, `polynomial` int default 1).

- [ ] **Step 1: Failing tests** (append)

```python
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


@pytest.mark.parametrize("bad", [
    {"id": "merge_rename", "sources": [], "target": "x"},
    {"id": "merge_rename", "sources": ["nope"], "target": "x"},
    {"id": "merge_rename", "sources": ["a"], "target": "bad name"},
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
    assert by_name["valid_item_item_ai_rating_mod_1"]["ConditionList"] == ["valid_item.item:ai_rating_mod^1"]
    assert by_name["valid_item_item_ai_rating_mod_2"]["ConditionList"] == ["valid_item.item:ai_rating_mod^2"]


def test_polynomial_one_omits_the_expansion_key():
    node = run_node(build_model(choices(recipes=[pmod()]), SCAN))
    assert "PolynomialExpansion" not in node["Model"]["Software"]["SPM"]["ParametricModulations"][0]


@pytest.mark.parametrize("bad", [
    pmod(regressor="trial_type.nope"),          # not a current regressor
    pmod(column="response_validity"),           # not numeric
    pmod(polynomial=0), pmod(polynomial=4),     # out of range 1..3
])
def test_invalid_pmod_raises(bad):
    with pytest.raises(WizardError):
        build_model(choices(recipes=[bad]), SCAN)


def test_two_pmods_on_the_same_column_get_unique_names():
    recipes = [pmod(), pmod(regressor="trial_type.a")]
    names = [m["Name"] for m in run_node(build_model(choices(recipes=recipes), SCAN))["Model"]["Software"]["SPM"]["ParametricModulations"]]
    assert len(set(names)) == 2
```

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** (append)

```python
@recipe("merge_rename", "Merge or rename conditions",
        "Combine several trial_type values into one regressor, or rename a single one.",
        [{"name": "sources", "kind": "conditions", "label": "Conditions", "required": True},
         {"name": "target", "kind": "text", "label": "New name", "required": True}])
def merge_rename(state, p):
    sources, target = list(p.get("sources") or []), p.get("target")
    if not sources:
        raise WizardError("pick at least one condition to merge or rename")
    for s in sources:
        _need_condition(state, s)
    _safe("new name", target)
    state["instructions"].append({"Name": "Replace", "Input": "trial_type", "Output": "trial_type",
                                  "Replace": [{"key": f"^{re.escape(s)}$", "value": target} for s in sources]})
    for s in sources:
        state["regressors"].remove(f"trial_type.{s}")
    if f"trial_type.{target}" not in state["regressors"]:
        state["regressors"].append(f"trial_type.{target}")


@recipe("parametric_modulator", "Parametric modulator",
        "Modulate a regressor by a numeric events column (e.g. RT or a rating); SPM mean-centres it.",
        [{"name": "regressor", "kind": "regressor", "label": "Regressor", "required": True},
         {"name": "column", "kind": "numeric_column", "label": "Numeric column", "required": True},
         {"name": "polynomial", "kind": "int", "label": "Polynomial order (1-3)", "required": False}])
def parametric_modulator(state, p):
    ref, column = p.get("regressor"), p.get("column")
    poly = 1 if p.get("polynomial") is None else p["polynomial"]  # 0 must be rejected, not defaulted
    if ref not in state["regressors"]:
        raise WizardError(f"regressor {ref!r} is not available (unknown, or removed by an earlier recipe)")
    if column not in state["numeric"]:
        raise WizardError(f"column {column!r} is not a numeric events column")
    if not isinstance(poly, int) or not 1 <= poly <= 3:
        raise WizardError("polynomial order must be 1, 2 or 3")
    name, n = f"{column}_mod", 1
    while any(m["Name"] == name for m in state["pmods"]):
        n += 1
        name = f"{column}_mod{n}"
    pm = {"Name": name, "Conditions": [ref], "Values": [column]}
    if poly > 1:
        pm["PolynomialExpansion"] = poly
    state["pmods"].append(pm)
```
Note `_run_contrasts` (Task 1) already builds the `ref:Name^k` contrasts from `state["pmods"]`.

- [ ] **Step 4: Run** — PASS. **Step 5: Commit** — `feat(wizard): merge_rename and parametric_modulator recipes`.

---

### Task 4: Golden test against study 141

**Files:** Modify `tests/test_model_wizard.py` only (plus fixes in `lib/model_wizard.py` if the golden test reveals a format difference — report them).

- [ ] **Step 1: Write the golden test** (skips if the study file is absent)

```python
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
```
- [ ] **Step 2: Run** — it should PASS if Tasks 1-3 are right. If it fails, the failure shows a real format mismatch: fix `lib/model_wizard.py` (not the test), keeping Tasks 1-3 tests green, and describe the fix in the report.
- [ ] **Step 3: Commit** — `test(wizard): golden test reproducing the study 141 Run node`.

---

### Task 5: Routes — scan, build (+ preflight on the proposed model), save

**Files:**
- Create: `webapp/web_wizard_api.py`, `tests/test_wizard_route.py`
- Modify: `bidspm_gui.py` (import + `register_wizard_routes(app, resolve_fs_path)`; check how `register_discovery_model_routes` receives `resolve_fs_path` and pass the same)

**Interfaces:**
- Consumes: `lib.model_wizard` (`build_model`, `WizardError`, `NUISANCE_PRESETS`, `RECIPE_CATALOG`), `webapp.web_discovery_model_api._discover_event_info/_discover_confound_info`, `lib.core.discover_tasks`, `lib.preflight.run_preflight_from_config` and `_verdict`.
- Produces: `POST /api/wizard/scan` body `{bids_dir, fmriprep_dir, task?}` -> `{"tasks","task","columns","numeric","confound_columns","catalog","nuisance_presets"}`; `POST /api/wizard/build` body `{choices, bids_dir, fmriprep_dir, space?, save_path?, overwrite?}` -> `{"model","preview","preflight","saved"?}` or `400/409 {"error"}`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_wizard_route.py
import json

from bidspm_gui import app
from tests.preflight_support import make_trees


def post(path, body):
    return app.test_client().post(path, json=body)


def paths(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    return {"bids_dir": str(bids), "fmriprep_dir": str(fmriprep)}


def test_scan_returns_tasks_columns_catalog_and_presets(tmp_path):
    res = post("/api/wizard/scan", paths(tmp_path))
    data = res.get_json()
    assert res.status_code == 200 and data["tasks"] == ["x"] and data["task"] == "x"
    assert set(data["columns"]["trial_type"]) == {"a", "b"}
    assert "trans_x" in data["confound_columns"]
    assert {r["id"] for r in data["catalog"]} >= {"valid_only", "split_by_column", "merge_rename", "parametric_modulator"}
    assert "motion6" in data["nuisance_presets"]


def choices(**over):
    return {"task": "x", "name": "m", "recipes": [], "nuisance": "motion6", "exclude": [],
            "contrasts": {"auto": True, "pairs": []}, **over}


def test_build_returns_model_preview_and_preflight_without_validator_noise(tmp_path):
    res = post("/api/wizard/build", {**paths(tmp_path), "space": "MNI", "choices": choices()})
    data = res.get_json()
    assert res.status_code == 200 and data["preview"]["regressors"] == ["trial_type.a", "trial_type.b"]
    assert data["preflight"]["verdict"] in ("ready", "warnings")
    assert all(c["id"] != "validator" for c in data["preflight"]["checks"])


def test_build_preflight_flags_a_missing_confound_column(tmp_path):
    res = post("/api/wizard/build", {**paths(tmp_path), "space": "MNI", "choices": choices(nuisance=["csf"])})
    assert "confound_columns" in {c["id"] for c in res.get_json()["preflight"]["checks"] if c["severity"] == "error"}


def test_build_wizard_error_is_a_400(tmp_path):
    res = post("/api/wizard/build", {**paths(tmp_path), "choices": choices(recipes=[{"id": "nope"}])})
    assert res.status_code == 400 and "unknown recipe" in res.get_json()["error"]


def test_save_writes_the_model_and_refuses_to_overwrite(tmp_path):
    target = tmp_path / "models" / "m.json"
    body = {**paths(tmp_path), "space": "MNI", "choices": choices(), "save_path": str(target)}
    first = post("/api/wizard/build", body)
    assert first.status_code == 200 and json.loads(target.read_text())["Name"] == "m"
    assert post("/api/wizard/build", body).status_code == 409
    assert post("/api/wizard/build", {**body, "overwrite": True}).status_code == 200


def test_non_dict_body_is_a_400_not_a_500():
    res = app.test_client().post("/api/wizard/build", data="[]", content_type="application/json")
    assert res.status_code == 400
```

- [ ] **Step 2: Run, verify fail** (404s).
- [ ] **Step 3: Implement**

```python
# webapp/web_wizard_api.py
"""Thin routes for the model wizard; the recipe engine lives in lib/model_wizard.py."""
import json
import os
import tempfile
from pathlib import Path

from flask import Flask, jsonify, request

from lib.core import discover_tasks
from lib.model_wizard import NUISANCE_PRESETS, RECIPE_CATALOG, WizardError, build_model
from lib.preflight import _verdict, run_preflight_from_config
from webapp.web_discovery_model_api import _discover_confound_info, _discover_event_info


def _scan(bids_dir, fmriprep_dir, task):
    tasks = discover_tasks(Path(bids_dir))
    task = task if task in tasks else (tasks[0] if tasks else "")
    events = _discover_event_info(Path(bids_dir), [task] if task else None)
    confounds = _discover_confound_info(Path(fmriprep_dir), [task] if task else None) if fmriprep_dir else {"columns": []}
    return {"tasks": tasks, "task": task, "columns": events["sample_values"],
            "numeric": events["numeric_columns"], "confound_columns": confounds["columns"]}


def _preflight(model, bids_dir, fmriprep_dir, space, task):
    """Preflight of the proposed model against the real data (the dataset validator is not model-related: dropped)."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(model, fh)
    try:
        report = run_preflight_from_config(
            {"BIDS_DIR": bids_dir, "FMRIPREP_DIR": fmriprep_dir, "SPACE": space or "", "TASKS": [task]},
            model=fh.name, validator="skip", actions=["stats"])
    finally:
        os.unlink(fh.name)
    checks = [c for c in report["checks"] if c["id"] != "validator"]
    return {"verdict": _verdict(checks), "checks": checks}


def register_wizard_routes(app: Flask, resolve_fs_path) -> None:
    def _body():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else None

    def _dirs(data):
        return (resolve_fs_path(str(data.get("bids_dir") or "")), resolve_fs_path(str(data.get("fmriprep_dir") or "")))

    @app.route("/api/wizard/scan", methods=["POST"])
    def wizard_scan():
        data = _body()
        if data is None:
            return jsonify({"error": "expected a JSON object"}), 400
        bids_dir, fmriprep_dir = _dirs(data)
        if not os.path.isdir(bids_dir):
            return jsonify({"error": f"BIDS folder not found: {bids_dir}"}), 404
        return jsonify({**_scan(bids_dir, fmriprep_dir, data.get("task")), "catalog": RECIPE_CATALOG,
                        "nuisance_presets": NUISANCE_PRESETS})

    @app.route("/api/wizard/build", methods=["POST"])
    def wizard_build():
        data = _body()
        if data is None or not isinstance(data.get("choices"), dict):
            return jsonify({"error": "expected a JSON object with 'choices'"}), 400
        choices = data["choices"]
        bids_dir, fmriprep_dir = _dirs(data)
        if not os.path.isdir(bids_dir):
            return jsonify({"error": f"BIDS folder not found: {bids_dir}"}), 404
        try:
            result = build_model(choices, _scan(bids_dir, fmriprep_dir, choices.get("task")))
        except WizardError as exc:
            return jsonify({"error": str(exc)}), 400
        result["preflight"] = _preflight(result["model"], bids_dir, fmriprep_dir, data.get("space"), choices["task"])
        save_path = str(data.get("save_path") or "").strip()
        if save_path:
            save_path = os.path.abspath(resolve_fs_path(save_path))
            if os.path.exists(save_path) and not data.get("overwrite"):
                return jsonify({"error": "File already exists. Set overwrite=true to replace it."}), 409
            os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
            with open(save_path, "w", encoding="utf-8") as fh:
                json.dump(result["model"], fh, indent=2)
                fh.write("\n")
            result["saved"] = save_path
        return jsonify(result)
```
Register in `bidspm_gui.py` after the discovery routes, with the same `resolve_fs_path` they use. Guard: `resolve_fs_path("")` must not raise (check its behaviour; if it does, skip resolving empty strings).

- [ ] **Step 4: Run** — `.bidspm/bin/python -m pytest -q tests/test_wizard_route.py tests/test_web_routes.py tests/test_gui_smoke.py` → PASS.
- [ ] **Step 5: Commit** — `feat(wizard): /api/wizard/scan and /api/wizard/build (+ preflight of the proposed model, save)`.

---

### Task 6: Wizard page and entry point

**Files:**
- Create: `templates/model_wizard.html`, `static/js/model_wizard.js`, `tests/test_wizard_browser.py`
- Modify: `webapp/web_pages.py` (route `/model-wizard` and `/model-wizard/<project_id>`, same context loader as the transformer builder page), `static/js/analysis_api_actions.js` (`createNewModel()` opens the wizard instead of `prompt()`), `tests/test_analysis_page_browser.py` (only if a global name changes).

**Interfaces:**
- Page context: `window.BIDSPM_WIZARD_CONTEXT = {projectId, bidsDir, fmriprepDir, space, modelsDir}` (taken from the project config like the transformer builder page does; study the existing page route and `window.BIDSPM_TRANSFORMER_CONTEXT` pattern first).
- Element ids (stable, tests use them): `#wiz-task` (select), `#wiz-conditions` (checkbox list; unchecked = excluded), `#wiz-recipe-add` (select of catalog recipes) + `#wiz-add-recipe` (button) + `#wiz-recipes` (list of added recipe cards with a remove button), `#wiz-nuisance` (select: presets + "custom"), `#wiz-nuisance-custom` (text, comma-separated), `#wiz-auto-contrasts` (checkbox), `#wiz-pair-table` (rows: name input, positive multi-select, negative multi-select) + `#wiz-add-pair`, `#wiz-name` (model name), `#wiz-save-path`, `#wiz-review` (preview: regressors, contrasts, warnings, preflight verdict + checks), `#wiz-save` (button), `#wiz-error` (message area).
- Behaviour: on load call `/api/wizard/scan`; every change (debounced 300 ms) posts `/api/wizard/build` without `save_path` and renders the preview; recipe parameter forms are generated from `catalog[].params` kinds (`condition`/`regressor` select from the current preview regressors or conditions, `column`/`numeric_column` select from the scan, `value`/`values` select from the chosen column's values, `bool` checkbox, `int` number, `text` input); `#wiz-save` posts with `save_path` (default `<modelsDir or studies/>/<name>.json`), on 409 asks to overwrite; after saving it sets the project's models file (use the existing project config save mechanism — inspect `static/js/analysis_project_form.js` / `webapp/web_projects_api.py` for the proper endpoint) and redirects to `/analysis/<projectId>`; on a 400 the engine's message is shown in `#wiz-error` and the previous preview stays. A collapsed "Advanced" note links to the analysis page's contrast builder ("Open the saved model in the editor for custom contrasts"). All server strings are inserted with `textContent`/DOM nodes, never `innerHTML` (messages contain user paths and event values).
- Entry: `createNewModel()` in `analysis_api_actions.js` navigates to `/model-wizard/<currentProjectId>` when a project is open (keep the old `prompt()` flow only when there is no project).

- [ ] **Step 1: Failing browser tests** (mirror `tests/test_preflight_browser.py` for the server/page setup; use `tests/browser_support.py`; skip without Chromium)

```python
# tests/test_wizard_browser.py  (sketch of required cases; implement fully with the fixtures used by the other browser tests)
# 1. test_page_loads_scans_and_previews: open /model-wizard/<id> on a dataset made by tests.preflight_support.make_trees
#    (use start_server with a project pointing at those folders; extend browser_support only if needed), wait for
#    #wiz-review to show "trial_type.a"; no page errors.
# 2. test_adding_a_valid_only_recipe_updates_the_preview: dataset events with a response_validity column; add recipe,
#    choose item/response_validity/valid; preview lists "valid_item.item" and a warning about the other trials.
# 3. test_unchecking_a_condition_excludes_it: preview no longer lists it.
# 4. test_engine_error_is_shown_not_thrown: mock /api/wizard/build with page.route to return 400 {"error": "x <b>y</b>"};
#    #wiz-error shows the text literally (no <b> element) and the page still works.
# 5. test_save_writes_the_model_and_returns_to_analysis: click #wiz-save with a tmp save path, assert the file exists and
#    the URL becomes /analysis/<id>.
# 6. test_new_model_button_opens_the_wizard: on /analysis/<id> call createNewModel() -> URL /model-wizard/<id>.
```
- [ ] **Step 2: Run, verify fail.** Real browser tests must run (check `-rs`).
- [ ] **Step 3: Implement** the page route, template (Bootstrap, stepper-like sections following `transformer_builder.html` styling and `base.html`), `model_wizard.js` (plain classic script, no new libs), and the `createNewModel` change. Keep each file focused; if `model_wizard.js` grows beyond ~400 lines, stop and report DONE_WITH_CONCERNS.
- [ ] **Step 4: Run** — `.bidspm/bin/python -m pytest -q tests/test_wizard_browser.py tests/test_analysis_page_browser.py tests/test_transformer_builder_browser.py tests/test_web_routes.py` → PASS (browser tests run, not skipped).
- [ ] **Step 5: Commit** — `feat(wizard): model wizard page and New-model entry point`.

---

### Task 7: Docs, real-data smoke, review, wrap-up

**Files:** Modify `README.md`.

- [ ] **Step 1:** README section "Model wizard": what it does, the five steps, the four recipes with one-line examples, that presets/pairs are the basics and the contrast builder is the advanced path, that the preflight verdict is shown before saving, and the out-of-scope list from the spec.
- [ ] **Step 2:** Full suite `.bidspm/bin/python -m pytest -q tests -rs`; browser tests must run; report honestly.
- [ ] **Step 3:** Real smoke, read-only, no containers: through the Flask test client (or a script in the scratchpad) call `/api/wizard/scan` and `/api/wizard/build` on study 141's real folders (settings via the project export as in the preflight smoke) with the 141 choices (valid_only + parametric_modulator, motion6); show the preview, the preflight verdict (expect no errors), and diff the generated Run node against `studies/141_fix_pmod.json`. Also do one build on study 132 (task ol) with `split_by_column` or `merge_rename` on its real trial_type values. Report actual outputs and any surprise (false positives, unsupported cases).
- [ ] **Step 4:** `/ponytail:ponytail-review` on `git diff main...HEAD`; resolve or consciously defer each finding.
- [ ] **Step 5:** superpowers:verification-before-completion, then superpowers:finishing-a-development-branch. Do not merge without the user's go-ahead.
