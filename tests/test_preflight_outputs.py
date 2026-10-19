"""R3: a stats run without Smooth needs the smoothed image of every run; a dataset-only run needs the subject results."""
import json
import struct

from lib.preflight import run_preflight
from tests.preflight_support import make_trees, write_model


def _smooth(fmri, deriv, run, fwhm):
    d = deriv / "bidspm-preproc" / "sub-01" / "func"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"sub-01_task-x_run-{run}_space-MNI_desc-smth{fwhm}_bold.nii").write_text("x")


def _check(tmp_path, actions, model=None, fwhm=6):
    bids, fmri = make_trees(tmp_path, runs=("1", "2"))
    return bids, fmri, dict(bids_dir=bids, fmriprep_dir=fmri, tasks=["x"], space="MNI", validator="skip",
                            model_file=model or write_model(tmp_path), actions=actions,
                            derivatives_dir=tmp_path / "deriv", fwhm=fwhm)


def _items(report, id):
    return [c for c in report["checks"] if c["id"] == id]


def test_stats_without_smooth_needs_every_runs_smoothed_image(tmp_path):
    bids, fmri, args = _check(tmp_path, ["stats"])
    _smooth(fmri, tmp_path / "deriv", "1", 6)
    (item,) = _items(run_preflight(**args), "smoothed_missing")
    assert item["severity"] == "error" and "run-2" in item["message"] and "FWHM 6" in item["message"]
    assert item["fix"] == "add Smooth to the actions or run smoothing first (FWHM 6)"


def test_smoothed_at_another_fwhm_is_mentioned(tmp_path):
    bids, fmri, args = _check(tmp_path, ["stats"])
    for run in ("1", "2"):
        _smooth(fmri, tmp_path / "deriv", run, 8)
    items = _items(run_preflight(**args), "smoothed_missing")
    assert len(items) == 2 and all("FWHM 8" in i["message"] for i in items)


def test_all_runs_smoothed_is_ready(tmp_path):
    bids, fmri, args = _check(tmp_path, ["stats"])
    for run in ("1", "2"):
        _smooth(fmri, tmp_path / "deriv", run, 6)
    assert _items(run_preflight(**args), "smoothed_missing") == []


def test_smooth_in_the_actions_skips_the_check(tmp_path):
    bids, fmri, args = _check(tmp_path, ["smooth", "stats"])
    assert _items(run_preflight(**args), "smoothed_missing") == []


def _dataset_model(tmp_path):
    path = tmp_path / "dsmodel.json"
    path.write_text(json.dumps({"Name": "m", "BIDSModelVersion": "1.0.0", "Input": {"task": ["x"]}, "Nodes": [
        {"Level": "Run", "Name": "run", "GroupBy": ["run", "subject"], "Model": {"X": ["trial_type.a", 1], "Type": "glm"}},
        {"Level": "Dataset", "Name": "dataset", "GroupBy": ["contrast"], "Model": {"X": [1], "Type": "glm"},
         "DummyContrasts": {"Test": "t", "Contrasts": ["a"]}}]}))
    return path


def _results(deriv, names, fwhm=6):
    d = deriv / "bidspm-stats" / "sub-01" / f"task-x_space-MNI_FWHM-{fwhm}"
    d.mkdir(parents=True)
    (d / "SPM.mat").write_text("x")
    for i, name in enumerate(names, 1):  # NIfTI-1 header: descrip (80 bytes) at offset 148, as spm_contrasts writes it
        hdr = bytearray(352)
        hdr[148:228] = f"Contrast {i}: {name}".encode().ljust(80, b"\0")
        (d / f"con_{i:04d}.nii").write_bytes(bytes(hdr))


def test_dataset_only_needs_the_subject_results(tmp_path):
    bids, fmri, args = _check(tmp_path, ["dataset"], model=_dataset_model(tmp_path))
    (item,) = _items(run_preflight(**args), "subject_results_missing")
    assert item["severity"] == "error" and "sub-01" in item["message"]


def test_dataset_only_needs_the_contrast_the_dataset_node_uses(tmp_path):
    bids, fmri, args = _check(tmp_path, ["dataset"], model=_dataset_model(tmp_path))
    _results(tmp_path / "deriv", ["b"])
    (item,) = _items(run_preflight(**args), "subject_results_missing")
    assert "'a'" in item["message"]


def test_dataset_only_with_results_is_ready(tmp_path):
    bids, fmri, args = _check(tmp_path, ["dataset"], model=_dataset_model(tmp_path))
    _results(tmp_path / "deriv", ["a_ses-1", "a"])
    assert _items(run_preflight(**args), "subject_results_missing") == []


def test_signature_tracks_fwhm_and_derivatives_only_when_earlier_outputs_are_read():
    from lib.preflight import signature
    a, b = {"FWHM": 6, "DERIVATIVES_DIR": "/d"}, {"FWHM": 8, "DERIVATIVES_DIR": "/d"}
    assert signature(a, "", "skip", ["stats"], True) != signature(b, "", "skip", ["stats"], True)
    assert signature(a, "", "skip", ["smooth", "stats"], True) == signature(b, "", "skip", ["smooth", "stats"], True)


def test_float_fwhm_matches_bidspms_whole_number_naming(tmp_path):
    """bidspm writes desc-smth6 / FWHM-6 for 6.0 (num2str); a float from the settings must not miss them."""
    bids, fmri, args = _check(tmp_path, ["stats"], fwhm=6.0)
    for run in ("1", "2"):
        _smooth(fmri, tmp_path / "deriv", run, 6)
    assert _items(run_preflight(**args), "smoothed_missing") == []


def test_results_at_fwhm_60_do_not_count_for_fwhm_6(tmp_path):
    bids, fmri, args = _check(tmp_path, ["dataset"], model=_dataset_model(tmp_path))
    _results(tmp_path / "deriv", ["a"], fwhm=60)
    assert len(_items(run_preflight(**args), "subject_results_missing")) == 1


def test_smoothed_file_name_uses_the_whole_number_fwhm():
    from pathlib import Path
    from lib.fast_smooth import _smth_path
    assert _smth_path(Path("sub-01_task-x_space-MNI_desc-preproc_bold.nii"), 6.0).name == \
        "sub-01_task-x_space-MNI_desc-smth6_bold.nii"
