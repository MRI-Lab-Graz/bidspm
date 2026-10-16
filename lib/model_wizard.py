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
