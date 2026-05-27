import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fix_events_format.py"
SPEC = importlib.util.spec_from_file_location("fix_events_format", MODULE_PATH)
fix_events_format = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fix_events_format)


class TestFixEventsFormat(unittest.TestCase):
    def test_find_matching_excel_normalizes_subject_name(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            excel_dir = Path(tmp_dir)
            workbook = excel_dir / "141_A891C.xlsx"
            workbook.write_bytes(b"")

            match = fix_events_format.find_matching_excel(
                "sub-141A891C_ses-77_task-MRAUT_run-1_events.tsv",
                excel_dir=excel_dir,
            )

            self.assertEqual(match, workbook)

    def test_fix_events_dataframe_enriches_item_rows(self):
        raw_df = pd.DataFrame(
            [
                {"onset": 0.0, "duration": 6.0, "event_type": "TextStim", "trial_type": "fixation", "response_time": "n/a"},
                {"onset": 6.0, "duration": 15.0, "event_type": "AUTitem Lampe", "trial_type": "AUTitem", "response_time": "n/a"},
                {"onset": 6.0, "duration": 15.0, "event_type": "Keyboard", "trial_type": "AUTidea_key", "response_time": "n/a"},
                {"onset": 21.0, "duration": 4.0, "event_type": "AUTresponse", "trial_type": "response2 Lampe", "response_time": "n/a"},
            ]
        )

        metadata_df = pd.DataFrame(
            {
                "AUT items": ["Lampe"],
                "AUT response": ["zum Wärmen"],
                "valid response": ["valid"],
                "AI rating": [2.4],
            }
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            workbook = Path(tmp_dir) / "141_A891C.xlsx"
            workbook.write_bytes(b"")

            with patch.object(fix_events_format.pd, "read_excel", return_value=metadata_df):
                matcher, workbook_path = fix_events_format.load_item_metadata_for_events(
                    "sub-141A891C_ses-77_task-MRAUT_run-1_events.tsv",
                    excel_dir=tmp_dir,
                )

            self.assertEqual(workbook_path, workbook)

            result = fix_events_format.fix_events_dataframe(raw_df, item_metadata=matcher)

            item_row = result[result["trial_type"] == "item"].iloc[0]
            response_row = result[result["trial_type"] == "verbal_response"].iloc[0]

            self.assertEqual(item_row["item"], "Lampe")
            self.assertEqual(item_row["aut_response"], "zum Wärmen")
            self.assertEqual(item_row["valid_response"], "valid")
            self.assertEqual(item_row["ai_rating"], "2.4")
            self.assertEqual(response_row["aut_response"], "n/a")
            self.assertEqual(response_row["valid_response"], "n/a")
            self.assertEqual(response_row["ai_rating"], "n/a")


if __name__ == "__main__":
    unittest.main()