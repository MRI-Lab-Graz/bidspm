"""Model wizard: build a BIDS-StatsModel from the scanned events/confounds plus the user's choices.

Pure functions, no Flask. Recipes (Task 2+) are small functions registered in RECIPES that rewrite the working state:
state = {"regressors": ["column.value", ...], "instructions": [...], "pmods": [...], "warnings": [...],
         "columns": {column: [values]}, "numeric": {columns}}.
"""
import copy
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
    name = re.sub(r"[^A-Za-z0-9_]+", "_", ref.removeprefix("trial_type.")).strip("_")
    if not name:
        raise WizardError(f"cannot derive a contrast name from {ref!r}")
    return name


def _expect(value, kind, what):
    if not isinstance(value, kind):
        raise WizardError(f"{what} has the wrong type")
    return value


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
    _expect(spec, dict, "contrasts")
    if spec.get("auto", True):
        out += [_t_contrast(_contrast_name(r), [r], [1]) for r in regressors]
        for pm in pmods:
            ref = pm["Conditions"][0]
            for k in range(1, pm.get("PolynomialExpansion", 1) + 1):
                out.append(_t_contrast(f"{_contrast_name(ref)}_{pm['Name']}_{k}", [f"{ref}:{pm['Name']}^{k}"], [1]))
    for pair in _expect(spec.get("pairs", []), list, "contrasts.pairs"):
        _expect(pair, dict, "contrast pair")
        name = _expect(pair.get("name") or "", str, "contrast name")
        pos = _expect(pair.get("positive") or [], list, "contrast positive")
        neg = _expect(pair.get("negative") or [], list, "contrast negative")
        if not NAME_RE.fullmatch(name):
            raise WizardError(f"contrast name {name!r}: use letters, digits and underscores only")
        unknown = [r for r in pos + neg if r not in regressors]
        if not pos or not neg or unknown:
            raise WizardError(f"contrast {name!r} needs regressors on both sides" + (f"; unknown: {', '.join(unknown)}" if unknown else ""))
        if len(set(pos + neg)) != len(pos + neg):
            raise WizardError(f"contrast {name!r} uses a regressor twice")
        out.append(_t_contrast(name, pos + neg, [1 / len(pos)] * len(pos) + [-1 / len(neg)] * len(neg)))
    names = [c["Name"] for c in out]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise WizardError(f"duplicate contrast names: {', '.join(dupes)}")
    return out

RECIPE_CATALOG = []
NA = {"n/a", "N/A", "nan", "NaN", ""}
# Names end up in Filter queries (bids-matlab get_query splits on ==, ~=, <, >, >=, <=; the right side is an
# anchored regex) and in output field names (coerce_fieldname strips everything but [A-Za-z0-9_]); '.' would
# also corrupt the "<column>.<value>" regressor name. So only word characters are allowed.
UNSAFE = re.compile(r"[^A-Za-z0-9_]")


def catalog():
    return copy.deepcopy(RECIPE_CATALOG)


def recipe(id, title, description, params):
    def register(fn):
        RECIPES[id] = fn
        RECIPE_CATALOG.append({"id": id, "title": title, "description": description, "params": params})
        return fn
    return register


def _str_param(label, value):
    return _expect(value, str, f"recipe {label}")


def _str_list_param(label, value):
    _expect(value, list, f"recipe {label}")
    for v in value:
        _str_param(label, v)
    return value


def _bool_param(label, value):
    return _expect(False if value is None else value, bool, f"recipe {label}")


def _safe(label, value):
    if not value or UNSAFE.search(str(value)):
        raise WizardError(f"{label} {value!r} cannot be used in a transformer query (only letters, digits and underscores are supported); rename it in the events first")


def _need_condition(state, condition):
    if f"trial_type.{condition}" not in state["regressors"]:
        raise WizardError(f"condition {condition!r} is not available (unknown, excluded, or already used by an earlier recipe)")


