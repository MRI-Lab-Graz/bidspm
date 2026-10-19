"""Multi-run subjects in the Pipeline (found on study 132: ses-1, task-al run-1..3)."""
from pathlib import Path

from lib.core import Pipeline, PipelineOptions
from tests.test_core_helpers import _make_config


def _pipeline(tmp, actions=("stats",)):
    p = Pipeline(PipelineOptions(actions=list(actions)))
    p.config = _make_config(Path(tmp))
    p.model_file_path = None
    p.stats_node_name = None
    return p


def test_brain_mask_with_session_and_run_entities_is_copied(tmp_path):
    """The mask pattern wanted '..._task-<t>_space-...': a run-<n> (or acq-) entity in between never matched, so bidspm
    fell back to SPM's ICV mask, whose Octave-image path the standalone engine cannot open (all 3 subjects failed)."""
    p = _pipeline(tmp_path)
    func = p.config.FMRIPREP_DIR / "sub-01" / "ses-1" / "func"
    func.mkdir(parents=True)
    name = "sub-01_ses-1_task-motor_run-2_space-MNI152NLin2009cAsym_desc-brain_mask.nii"
    (func / name).write_text("mask")
    p._copy_brain_mask("01", "motor")
    assert (p.config.DERIVATIVES_DIR / "bidspm-preproc" / "sub-01" / "ses-1" / "func" / name).is_file()


def _two_runs(p, smoothed=("1", "2"), fwhm=6.0):
    """fMRIPrep preproc for run-1 and run-2; bidspm-preproc smoothed images for the runs in `smoothed`."""
    import gzip
    space = p.config.SPACE
    for run in ("1", "2"):
        base = f"sub-01_ses-1_task-motor_run-{run}_space-{space}"
        src = p.config.FMRIPREP_DIR / "sub-01" / "ses-1" / "func"
        src.mkdir(parents=True, exist_ok=True)
        with gzip.open(src / f"{base}_desc-preproc_bold.nii.gz", "wb") as fh:
            fh.write(b"x")
        if run in smoothed:
            dst = p.config.DERIVATIVES_DIR / "bidspm-preproc" / "sub-01" / "ses-1" / "func"
            dst.mkdir(parents=True, exist_ok=True)
            (dst / f"{base}_desc-smth{fwhm}_bold.nii").write_text("x")


def test_stats_fails_clearly_when_a_runs_smoothed_image_is_missing(tmp_path):
    from unittest.mock import patch
    p = _pipeline(tmp_path)
    _two_runs(p, smoothed=("1",))
    with patch.object(p, "_run_container_action", return_value=True) as container, patch.object(p, "_copy_brain_mask"):
        assert p._process_subject("01", "motor") is False
    container.assert_not_called()
    assert any("run-2" in e and "FWHM 6.0" in e for e in p.errors), p.errors


def test_stats_runs_when_every_run_is_smoothed(tmp_path):
    from unittest.mock import patch
    p = _pipeline(tmp_path)
    _two_runs(p)
    with patch.object(p, "_run_container_action", return_value=True) as container, patch.object(p, "_copy_brain_mask"), \
            patch("lib.core.find_new_spm_mats", return_value=[Path("SPM.mat")]):
        assert p._process_subject("01", "motor") is True
    container.assert_called()


def test_a_subject_with_one_of_two_runs_smoothed_is_not_already_smoothed(tmp_path):
    from lib.core import check_subject_processed
    p = _pipeline(tmp_path)
    _two_runs(p, smoothed=("1",))
    assert check_subject_processed(p.config, "01", "motor", "smooth") is False
    _two_runs(p)
    assert check_subject_processed(p.config, "01", "motor", "smooth") is True


def test_stats_ignores_runs_the_model_input_excludes(tmp_path):
    import json
    from unittest.mock import patch
    p = _pipeline(tmp_path)
    _two_runs(p, smoothed=("1",))
    model = tmp_path / "m.json"
    model.write_text(json.dumps({"Name": "m", "BIDSModelVersion": "1.0.0", "Input": {"task": ["motor"], "run": [1]}, "Nodes": []}))
    p.model_file_path = model
    with patch.object(p, "_run_container_action", return_value=True), patch.object(p, "_copy_brain_mask"), \
            patch("lib.core.find_new_spm_mats", return_value=[Path("SPM.mat")]):
        assert p._process_subject("01", "motor") is True, p.errors
