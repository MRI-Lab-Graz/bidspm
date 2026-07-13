import tempfile
import unittest
from pathlib import Path

from webapp.web_discovery_model_api import (
    _build_default_model,
    _extract_model_hints,
    _extract_task_name,
    _scan_bids_for_model,
)


class TestExtractModelHintsMalformedNodes(unittest.TestCase):
    """Covers per-node malformed-shape branches not hit by the happy-path /
    top-level-invalid-shape tests in tests/test_bidspm_gui_helpers.py."""

    def test_task_as_bare_string_is_wrapped_in_a_list(self):
        hints = _extract_model_hints({"Input": {"task": "motor"}, "Nodes": []})
        self.assertEqual(hints["model_tasks"], ["motor"])

    def test_non_dict_node_marks_replace_and_contrast_levels_invalid(self):
        hints = _extract_model_hints({"Nodes": [123]})
        self.assertEqual(hints["field_status"]["replace_values"], "invalid")
        self.assertEqual(hints["field_status"]["contrast_levels"], "invalid")

    def test_non_dict_transformations_marks_invalid(self):
        hints = _extract_model_hints({"Nodes": [{"Transformations": "not-a-dict"}]})
        self.assertEqual(hints["field_status"]["replace_values"], "invalid")
        self.assertEqual(hints["field_status"]["transformed_columns"], "invalid")

    def test_non_list_generated_columns_marks_invalid(self):
        hints = _extract_model_hints({
            "Nodes": [{"Transformations": {"GeneratedColumns": "not-a-list"}}],
        })
        self.assertEqual(hints["field_status"]["transformed_columns"], "invalid")

    def test_non_dict_instruction_marks_invalid_and_is_skipped(self):
        hints = _extract_model_hints({
            "Nodes": [{"Transformations": {"Instructions": [123]}}],
        })
        self.assertEqual(hints["field_status"]["replace_values"], "invalid")
        self.assertEqual(hints["field_status"]["transformed_columns"], "invalid")

    def test_non_string_non_list_output_marks_invalid(self):
        hints = _extract_model_hints({
            "Nodes": [{"Transformations": {"Instructions": [{"Output": 5}]}}],
        })
        self.assertEqual(hints["field_status"]["transformed_columns"], "invalid")

    def test_output_list_with_invalid_entry_keeps_valid_entries_and_reports_present(self):
        # A later valid entry makes the field "present" overall even though an
        # earlier entry in the same list was invalid (see lines 158-161).
        hints = _extract_model_hints({
            "Nodes": [{"Transformations": {"Instructions": [{"Output": ["scaled_a", 123, ""]}]}}],
        })
        self.assertIn("scaled_a", hints["transformed_columns"])
        self.assertEqual(hints["field_status"]["transformed_columns"], "present")

    def test_replace_entries_not_a_list_marks_invalid(self):
        hints = _extract_model_hints({
            "Nodes": [{"Transformations": {"Instructions": [
                {"Name": "Replace", "Replace": "not-a-list"},
            ]}}],
        })
        self.assertEqual(hints["field_status"]["replace_values"], "invalid")

    def test_replace_entry_not_a_dict_keeps_valid_entries_and_reports_present(self):
        hints = _extract_model_hints({
            "Nodes": [{"Transformations": {"Instructions": [
                {"Name": "Replace", "Replace": [123, {"value": "kept"}]},
            ]}}],
        })
        self.assertEqual(hints["field_status"]["replace_values"], "present")
        self.assertIn("kept", hints["replace_values"])

    def test_contrasts_not_a_list_marks_invalid(self):
        hints = _extract_model_hints({"Nodes": [{"Contrasts": "not-a-list"}]})
        self.assertEqual(hints["field_status"]["contrast_levels"], "invalid")

    def test_contrast_entry_not_a_dict_marks_invalid(self):
        hints = _extract_model_hints({"Nodes": [{"Contrasts": [123]}]})
        self.assertEqual(hints["field_status"]["contrast_levels"], "invalid")

    def test_condition_list_not_a_list_marks_invalid(self):
        hints = _extract_model_hints({
            "Nodes": [{"Contrasts": [{"ConditionList": "not-a-list"}]}],
        })
        self.assertEqual(hints["field_status"]["contrast_levels"], "invalid")

    def test_condition_list_term_not_a_string_keeps_valid_entries_and_reports_present(self):
        hints = _extract_model_hints({
            "Nodes": [{"Contrasts": [{"ConditionList": [123, "trial_type.left", "plainterm"]}]}],
        })
        self.assertEqual(hints["field_status"]["contrast_levels"], "present")
        self.assertIn("left", hints["contrast_levels"])
        self.assertIn("plainterm", hints["contrast_levels"])