def _first_filter(state, condition):
    out = f"trial_{condition}"
    instruction = {"Name": "Filter", "Input": "trial_type", "Query": f"trial_type=={condition}", "Output": out}
    if instruction in state["instructions"]:
        return out
    if out in state["columns"] or any(i.get("Output") == out for i in state["instructions"]):
        raise WizardError(f"the output name {out!r} clashes with an events column or another recipe")
    state["instructions"].append(instruction)
    return out


def _second_filter(state, source, column, value, condition):
    out = f"{value}_{condition}"
    if out in state["columns"] or any(i.get("Output") == out for i in state["instructions"]):
        raise WizardError(f"the output name {out!r} clashes with an events column or another recipe")
    state["instructions"].append({"Name": "Filter", "Input": source, "Query": f"{column}=={value}", "Output": out})
    return f"{out}.{condition}"


def _split(state, condition, column, values, keep_original):
    _str_param("condition", condition)
    _str_param("column", column)
    _str_list_param("values", values)
    keep_original = _bool_param("keep_original", keep_original)
    values = list(dict.fromkeys(values))
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
    _split(state, p.get("condition"), p.get("column"), [p.get("value")], p.get("keep_original"))
    others = [v for v in state["columns"][p["column"]] if v != p["value"] and v not in NA]
    if others and not p.get("keep_original"):
        state["warnings"].append(f"{p['condition']}: trials with {p['column']} = {', '.join(others)} are not modelled")


@recipe("split_by_column", "Split a condition by a column",
        "One regressor per value of a column (e.g. item -> valid_item / invalid_item).",
        [{"name": "condition", "kind": "condition", "label": "Condition", "required": True},
         {"name": "column", "kind": "column", "label": "Column", "required": True},
         {"name": "values", "kind": "values", "label": "Values (default: all)", "required": False},
         {"name": "keep_original", "kind": "bool", "label": "Keep the original condition too", "required": False}])
def split_by_column(state, p):
    column = _str_param("column", p.get("column"))
    values = p.get("values")
    if values is None:
        if column in state["numeric"]:
            raise WizardError(f"column {column!r} is numeric; choose the values to split by explicitly (or use the parametric modulator recipe)")
        values = [v for v in state["columns"].get(column, []) if v not in NA]
    _split(state, p.get("condition"), column, values, p.get("keep_original"))


def build_model(choices, scan):
    _expect(choices, dict, "choices")
    _expect(scan, dict, "scan")
    task = choices.get("task")
    if task not in scan.get("tasks", []):
        raise WizardError(f"task {task!r} was not found in the dataset (found: {', '.join(scan.get('tasks', [])) or 'none'})")
    conditions = scan.get("columns", {}).get("trial_type", [])
    if not conditions:
        raise WizardError(f"the events of task-{task} have no trial_type values; the wizard needs a trial_type column")
    exclude = _expect(choices.get("exclude", []), list, "exclude")
    if not all(isinstance(e, str) for e in exclude):
        raise WizardError("exclude must be a list of trial_type values")
    if set(exclude) - set(conditions):
        raise WizardError(f"cannot exclude unknown trial_type values: {', '.join(sorted(set(exclude) - set(conditions)))}")
    _expect(choices.get("name") or "", str, "name")
    recipes = _expect(choices.get("recipes", []), list, "recipes")
    state = {"regressors": [f"trial_type.{c}" for c in conditions if c not in exclude], "instructions": [],
             "pmods": [], "warnings": [], "columns": scan["columns"], "numeric": set(scan.get("numeric", []))}
    for recipe in recipes:
        fn = RECIPES.get(_expect(recipe, dict, "recipe").get("id"))
        if fn is None:
            raise WizardError(f"unknown recipe {recipe.get('id')!r}")
        fn(state, recipe)
    regressors = state["regressors"]
    if not regressors:
        raise WizardError("the model has no regressors left")
    nuisance = _nuisance(choices.get("nuisance", "none"))
    contrasts = _run_contrasts(regressors, state["pmods"], choices.get("contrasts", {}))
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
