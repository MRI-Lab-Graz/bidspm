"""The dataset step only gets subjects whose stats succeeded, and a failed/skipped dataset step is not 'completed'."""
import tempfile
from pathlib import Path
from unittest.mock import patch

from lib import core
from tests.test_core_helpers import _make_config


def _run(outcomes, dataset_ok=True, actions=("stats", "dataset")):
    calls = []
    pipeline = core.Pipeline(core.PipelineOptions(actions=list(actions), force=True))
    pipeline.config = _make_config(Path(tempfile.mkdtemp()))
    pipeline.setup = lambda: True
    pipeline.get_subjects_to_process = lambda: list(outcomes)

    def process(subject, task):
        if not outcomes[subject]:
            pipeline._log_error(f"Stats for subject {subject}, task {task}: the container exited 0 but wrote no SPM.mat")
        return outcomes[subject]

    pipeline._process_subject = process
    pipeline._run_container_dataset_action = lambda task, subjects=None: calls.append(list(subjects)) or dataset_ok
    with patch("lib.core.validate_space_availability", return_value=True), \
         patch("lib.core.validate_events_availability", return_value=True), \
         patch("lib.core.ensure_derivatives_dataset_description"), \
         patch("lib.core.cleanup_tmp_directories"):
        result = pipeline.run()
    return result, calls


def test_dataset_step_gets_only_the_subjects_whose_stats_succeeded():
    result, calls = _run({"01": True, "02": False, "03": True})
    assert calls == [["01", "03"]]
    assert "dataset" in result.actions_completed
    assert not result.success  # subject 02 still failed
    assert any("02" in e and "left out" in e for e in result.warnings + result.errors)


def test_dataset_step_is_skipped_with_fewer_than_two_good_subjects():
    result, calls = _run({"01": True, "02": False, "03": False})
    assert calls == []
    assert "dataset" not in result.actions_completed and not result.success
    msg = [e for e in result.errors if "Dataset" in e]
    assert msg and "02" in msg[0] and "03" in msg[0] and "wrote no SPM.mat" in msg[0]


def test_failed_dataset_step_is_not_reported_completed():
    result, calls = _run({"01": True, "02": True}, dataset_ok=False)
    assert calls == [["01", "02"]]
    assert "dataset" not in result.actions_completed and not result.success
    assert any("Dataset" in e for e in result.errors)


def test_dataset_only_run_passes_all_subjects():
    result, calls = _run({"01": True, "02": True}, actions=("dataset",))
    assert calls == [["01", "02"]] and result.success and "dataset" in result.actions_completed


def test_dataset_action_labels_the_given_subjects():
    pipeline = core.Pipeline(core.PipelineOptions(actions=["dataset"], dry_run=True))
    pipeline.config = _make_config(Path(tempfile.mkdtemp()))
    with patch("lib.core.build_container_command", return_value=(["x"], None)) as build:
        pipeline._run_container_dataset_action("motor", ["01", "03"])
    args = build.call_args[0][2]
    i = args.index("--participant_label")
    assert args[i + 1:i + 3] == ["01", "03"]
