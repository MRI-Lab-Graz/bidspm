"""Empty TASKS: the pipeline and the preflight pick the same tasks (explicit, else model Input.task, else discovery)."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from lib.config import ContainerConfig
from lib.core import Pipeline, PipelineOptions
from lib.preflight import resolve_tasks
from tests.test_core_helpers import _make_config


def _bids_with(root, task):
    func = root / "bids" / "sub-01" / "func"
    func.mkdir(parents=True)
    (func / f"sub-01_task-{task}_bold.nii.gz").write_text("x")


class TestResolveTasks(unittest.TestCase):
    def test_order_explicit_then_model_then_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bids_with(root, "found")
            model = root / "m.json"
            model.write_text(json.dumps({"Input": {"task": "fromModel"}}))
            bids = root / "bids"
            self.assertEqual(resolve_tasks(["a"], str(model), bids), ["a"])
            self.assertEqual(resolve_tasks([], str(model), bids), ["fromModel"])
            self.assertEqual(resolve_tasks([], "", bids), ["found"])


class TestPipelineUsesFallback(unittest.TestCase):
    def _processed_tasks(self, tasks, model_task=None):
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _bids_with(root, "found")
            model = root / "m.json"
            model.write_text(json.dumps({"Input": {"task": model_task}} if model_task else {}))
            pipeline = Pipeline(PipelineOptions(actions=["stats"], dry_run=True, model_file=str(model)))
            config = replace(_make_config(root), TASKS=tasks)
            pipeline.config = config
            pipeline.container_config = ContainerConfig(container_type="docker", docker_image="x:latest")
            pipeline.model_file_path = model
            with patch.object(Pipeline, "setup", return_value=True), \
                 patch.object(Pipeline, "_check_standalone_image", return_value=True), \
                 patch.object(Pipeline, "get_subjects_to_process", return_value=["01"]), \
                 patch.object(Pipeline, "_skip_if_processed", return_value=False), \
                 patch.object(Pipeline, "_process_subject", side_effect=lambda s, t: seen.append(t) or True), \
                 patch("lib.core.validate_space_availability", return_value=True), \
                 patch("lib.core.validate_events_availability", return_value=True), \
                 patch("lib.core.ensure_derivatives_dataset_description"), \
                 patch("lib.core.cleanup_tmp_directories"):
                pipeline.run()
        return seen

    def test_explicit_tasks_win(self):
        self.assertEqual(self._processed_tasks(["x"], "fromModel"), ["x"])

    def test_empty_tasks_use_model_task(self):
        self.assertEqual(self._processed_tasks([], "fromModel"), ["fromModel"])

    def test_empty_tasks_and_model_without_task_discover(self):
        self.assertEqual(self._processed_tasks([]), ["found"])
