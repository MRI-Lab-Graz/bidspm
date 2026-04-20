import tempfile
import unittest
from pathlib import Path

from bidspm_gui import app as flask_app


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


class TestNewFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app.config.update(TESTING=True)
        cls.client = flask_app.test_client()

    def test_model_editor_page_renders(self):
        response = self.client.get("/model_editor", query_string={"path": "studies/model.json"})

        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn("Model Editor", text)
        self.assertIn("studies/model.json", text)

    def test_api_bids_entities_missing_path_returns_defaults(self):
        response = self.client.get("/api/bids_entities", query_string={"path": "/path/that/does/not/exist"})

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["entities"], [])
        self.assertEqual(payload["groupby_options"], ["subject"])
        self.assertEqual(payload["values"], {"task": [], "run": [], "session": [], "subject": []})

    def test_api_bids_entities_extracts_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            bids_dir = Path(tmp_dir) / "bids"
            sample_file = (
                bids_dir
                / "sub-01"
                / "ses-01"
                / "func"
                / "sub-01_ses-01_task-motor_run-02_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
            )
            _touch(sample_file)

            response = self.client.get("/api/bids_entities", query_string={"path": str(bids_dir)})

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            values = payload["values"]

            self.assertIn("task", payload["entities"])
            self.assertEqual(values["task"], ["motor"])
            self.assertEqual(values["run"], ["02"])
            self.assertEqual(values["session"], ["01"])
            self.assertEqual(values["subject"], ["01"])
            self.assertIn("func", values["datatype"])
            self.assertIn("bold", values["suffix"])
            self.assertIn(".nii.gz", values["extension"])
            self.assertIn("MNI152NLin2009cAsym", values["space"])
            self.assertEqual(payload["groupby_options"], ["subject", "run", "session", "task"])

    def test_get_fmriprep_spaces_filters_by_task(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            fmriprep_dir = Path(tmp_dir) / "fmriprep"

            motor_file = (
                fmriprep_dir
                / "sub-01"
                / "func"
                / "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
            )
            rest_file = (
                fmriprep_dir
                / "sub-01"
                / "func"
                / "sub-01_task-rest_space-T1w_desc-preproc_bold.nii.gz"
            )
            _touch(motor_file)
            _touch(rest_file)

            all_spaces = self.client.get("/get_fmriprep_spaces", query_string={"path": str(fmriprep_dir)})
            motor_spaces = self.client.get(
                "/get_fmriprep_spaces",
                query_string=[("path", str(fmriprep_dir)), ("tasks", "motor")],
            )

            self.assertEqual(all_spaces.status_code, 200)
            self.assertEqual(all_spaces.get_json(), ["MNI152NLin2009cAsym", "T1w"])

            self.assertEqual(motor_spaces.status_code, 200)
            self.assertEqual(motor_spaces.get_json(), ["MNI152NLin2009cAsym"])


if __name__ == "__main__":
    unittest.main()
