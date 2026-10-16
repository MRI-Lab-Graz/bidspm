"""Synthetic BIDS + fMRIPrep trees for the preflight tests (not a test module)."""
import json
from pathlib import Path

import nibabel as nib
import numpy as np

EVENTS = "onset\tduration\ttrial_type\n1\t1\ta\n5\t1\tb\n"
CONFOUNDS = "trans_x\ttrans_y\ttrans_z\nn/a\t0\t0\n"


def make_trees(tmp, subjects=("01",), task="x", space="MNI", events=EVENTS, confounds=CONFOUNDS, tr=2.0, nvols=100):
    bids, fmriprep = Path(tmp) / "bids", Path(tmp) / "fmriprep"
    for root in (bids, fmriprep):
        root.mkdir(parents=True, exist_ok=True)
        (root / "dataset_description.json").write_text(json.dumps({"Name": "t", "BIDSVersion": "1.9.0"}))
    for s in subjects:
        b, f = bids / f"sub-{s}" / "func", fmriprep / f"sub-{s}" / "func"
        b.mkdir(parents=True, exist_ok=True)
        f.mkdir(parents=True, exist_ok=True)
        (b / f"sub-{s}_task-{task}_events.tsv").write_text(events)
        stem = f"sub-{s}_task-{task}_space-{space}_desc"
        nib.save(nib.Nifti1Image(np.zeros((2, 2, 2, nvols), "f4"), np.eye(4)), f / f"{stem}-preproc_bold.nii.gz")
        (f / f"{stem}-preproc_bold.json").write_text(json.dumps({"RepetitionTime": tr}))
        (f / f"sub-{s}_task-{task}_desc-confounds_timeseries.tsv").write_text(confounds)
    return bids, fmriprep


def write_model(tmp, x=("trial_type.a", "trial_type.b", 1), transformations=False):
    node = {"Level": "Run", "Name": "run", "GroupBy": ["run", "subject"], "Model": {"X": list(x), "Type": "glm"}}
    if transformations:
        node["Transformations"] = {"Transformer": "bidspm", "Instructions": [
            {"Name": "Filter", "Input": ["trial_type"], "Query": "trial_type=='a'"}]}
    path = Path(tmp) / "model.json"
    path.write_text(json.dumps({"Name": "m", "BIDSModelVersion": "1.0.0", "Input": {"task": ["x"]}, "Nodes": [node]}))
    return path
