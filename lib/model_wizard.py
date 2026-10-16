"""Model wizard: build a BIDS-StatsModel from the scanned events/confounds plus the user's choices.

Pure functions, no Flask: scan_events reads the events files, build_model turns the user's choices into a model. Recipes are
small functions registered in RECIPES that rewrite the working state:
state = {"regressors": ["column.value", ...], "instructions": [...], "pmods": [...], "warnings": [...],
         "columns": {column: [values]}, "numeric": {columns}}.
"""
import copy
import csv
import re
from pathlib import Path

NAME_RE = re.compile(r"[A-Za-z0-9_]+")
MOTION6 = ["trans_x", "trans_y", "trans_z", "rot_x", "rot_y", "rot_z"]
NUISANCE_PRESETS = {
    "none": [],
    "motion6": MOTION6,
    "motion24": MOTION6 + [f"{n}_{s}" for s in ("derivative1", "power2", "derivative1_power2") for n in MOTION6],
    "motion6_fd": MOTION6 + ["framewise_displacement"],
}
RECIPES = {}
RECIPE_CATALOG = []
NA = {"n/a", "N/A", "nan", "NaN", ""}
# Names end up in Filter queries (bids-matlab get_query splits on ==, ~=, <, >, >=, <=; the right side is an
# anchored regex) and in output field names (coerce_fieldname strips everything but [A-Za-z0-9_]); '.' would
# also corrupt the "<column>.<value>" regressor name. So only word characters are allowed, plus '-' in
# conditions and values (a literal in the regex; the query keeps it, output names are coerced like bids-matlab).
UNSAFE = re.compile(r"[^A-Za-z0-9_]")
UNSAFE_HYPHEN_OK = re.compile(r"[^A-Za-z0-9_-]")


class WizardError(ValueError):
    """The choices cannot be turned into a model bidspm would run correctly."""


def _t_contrast(name, conditions, weights):
    return {"Name": name, "ConditionList": conditions, "Weights": weights, "Test": "t"}


