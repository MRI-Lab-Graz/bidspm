import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import bidspm_gui
from bidspm_gui import _build_model_warnings
from bidspm_gui import _discover_confound_info
from bidspm_gui import _discover_event_info
from bidspm_gui import _discover_participants_info
from bidspm_gui import _extract_model_hints
from bidspm_gui import _normalize_subject_ids
from bidspm_gui import _normalize_token_list
from bidspm_gui import _pids_listening_on_port
from bidspm_gui import find_free_port
from bidspm_gui import kill_existing_on_port
from bidspm_gui import wait_for_http_ready


class TestBidspmGuiHelpers(unittest.TestCase):
    def test_find_free_port_finds_available_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            start_port = probe.getsockname()[1]

        port = find_free_port(start_port=start_port, max_tries=1)

        self.assertEqual(port, start_port)

    def test_wait_for_http_ready_handles_success_and_timeout(self):
        fake_response = MagicMock()
        fake_response.status = 200
        fake_context = MagicMock()
        fake_context.__enter__.return_value = fake_response
        fake_context.__exit__.return_value = False

        with patch("bidspm_gui.urllib.request.urlopen", side_effect=[Exception("down"), fake_context]):
            self.assertTrue(wait_for_http_ready("http://localhost:5100", timeout=1.0, interval=0.01))

        with patch("bidspm_gui.urllib.request.urlopen", side_effect=Exception("down")):
            self.assertFalse(wait_for_http_ready("http://localhost:5100", timeout=0.05, interval=0.01))

    def test_pid_helpers_parse_and_kill_processes(self):
        with patch(
            "bidspm_gui.subprocess.run",
            return_value=SimpleNamespace(stdout="LISTEN 0 128 *:5100 *:* users:((\"python\",pid=1234,fd=5),(\"python\",pid=5678,fd=6))"),
        ):
            self.assertEqual(_pids_listening_on_port(5100), [1234, 5678])

        with patch("bidspm_gui.os.getpid", return_value=9999), \
             patch("bidspm_gui._pids_listening_on_port", side_effect=[[1111, 2222], [], []]), \
             patch("bidspm_gui.os.kill") as mock_kill:
            self.assertTrue(kill_existing_on_port(5100))

        self.assertEqual(mock_kill.call_count, 2)

    def test_normalize_helpers_deduplicate_tokens_and_subjects(self):
        self.assertEqual(_normalize_token_list([" motor ", "motor", "", None, "rest"]), ["motor", "rest"])
        self.assertEqual(_normalize_subject_ids(["sub-01", "01", "sub-02", " 02 ", ""]), ["01", "02"])

    def test_extract_model_hints_collects_tasks_replace_levels_and_generated_columns(self):
        hints = _extract_model_hints(
            {
                "Input": {"task": ["motor", "rest"]},
                "Nodes": [
                    {
                        "Transformations": {
                            "GeneratedColumns": ["derived_a"],
                            "Instructions": [
                                {"Name": "Replace", "Replace": [{"value": "left"}, {"value": "right"}]},
                                {"Name": "Scale", "Output": ["scaled_a", "scaled_b"]},
                            ],
                        },
                        "Contrasts": [
                            {"ConditionList": ["trial_type.left", "condition.right", "derived_a"]}
                        ],
                    }
                ],
            }
        )

        self.assertEqual(hints["model_tasks"], ["motor", "rest"])
        self.assertEqual(hints["replace_values"], ["left", "right"])
        self.assertEqual(hints["contrast_levels"], ["derived_a", "left", "right"])
        self.assertEqual(hints["transformed_columns"], ["derived_a", "scaled_a", "scaled_b"])
        self.assertEqual(hints["field_status"]["model_tasks"], "present")
        self.assertEqual(hints["field_status"]["replace_values"], "present")
        self.assertEqual(hints["field_status"]["transformed_columns"], "present")

    def test_extract_model_hints_marks_invalid_shapes(self):
        hints = _extract_model_hints({"Input": {"task": 7}, "Nodes": {"bad": True}})

        self.assertEqual(hints["model_tasks"], [])
        self.assertEqual(hints["field_status"]["model_tasks"], "invalid")
        self.assertEqual(hints["field_status"]["replace_values"], "invalid")
        self.assertEqual(hints["field_status"]["contrast_levels"], "invalid")

    def test_discover_event_info_collects_columns_samples_and_numeric_fields(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            bids_dir = Path(tmp_dir)
            event_file = bids_dir / "sub-01" / "func" / "sub-01_task-motor_events.tsv"
            other_file = bids_dir / "sub-01" / "func" / "sub-01_task-rest_events.tsv"
            event_file.parent.mkdir(parents=True, exist_ok=True)
            event_file.write_text(
                "onset\tduration\ttrial_type\tcondition\trating\n"
                "0\t1\tleft\tgo\t1.5\n"
                "2\t1\tright\tstop\t2.5\n",
                encoding="utf-8",
            )
            other_file.write_text(
                "onset\tduration\ttrial_type\n0\t1\trest\n",
                encoding="utf-8",
            )

            info = _discover_event_info(bids_dir, tasks_filter=["motor"])

        self.assertEqual(info["files_scanned"], 1)
        self.assertIn("trial_type", info["event_columns"])
        self.assertEqual(info["sample_values"]["trial_type"], ["left", "right"])
        self.assertEqual(info["sample_values"]["condition"], ["go", "stop"])
        self.assertEqual(info["numeric_columns"], ["duration", "onset", "rating"])
        self.assertEqual(info["numeric_sample_values"]["rating"], ["1.5", "2.5"])
        self.assertEqual(info["sample_status"]["trial_type"], "present")

    def test_discover_confound_info_handles_missing_and_present_files(self):
        missing = _discover_confound_info(Path("/path/that/does/not/exist"))
        self.assertEqual(missing["sample_status"], "missing-dir")

        with tempfile.TemporaryDirectory() as tmp_dir:
            fmriprep_dir = Path(tmp_dir)
            confound_file = fmriprep_dir / "sub-01" / "func" / "sub-01_task-motor_desc-confounds_timeseries.tsv"
            confound_file.parent.mkdir(parents=True, exist_ok=True)
            confound_file.write_text(
                "trans_x\ttrans_y\trot_x\ta_comp_cor_00\n0\t0\t0\t0.1\n",
                encoding="utf-8",
            )

            info = _discover_confound_info(fmriprep_dir, tasks_filter=["motor"])

        self.assertEqual(info["files_scanned"], 1)
        self.assertEqual(info["sample_status"], "present")
        self.assertEqual(info["trans_rot_present"], ["trans_x", "trans_y", "rot_x"])
        self.assertIn("a_comp_cor_00", info["columns"])

    def test_discover_confound_info_task_filter_excludes_all_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            fmriprep_dir = Path(tmp_dir)
            confound_file = fmriprep_dir / "sub-01" / "func" / "sub-01_task-motor_desc-confounds_timeseries.tsv"
            confound_file.parent.mkdir(parents=True, exist_ok=True)
            confound_file.write_text("trans_x\n0\n", encoding="utf-8")

            info = _discover_confound_info(fmriprep_dir, tasks_filter=["rest"])

        self.assertEqual(info["sample_status"], "missing-files")
        self.assertEqual(info["files_scanned"], 0)

    def test_discover_confound_info_empty_file_reports_empty_status(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            fmriprep_dir = Path(tmp_dir)
            confound_file = fmriprep_dir / "sub-01" / "func" / "sub-01_task-motor_desc-confounds_timeseries.tsv"
            confound_file.parent.mkdir(parents=True, exist_ok=True)
            confound_file.write_text("", encoding="utf-8")  # no header at all

            info = _discover_confound_info(fmriprep_dir)

        self.assertEqual(info["sample_status"], "empty")
        self.assertEqual(info["columns"], [])

    def test_discover_participants_info_handles_file_states(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            bids_dir = Path(tmp_dir)

            missing = _discover_participants_info(bids_dir)
            self.assertEqual(missing["sample_status"], "missing-file")

            (bids_dir / "participants.tsv").write_text(
                "participant_id\tgroup\tage\n"
                "sub-01\tcontrol\t29\n"
                "sub-02\tpatient\t34\n",
                encoding="utf-8",
            )

            info = _discover_participants_info(bids_dir)

        self.assertEqual(info["sample_status"], "present")
        self.assertEqual(info["categorical_columns"], ["group"])
        self.assertEqual(info["numeric_columns"], ["age"])
        self.assertEqual(info["sample_values"]["group"], ["control", "patient"])
        self.assertEqual(info["numeric_stats"]["age"]["count"], 2)
        self.assertEqual(info["numeric_stats"]["age"]["min"], 29.0)
        self.assertEqual(info["numeric_stats"]["age"]["max"], 34.0)

    def test_build_model_warnings_flags_task_and_condition_mismatches(self):
        warnings = _build_model_warnings(
            {
                "model_tasks": ["motro"],
                "replace_values": [],
                "contrast_levels": ["left", "rgiht", "derived_col"],
                "transformed_columns": ["derived_col"],
            },
            ["motor", "rest"],
            {
                "profile_variants": {"trial_type": 2},
                "all_values": {"trial_type": ["left", "right"], "condition": ["go", "stop"]},
            },
        )

        self.assertTrue(any("Task 'motro'" in warning for warning in warnings))
        self.assertTrue(any("Contrast level 'rgiht'" in warning for warning in warnings))
        self.assertTrue(any("distinct trial_type profiles" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()