class TestExtractTaskName(unittest.TestCase):
    def test_extracts_task_token(self):
        self.assertEqual(_extract_task_name("sub-01_task-motor_events.tsv"), "motor")

    def test_returns_empty_string_when_no_task_token(self):
        self.assertEqual(_extract_task_name("sub-01_events.tsv"), "")


class TestScanBidsForModel(unittest.TestCase):
    def test_collects_tasks_and_trial_types_across_subjects(self):
        with tempfile.TemporaryDirectory() as tmp:
            bids_dir = Path(tmp)
            events1 = bids_dir / "sub-01" / "func" / "sub-01_task-motor_events.tsv"
            events1.parent.mkdir(parents=True, exist_ok=True)
            events1.write_text("onset\tduration\ttrial_type\n0\t1\tleft\n1\t1\tright\n", encoding="utf-8")

            events2 = bids_dir / "sub-02" / "ses-01" / "func" / "sub-02_ses-01_task-motor_events.tsv"
            events2.parent.mkdir(parents=True, exist_ok=True)
            events2.write_text("onset\tduration\ttrial_type\n0\t1\tleft\n1\t1\tn/a\n", encoding="utf-8")

            result = _scan_bids_for_model(str(bids_dir))

            self.assertEqual(result["tasks"], ["motor"])
            self.assertEqual(result["trial_types_by_task"]["motor"], ["left", "right"])

    def test_skips_files_without_task_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            bids_dir = Path(tmp)
            events = bids_dir / "sub-01" / "func" / "sub-01_events.tsv"
            events.parent.mkdir(parents=True, exist_ok=True)
            events.write_text("onset\tduration\n0\t1\n", encoding="utf-8")

            result = _scan_bids_for_model(str(bids_dir))
            self.assertEqual(result["tasks"], [])

    def test_unreadable_events_file_is_skipped_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            bids_dir = Path(tmp)
            events = bids_dir / "sub-01" / "func" / "sub-01_task-motor_events.tsv"
            events.parent.mkdir(parents=True, exist_ok=True)
            events.write_bytes(b"\xff\xfe not valid utf-8 \x00\x01")

            result = _scan_bids_for_model(str(bids_dir))
            self.assertEqual(result["tasks"], ["motor"])
            self.assertEqual(result["trial_types_by_task"], {})


class TestBuildDefaultModel(unittest.TestCase):
    def test_single_task_with_conditions_builds_run_subject_dataset_nodes(self):
        model = _build_default_model(["motor"], {"motor": ["left", "right"]})

        self.assertEqual(model["Input"]["task"], ["motor"])
        levels = [node["Level"] for node in model["Nodes"]]
        self.assertEqual(levels, ["Run", "Subject", "Dataset"])
        run_node = model["Nodes"][0]
        self.assertEqual(run_node["Name"], "run_level")
        self.assertEqual(len(run_node["Contrasts"]), 2)
        # Two-condition contrast weights sum to zero (a proper t-contrast).
        self.assertAlmostEqual(sum(run_node["Contrasts"][0]["Weights"]), 0.0)

    def test_multi_task_names_nodes_per_task(self):
        model = _build_default_model(["motor", "rest"], {})
        run_nodes = [n for n in model["Nodes"] if n["Level"] == "Run"]
        self.assertEqual({n["Name"] for n in run_nodes}, {"run_level_motor", "run_level_rest"})

    def test_task_without_conditions_falls_back_to_condition_a(self):
        model = _build_default_model(["motor"], {})
        run_node = model["Nodes"][0]
        self.assertEqual(run_node["Contrasts"][0]["Name"], "condition_a")
        self.assertEqual(run_node["Contrasts"][0]["Weights"], [1])


if __name__ == "__main__":
    unittest.main()