def _contrast_name(ref):
    head, _, tail = ref.partition(".")
    if head == tail:  # renamed split regressor "<out>.<out>"
        ref = head
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
        {"Level": "Dataset", "Name": "dataset", "GroupBy": ["contrast"],
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
        pos = _str_list_param("positive", pair.get("positive") or [], "contrast positive")
        neg = _str_list_param("negative", pair.get("negative") or [], "contrast negative")
        if not NAME_RE.fullmatch(name):
            raise WizardError(f"contrast name {name!r}: use letters, digits and underscores only")
        unknown = [r for r in pos + neg if r not in regressors]
        if not pos or not neg or unknown:
            raise WizardError(f"contrast {name!r} needs regressors on both sides" + (f"; unknown: {', '.join(unknown)}" if unknown else ""))
        if len(set(pos + neg)) != len(pos + neg):
            raise WizardError(f"contrast {name!r} uses a regressor twice")
        out.append(_t_contrast(name, pos + neg, [1 / len(pos)] * len(pos) + [-1 / len(neg)] * len(neg)))
    if not out:
        raise WizardError("the model has no contrasts; keep the automatic contrasts or add a pair")
    names = [c["Name"] for c in out]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise WizardError(f"duplicate contrast names: {', '.join(dupes)}")
    return out



def _coerce(name):
    return re.sub(r"[^A-Za-z0-9_]", "", name)


def catalog():
    return copy.deepcopy(RECIPE_CATALOG)


def recipe(id, title, description, params):
    def register(fn):
        RECIPES[id] = fn
        RECIPE_CATALOG.append({"id": id, "title": title, "description": description, "params": params})
        return fn
    return register


def _str_param(label, value, what=None):
    return _expect(value, str, what or f"recipe {label}")


def _str_list_param(label, value, what=None):
    _expect(value, list, what or f"recipe {label}")
    for v in value:
        _str_param(label, v, what)
    return value


def _bool_param(label, value):
    return _expect(False if value is None else value, bool, f"recipe {label}")


def _safe(label, value, hyphen=False):
    if not value or (UNSAFE_HYPHEN_OK if hyphen else UNSAFE).search(value) or not _coerce(value):
        allowed = "letters, digits, underscores and hyphens" if hyphen else "letters, digits and underscores"
        raise WizardError(f"{label} {value!r} cannot be used in a transformer query (only {allowed} are supported); rename it in the events first")


def _need_condition(state, condition):
    if f"trial_type.{condition}" not in state["regressors"]:
        raise WizardError(f"condition {condition!r} is not available (unknown, excluded, or already used by an earlier recipe)")


def _release(state, ref):
    """Drop a regressor consumed by a recipe; a parametric modulator on it would be left dangling."""
    if any(ref in pm["Conditions"] for pm in state["pmods"]):
        raise WizardError(f"{ref!r} has a parametric modulator, so it cannot be merged, renamed or split away afterwards; add the modulator last")
    state["regressors"].remove(ref)


def _first_filter(state, condition):
    out = f"trial_{_coerce(condition)}"
    instruction = {"Name": "Filter", "Input": "trial_type", "Query": f"trial_type=={condition}", "Output": out}
    if instruction in state["instructions"]:
        if any(i["Name"] == "Replace" and i["Input"] == "trial_type" for i in state["instructions"][state["instructions"].index(instruction):]):
            raise WizardError(f"the filter for {condition!r} predates a merge/rename and would miss the merged rows; put that recipe before the earlier one")
        return out
    if out in state["columns"] or any(i.get("Output") == out for i in state["instructions"]):
        raise WizardError(f"the output name {out!r} clashes with an events column or another recipe")
    state["instructions"].append(instruction)
    return out


def _second_filter(state, source, column, value, condition, rename):
    out = f"{_coerce(value)}_{_coerce(condition)}"
    if out[0].isdigit():  # field names must not start with a digit; checked in Octave (see task-3 report)
        out = "v" + out
    if out in state["columns"] or any(i.get("Output") == out for i in state["instructions"]):
        raise WizardError(f"the output name {out!r} clashes with an events column or another recipe")
    state["instructions"].append({"Name": "Filter", "Input": source, "Query": f"{column}=={value}", "Output": out})
    if not rename:
        return f"{out}.{condition}"
    # bidspm names the SPM condition after the part behind the first '.', so give every split regressor its own cell value
    state["instructions"].append({"Name": "Replace", "Input": out, "Output": out,
                                  "Replace": [{"key": f"^{re.escape(condition)}$", "value": out}]})
    return f"{out}.{out}"


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
    _safe("column", column)
    for label, v in [("condition", condition)] + [("value", v) for v in values]:
        _safe(label, v, hyphen=True)
    source = _first_filter(state, condition)
    rename = keep_original or len(values) > 1
    state["regressors"] += [_second_filter(state, source, column, v, condition, rename) for v in values]
    if not keep_original:
        _release(state, f"trial_type.{condition}")


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


@recipe("merge_rename", "Merge or rename conditions",
        "Combine several trial_type values into one regressor, or rename a single one.",
        [{"name": "sources", "kind": "conditions", "label": "Conditions", "required": True},
         {"name": "target", "kind": "text", "label": "New name", "required": True}])
def merge_rename(state, p):
    sources = list(dict.fromkeys(_str_list_param("sources", p.get("sources"))))
    target = _str_param("target", p.get("target"))
    if not sources:
        raise WizardError("pick at least one condition to merge or rename")
    for s in sources:
        _need_condition(state, s)
        _safe("condition", s, hyphen=True)
    _safe("new name", target, hyphen=True)
    ref = f"trial_type.{target}"
    if ref not in state["regressors"]:
        if target in state["columns"]["trial_type"]:
            raise WizardError(f"new name {target!r} is a condition that is excluded or already used by an earlier recipe; merging into it would model those events twice")
        for r in state["regressors"]:
            cond = r.removeprefix("trial_type.")
            if r.startswith("trial_type.") and r != f"trial_type.{target}" and _coerce(cond) == _coerce(target) and cond not in sources:
                raise WizardError(f"new name {target!r} clashes with {cond!r} once output names are coerced; choose another name")
    elif any(ref in pm["Conditions"] for pm in state["pmods"]):
        raise WizardError(f"{ref!r} has a parametric modulator, so nothing can be merged into it; add the modulator last")
    state["instructions"].append({"Name": "Replace", "Input": "trial_type", "Output": "trial_type",
                                  "Replace": [{"key": f"^{re.escape(s)}$", "value": target} for s in sources]})
    for s in sources:
        _release(state, f"trial_type.{s}")
    if f"trial_type.{target}" not in state["regressors"]:
        state["regressors"].append(f"trial_type.{target}")


@recipe("parametric_modulator", "Parametric modulator",
        "Modulate a regressor by a numeric events column (e.g. RT or a rating); SPM mean-centres it.",
        [{"name": "regressor", "kind": "regressor", "label": "Regressor", "required": True},
         {"name": "column", "kind": "numeric_column", "label": "Numeric column", "required": True},
         {"name": "polynomial", "kind": "int", "label": "Polynomial order (1-3)", "required": False}])
def parametric_modulator(state, p):
    ref = _str_param("regressor", p.get("regressor"))
    column = _str_param("column", p.get("column"))
    poly = 1 if p.get("polynomial") is None else p["polynomial"]  # 0 must be rejected, not defaulted
    if ref not in state["regressors"]:
        raise WizardError(f"regressor {ref!r} is not available (unknown, or removed by an earlier recipe)")
    if column not in state["numeric"]:
        raise WizardError(f"column {column!r} is not a numeric events column")
    if UNSAFE.search(column):
        raise WizardError(f"column {column!r}: bidspm reads the modulator by its field name, so only letters, digits and underscores work; rename the column in the events first")
    if not isinstance(poly, int) or isinstance(poly, bool) or not 1 <= poly <= 3:
        raise WizardError("polynomial order must be 1, 2 or 3")
    name, n = f"{column}_mod", 1
    while any(m["Name"] == name for m in state["pmods"]):
        n += 1
        name = f"{column}_mod{n}"
    pm = {"Name": name, "Conditions": [ref], "Values": [column]}
    if poly > 1:
        pm["PolynomialExpansion"] = poly
    state["pmods"].append(pm)


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
        fn = RECIPES.get(_str_param("id", _expect(recipe, dict, "recipe").get("id")))
        if fn is None:
            raise WizardError(f"unknown recipe {recipe.get('id')!r}")
        fn(state, recipe)
    regressors = state["regressors"]
    if not regressors:
        raise WizardError("the model has no regressors left")
    seen = {}
    for r in regressors:
        spm_name = r.split(".", 1)[1]
        if spm_name in seen:
            raise WizardError(f"{seen[spm_name]!r} and {r!r} would get the same name ({spm_name!r}) in SPM; rename or merge one of them")
        seen[spm_name] = r
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


def scan_events(bids_dir, task, max_files=300, max_values=200):
    """Union of every events column and value over all subjects of a task (plus a dataset-level events file)."""
    root = Path(bids_dir)
    files = sorted(set(root.glob(f"sub-*/**/func/*task-{task}_*events.tsv")) | set(root.glob(f"task-{task}_events.tsv")))
    values, numeric_bad, truncated, used = {}, set(), set(), 0
    for path in files[:max_files]:
        try:
            with open(path, encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh, delimiter="\t"))
        except (OSError, UnicodeError, csv.Error):
            continue
        used += 1
        for row in rows:
            for col, val in row.items():
                if not col or col in ("onset", "duration") or val is None:
                    continue
                seen = values.setdefault(col, set())
                if val in NA:
                    continue
                try:
                    float(val)
                except ValueError:
                    numeric_bad.add(col)
                if val in seen:
                    continue
                if len(seen) >= max_values:
                    truncated.add(col)
                else:
                    seen.add(val)
    return {"files_truncated": len(files) > max_files,
            "columns": {c: sorted(v) for c, v in values.items()},
            "numeric": sorted(c for c, v in values.items() if v and c not in numeric_bad),
            "files": used, "truncated": sorted(truncated)}
