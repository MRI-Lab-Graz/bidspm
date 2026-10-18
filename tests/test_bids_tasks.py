"""/get_bids_tasks: same task list as before for valid BIDS, without walking the whole tree; fetched once per page load."""
import tempfile
import unittest
from pathlib import Path

from bidspm_gui import app
from lib.core import discover_tasks
from tests.browser_support import (chromium_available, make_dataset, post_json, start_server, sync_playwright)


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")


def make_tree(root):
    touch(root / "sub-01" / "func" / "sub-01_task-motor_bold.nii.gz")
    touch(root / "sub-01" / "func" / "sub-01_task-motor_events.tsv")
    touch(root / "sub-02" / "ses-1" / "func" / "sub-02_ses-1_task-rest_run-1_bold.nii.gz")
    touch(root / "sub-02" / "ses-1" / "func" / "sub-02_ses-1_desc-task-xy_bold.json")  # decoy: not a task entity
    touch(root / "sub-02" / "anat" / "sub-02_task-anatdecoy_T1w.nii.gz")  # not a func folder
    touch(root / "derivatives" / "fmriprep" / "sub-01" / "func" / "sub-01_task-deriv_bold.nii.gz")
    touch(root / "sourcedata" / "sub-01" / "func" / "sub-01_task-raw_bold.nii.gz")
    touch(root / "task-motor_events.tsv")


class TestBidsTasks(unittest.TestCase):
    def test_lists_tasks_of_func_folders_with_sessions_and_skips_decoys_and_derivatives(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_tree(Path(tmp))
            expected = ["motor", "rest"]
            self.assertEqual(discover_tasks(Path(tmp)), expected)
            self.assertEqual(app.test_client().get("/get_bids_tasks", query_string={"path": tmp}).get_json(), expected)

    def test_unknown_folder_is_an_empty_list(self):
        self.assertEqual(app.test_client().get("/get_bids_tasks", query_string={"path": "/no/such/dir"}).get_json(), [])


@unittest.skipUnless(chromium_available(), "Playwright + Chromium not available")
class TestBidsTasksFetchedOnce(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        make_dataset(tmp)
        (tmp / "wd").mkdir()
        (tmp / "fmriprep").mkdir()
        cls.server, cls.base, _ = start_server(tmp)
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.tmp.cleanup()

    def test_analysis_page_requests_the_task_list_once_per_bids_folder(self):
        tmp = Path(self.tmp.name)
        pid = post_json(self.base + "/api/projects", {"name": "once", "config": {
            "output_folder": str(tmp / "wd"), "bids_folder": str(tmp / "bids"), "derivatives_folder": str(tmp / "derivs"),
            "fmriprep_folder": str(tmp / "fmriprep"), "models_file": str(tmp / "model.json"), "tasks": ["motor"],
            "space": "MNI152NLin2009cAsym", "fwhm": 6, "actions": ["smooth", "stats"]}})["project"]["id"]
        page = self.browser.new_page()
        try:
            urls = []
            page.on("request", lambda r: urls.append(r.url) if "/get_bids_tasks" in r.url else None)
            page.goto(f"{self.base}/analysis/{pid}", wait_until="load")
            page.wait_for_function("window.analysisStages !== undefined")
            # both consumers have run once the model editor was rendered from the saved model and the task is ticked
            page.wait_for_function("document.querySelector('#task-motor') && modelEditorBidsTasks.length > 0")
            self.assertEqual(len(urls), 1, urls)
        finally:
            page.close()
