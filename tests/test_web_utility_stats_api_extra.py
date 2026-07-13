import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bidspm_gui
from bidspm_gui import app as flask_app
from lib.project_manager import ProjectManager
from webapp.web_utility_stats_api import (
    _build_participants_status_report,
    _normalize_fwhm,
)
from bidspm_gui import _normalize_token_list


class TestNormalizeFwhm(unittest.TestCase):
    def test_whole_number_float_becomes_int(self):
        self.assertEqual(_normalize_fwhm(6.0), 6)
        self.assertIsInstance(_normalize_fwhm(6.0), int)

    def test_fractional_value_stays_float(self):
        self.assertEqual(_normalize_fwhm(6.5), 6.5)

    def test_non_numeric_value_passed_through_unchanged(self):
        self.assertEqual(_normalize_fwhm("not-a-number"), "not-a-number")
        self.assertIsNone(_normalize_fwhm(None))


class TestBuildParticipantsStatusReport(unittest.TestCase):
    def test_not_evaluable_when_inputs_insufficient_marks_subjects_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bids_dir = root / "bids"
            (bids_dir / "sub-01").mkdir(parents=True)

            report = _build_participants_status_report(
                bids_dir=str(bids_dir),
                fmriprep_dir="",
                derivatives_dir="",  # missing derivatives -> can_evaluate False
                actions=["smooth"],
                tasks=["motor"],
                space="MNI152NLin2009cAsym",
                fwhm=6,
                model_file="",
                resolve_fs_path=lambda p: p,
                normalize_token_list=_normalize_token_list,
                check_subject_processed=lambda *a, **k: True,
            )

            self.assertFalse(report["evaluable"])
            self.assertEqual(report["details"][0]["status"], "unknown")
            self.assertEqual(report["summary"]["total"], 1)

    def test_evaluable_reports_computed_and_missing_subjects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bids_dir = root / "bids"
            derivatives_dir = root / "derivatives"
            (bids_dir / "sub-01").mkdir(parents=True)
            (bids_dir / "sub-02").mkdir(parents=True)
            derivatives_dir.mkdir(parents=True)

            def fake_check_subject_processed(config, subject, task, action):
                return subject == "01"  # only sub-01 counts as done

            report = _build_participants_status_report(
                bids_dir=str(bids_dir),
                fmriprep_dir="",
                derivatives_dir=str(derivatives_dir),
                actions=["smooth", "stats"],
                tasks=["motor"],
                space="MNI152NLin2009cAsym",
                fwhm=6,
                model_file="",
                resolve_fs_path=lambda p: p,
                normalize_token_list=_normalize_token_list,
                check_subject_processed=fake_check_subject_processed,
            )

            self.assertTrue(report["evaluable"])
            self.assertEqual(report["computed_subjects"], ["01"])
            self.assertEqual(report["missing_subjects"], ["02"])
            missing_detail = next(d for d in report["details"] if d["subject"] == "02")
            self.assertIn("smooth:motor", missing_detail["pending"])
            self.assertIn("stats:motor", missing_detail["pending"])

    def test_falls_back_to_model_tasks_when_no_tasks_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_file = root / "model.json"
            model_file.write_text(
                '{"Input": {"task": ["motor"]}}', encoding="utf-8"
            )
            bids_dir = root / "bids"
            derivatives_dir = root / "derivatives"
            (bids_dir / "sub-01").mkdir(parents=True)
            derivatives_dir.mkdir(parents=True)

            report = _build_participants_status_report(
                bids_dir=str(bids_dir),
                fmriprep_dir="",
                derivatives_dir=str(derivatives_dir),
                actions=["smooth"],
                tasks=[],
                space="MNI152NLin2009cAsym",
                fwhm=6,
                model_file=str(model_file),
                resolve_fs_path=lambda p: p,
                normalize_token_list=_normalize_token_list,
                check_subject_processed=lambda *a, **k: True,
            )

            self.assertEqual(report["tasks_considered"], ["motor"])


class TestParticipantsStatusRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app.config.update(TESTING=True)
        cls.client = flask_app.test_client()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.project_manager = ProjectManager(Path(self.temp_dir.name) / "projects")
        self.project_manager_patch = patch.object(bidspm_gui, "project_manager", self.project_manager)
        self.project_manager_patch.start()
        self.addCleanup(self.project_manager_patch.stop)

    def test_missing_project_returns_404(self):
        response = self.client.post(
            "/api/participants_status", json={"project_id": "does-not-exist"}
        )
        self.assertEqual(response.status_code, 404)

    def test_direct_params_report_all_missing_when_nothing_processed(self):
        root = Path(self.temp_dir.name)
        bids_dir = root / "bids"
        derivatives_dir = root / "derivatives"
        (bids_dir / "sub-01" / "func").mkdir(parents=True)
        derivatives_dir.mkdir(parents=True)

        response = self.client.post(
            "/api/participants_status",
            json={
                "bids_dir": str(bids_dir),
                "derivatives_dir": str(derivatives_dir),
                "actions": ["smooth"],
                "tasks": ["motor"],
                "space": "MNI152NLin2009cAsym",
                "fwhm": 6,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["evaluable"])
        self.assertEqual(payload["missing_subjects"], ["01"])
        self.assertIsNone(payload["project_id"])


if __name__ == "__main__":
    unittest.main()
