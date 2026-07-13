import json
import tempfile
import unittest
from pathlib import Path

from webapp.web_utility_stats_api import (
    _build_stats_subject_coverage_report,
    _extract_subject_from_path,
    _extract_task_from_name,
    _model_tasks_from_file,
    _scan_subject_task_map,
    _sort_subject_ids,
)


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def _normalize_tokens(values):
    items = values if isinstance(values, list) else ([values] if values else [])
    normalized = []
    for item in items:
      token = str(item or "").strip()
      if token and token not in normalized:
          normalized.append(token)
    return normalized


def _normalize_subjects(values):
    normalized = []
    for token in _normalize_tokens(values):
        subject = token[4:] if token.startswith("sub-") else token
        if subject and subject not in normalized:
            normalized.append(subject)
    return normalized


class TestUtilityStatsHelpers(unittest.TestCase):
    def test_sort_and_extract_helpers_handle_bids_tokens(self):
        self.assertEqual(_sort_subject_ids(["10", "alpha", "2", "01"]), ["01", "2", "10", "alpha"])
        self.assertEqual(_extract_task_from_name("sub-01_task-motor_run-01_events.tsv"), "motor")
        self.assertEqual(
            _extract_subject_from_path(Path("/tmp/demo/sub-07/ses-01/func/sub-07_task-motor_events.tsv")),
            "07",
        )

    def test_scan_subject_task_map_supports_filters_and_wildcards(self):
        files = [
            Path("/tmp/sub-01/func/sub-01_task-motor_events.tsv"),
            Path("/tmp/sub-01/func/sub-01_events.tsv"),
            Path("/tmp/sub-02/func/sub-02_task-rest_events.tsv"),
        ]

        all_tasks = _scan_subject_task_map(files, [])
        motor_only = _scan_subject_task_map(files, ["motor"])

        self.assertEqual(all_tasks, {"01": {"motor", "*"}, "02": {"rest"}})
        self.assertEqual(motor_only, {"01": {"motor"}})

    def test_model_tasks_from_file_reads_and_normalizes_model_input(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            model_path = Path(tmp_dir) / "model.json"
            model_path.write_text(
                json.dumps({"Input": {"task": ["motor", "", "rest", "motor"]}}),
                encoding="utf-8",
            )

            tasks = _model_tasks_from_file(str(model_path), lambda value: value, _normalize_tokens)
            missing = _model_tasks_from_file(str(Path(tmp_dir) / "missing.json"), lambda value: value, _normalize_tokens)

        self.assertEqual(tasks, ["motor", "rest"])
        self.assertEqual(missing, [])

    def test_build_stats_subject_coverage_report_uses_model_tasks_fallback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bids_dir = root / "bids"
            fmriprep_dir = root / "fmriprep"
            model_path = root / "model.json"

            _touch(bids_dir / "sub-01" / "func" / "sub-01_task-motor_events.tsv")
            _touch(fmriprep_dir / "sub-01" / "func" / "sub-01_task-motor_desc-preproc_bold.nii.gz")
            (bids_dir / "sub-02").mkdir(parents=True, exist_ok=True)
            model_path.write_text(json.dumps({"Input": {"task": ["motor"]}}), encoding="utf-8")

            report = _build_stats_subject_coverage_report(
                bids_dir=str(bids_dir),
                fmriprep_dir=str(fmriprep_dir),
                tasks=[],
                selected_subjects=["sub-01", "02"],
                model_file=str(model_path),
                resolve_fs_path=lambda value: value,
                normalize_token_list=_normalize_tokens,
                normalize_subject_ids=_normalize_subjects,
            )

        self.assertFalse(report["ok"])
        self.assertEqual(report["tasks_considered"], ["motor"])
        self.assertEqual(report["selected_subjects"], ["01", "02"])
        self.assertEqual(report["ready_subjects"], ["01"])
        self.assertEqual(report["missing_subject_ids"], ["02"])
        self.assertEqual(report["summary"], {"total_subjects": 2, "ready_subjects": 1, "missing_subjects": 1})
        self.assertIn("missing fMRIPrep subject folder", report["missing_subjects"][0]["issues"])
        self.assertIn("missing events for task(s): motor", report["missing_subjects"][0]["issues"])
        self.assertIn("missing fMRIPrep preproc for task(s): motor", report["missing_subjects"][0]["issues"])

    def test_build_stats_subject_coverage_report_reports_missing_roots(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            report = _build_stats_subject_coverage_report(
                bids_dir=str(root / "missing-bids"),
                fmriprep_dir=str(root / "missing-fmriprep"),
                tasks=["motor"],
                selected_subjects=[],
                model_file="",
                resolve_fs_path=lambda value: value,
                normalize_token_list=_normalize_tokens,
                normalize_subject_ids=_normalize_subjects,
            )

        self.assertFalse(report["ok"])
        self.assertEqual(report["tasks_considered"], ["motor"])
        self.assertEqual(report["summary"], {"total_subjects": 0, "ready_subjects": 0, "missing_subjects": 0})
        self.assertIn("BIDS folder is missing or not accessible.", report["messages"])
        self.assertIn("fMRIPrep folder is missing or not accessible.", report["messages"])
        self.assertIn("No subjects detected from BIDS/fMRIPrep folders.", report["messages"])
