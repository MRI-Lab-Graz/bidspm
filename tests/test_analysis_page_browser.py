"""Real-browser safety net for templates/analysis.html and the scripts it loads.

Opens the page in headless Chromium against the real server, so moving code between the template and
static/js files cannot silently break load order, globals or the model editor. Skips itself where
Playwright or its Chromium is not installed (pip install playwright && playwright install chromium).
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # optional dependency
    sync_playwright = None

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every function the page defines globally; the refactor must keep each one reachable from window.
GLOBAL_FUNCTIONS = [
    "revealResult", "createAdvancedFieldsBadge", "getBranchBadgeDescriptors", "createModelTaskPicker",
    "createModelSessionRunPicker", "createInlineNote", "getModelEditorParticipantsInfo", "setModelEditorStatus",
    "renderModelSectionContent", "createModelSectionCard", "pruneEdgesForCurrentNodes", "removeArrayItem",
    "loadBidsTasksForModelEditor", "loadInterestRegressorsForModelEditor", "loadGroupByOptionsForModelEditor",
    "getFullFormData", "setFullFormData", "initApp", "loadProjectConfig", "saveProjectConfig",
    "setupStaticListeners", "updateInternalState", "syncInternalToForm", "refreshTasks", "getModelContentFromPath",
    "validateModel", "createNewModel", "openModelEditor", "inferTransformerLaunchNodeLevel",
    "inferTransformerLaunchNodeIndex", "persistTransformerLaunchContext", "openTransformerBuilder",
    "saveModelEditor", "refreshModelTasks", "refreshSpaces", "loadLatestStudy", "normalizeSubjectLabel",
    "resetRunIssues", "renderRunIssues", "processRunLogLine", "parseFailedSubjects", "startExecution", "resetStatus",
]

MODEL = {
    "Name": "browser test model", "BIDSModelVersion": "1.0.0", "Description": "",
    "Input": {"task": ["motor"]},
    "Nodes": [{
        "Level": "Run", "Name": "run", "GroupBy": ["run", "subject"],
        "Model": {"X": ["trial_type.a", "trial_type.b", 1], "Type": "glm",
                  "HRF": {"Variables": ["trial_type.a", "trial_type.b"], "Model": "spm"}},
        "DummyContrasts": {"Test": "t"},
    }],
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def _chromium_available() -> bool:
    if sync_playwright is None:
        return False
    try:
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


@unittest.skipUnless(_chromium_available(), "Playwright + Chromium not available")
class TestAnalysisPageInBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        (tmp / "model.json").write_text(json.dumps(MODEL))
        (tmp / "derivs").mkdir()
        func = tmp / "bids" / "sub-01" / "func"
        func.mkdir(parents=True)
        (tmp / "bids" / "dataset_description.json").write_text(json.dumps({"Name": "t", "BIDSVersion": "1.9.0"}))
        (func / "sub-01_task-motor_events.tsv").write_text("onset\tduration\ttrial_type\n1\t1\ta\n5\t1\tb\n")
        port = _free_port()
        cls.base = f"http://127.0.0.1:{port}"
        env = dict(os.environ, HOME=str(tmp / "home"))
        cls.server = subprocess.Popen(
            [sys.executable, "bidspm_gui.py", "--no-browser", "-p", str(port)], cwd=str(REPO_ROOT), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.base + "/", timeout=1)
                break
            except Exception:
                time.sleep(0.3)
        cls.project_id = _post(cls.base + "/api/projects", {"name": "browser", "config": {
            "bids_folder": str(tmp / "bids"), "derivatives_folder": str(tmp / "derivs"),
            "models_file": str(tmp / "model.json"), "tasks": ["motor"]}})["project"]["id"]
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.tmp.cleanup()

    def open_page(self):
        page = self.browser.new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: self.errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
        page.goto(f"{self.base}/analysis/{self.project_id}", wait_until="networkidle")
        page.wait_for_timeout(500)
        return page

    def test_loads_without_script_errors(self):
        self.open_page()
        self.assertEqual(self.errors, [])

    def test_every_global_function_is_still_defined(self):
        page = self.open_page()
        missing = page.evaluate("names => names.filter(n => typeof window[n] !== 'function')", GLOBAL_FUNCTIONS)
        self.assertEqual(missing, [])

    def test_model_editor_renders_the_model(self):
        page = self.open_page()
        page.evaluate("openModelEditor({scrollIntoView: false, showStatus: false})")
        page.wait_for_function("document.querySelectorAll('#model-editor-accordion > *').length > 0", timeout=10000)
        self.assertEqual(self.errors, [])
        self.assertEqual(page.evaluate("modelEditorDraft && modelEditorDraft.Name"), "browser test model")
        self.assertIn("browser test model", page.inner_text("#model-json-preview"))

    def test_form_round_trips_and_controls_work(self):
        page = self.open_page()
        page.select_option("#estimation_engine", "standalone")
        page.check("#run_results")
        page.click("#suggest_workers")
        page.wait_for_function("document.getElementById('suggest_workers_hint').textContent.length > 0")
        data = page.evaluate("getFullFormData()")
        self.assertEqual(data["estimation_engine"], "standalone")
        self.assertTrue(data["run_results"])
        self.assertGreaterEqual(data["stats_workers"], 1)
        again = page.evaluate("async d => { await setFullFormData(d); return getFullFormData(); }", data)
        self.assertEqual(again, data)
        self.assertEqual(self.errors, [])

    def test_toolbar_buttons_are_wired(self):
        page = self.open_page()
        # onclick handlers exist for every toolbar button (they are attached at load by analysis_buttons.js)
        wired = page.evaluate(
            "ids => ids.filter(id => typeof document.getElementById(id).onclick !== 'function')",
            ["btn-validate", "btn-check-paths", "btn-save-only", "btn-save-start", "btn-run-cached", "btn-stop"])
        self.assertEqual(wired, [])
        # and they act: validating the config shows a result
        page.click("#btn-validate")
        page.wait_for_function("document.getElementById('validation-result').innerText.trim().length > 0 "
                               "&& !document.getElementById('validation-result').innerText.includes('Validating')",
                               timeout=10000)
        # with a project open, "Load config" points the user to the Projects page (an alert)
        messages = []
        page.once("dialog", lambda d: (messages.append(d.message), d.dismiss()))
        page.click("#btn-load-config")
        self.assertTrue(messages and "Projects page" in messages[0], messages)
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
