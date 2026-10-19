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
