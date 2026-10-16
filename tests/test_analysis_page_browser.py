"""Real-browser safety net for templates/analysis.html and the scripts it loads.

Opens the page in headless Chromium against the real server, so moving code between the template and
static/js files cannot silently break load order, globals or the model editor. Skips itself where
Playwright or its Chromium is not installed (pip install playwright && playwright install chromium).
"""
import unittest
import tempfile
from pathlib import Path

from tests.browser_support import (chromium_available, go_to_stage, make_dataset, start_server, sync_playwright)

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
    "validatorMode", "renderPreflight", "runPreflight", "resetRunIssues", "renderRunIssues", "processRunLogLine", "parseFailedSubjects", "startExecution", "resetStatus",
]

@unittest.skipUnless(chromium_available(), "Playwright + Chromium not available")
class TestAnalysisPageInBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        make_dataset(Path(cls.tmp.name))
        cls.server, cls.base, cls.project_id = start_server(Path(cls.tmp.name))
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
        go_to_stage(page, "options")
        page.click("#options-advanced > summary")  # container settings sit in the Advanced block
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
        go_to_stage(page, "run")
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

    def test_path_equivalence_helpers(self):
        page = self.open_page()
        cases = [("/a/b/model.json", "/a/b/model.json", True), ("/a/b/../b/model.json", "/a/b/model.json", True),
                 ("model.json", "/a/b/model.json", True), ("/a/b/model.json?x=1#h", "/a/b/model.json", True),
                 ("/a/b%20c/m.json", "/a/b c/m.json", True), ("/a/b/model.json", "/a/c/model.json", False),
                 ("", "/a/b/model.json", False)]
        got = page.evaluate("cs => cs.map(([a, b]) => areModelPathsEquivalent(a, b))", cases)
        self.assertEqual(got, [c[2] for c in cases])
        self.assertEqual(self.errors, [])

    def test_dataset_presets_name_the_node_exactly_dataset(self):
        # bidspm looks the Dataset node up by exact name; a second one is suffixed (and warned about)
        page = self.open_page()
        got = page.evaluate("""() => {
            const mk = (nodes) => window.BidspmAnalysisModelPresets.createModelHelperApi({getModelDraft: () => ({Nodes: nodes})});
            return [mk([]).buildNodeFromPreset('dataset_basic').node.Name,
                    mk([]).buildNodeFromPreset('one_sample_all').node.Name,
                    mk([{Name: 'dataset'}]).buildNodeFromPreset('dataset_basic').node.Name];
        }""")
        self.assertEqual(got, ["dataset", "dataset", "dataset_2"])
        self.assertEqual(self.errors, [])

    def test_transformer_launch_node_inference(self):
        page = self.open_page()
        page.evaluate("openModelEditor({scrollIntoView: false, showStatus: false})")
        page.wait_for_function("modelEditorDraft && modelEditorDraft.Nodes && modelEditorDraft.Nodes.length > 0")
        got = page.evaluate("""() => {
            const out = {};
            modelEditorOpenPaths = new Set(); modelEditorPendingOpenPaths = new Set();
            out.none = [inferTransformerLaunchNodeLevel(), inferTransformerLaunchNodeIndex()];
            modelEditorOpenPaths = new Set(['Nodes[0].Model']);
            out.open = [inferTransformerLaunchNodeLevel(), inferTransformerLaunchNodeIndex()];
            modelEditorPendingOpenPaths = new Set(['Nodes[0]']);
            out.pending = [inferTransformerLaunchNodeLevel(), inferTransformerLaunchNodeIndex()];
            return out;
        }""")
        self.assertEqual(got["open"], ["Run", 0])
        self.assertEqual(got["pending"], ["Run", 0])
        self.assertEqual(got["none"][0], "")
        self.assertEqual(self.errors, [])

    def test_event_hints_reset_when_there_is_no_bids_folder(self):
        page = self.open_page()
        got = page.evaluate("""async () => {
            modelEditorEventColumns = ['x']; modelEditorConfoundColumns = ['y']; modelEditorInterestRegressors = ['z'];
            document.getElementById('input-BIDS_DIR').value = '';
            const ret = await loadInterestRegressorsForModelEditor({});
            return [ret, modelEditorEventColumns, modelEditorConfoundColumns, modelEditorInterestRegressors,
                    modelEditorEventSamples, modelEditorParticipantsInfo.columns];
        }""")
        self.assertEqual(got, [[], [], [], [], {"trial_type": [], "condition": []}, []])
        self.assertEqual(self.errors, [])

    def test_path_browser_modal_navigates_and_selects(self):
        page = self.open_page()
        bids = str(Path(self.tmp.name) / "bids")
        # folder mode (working directory)
        go_to_stage(page, "folders")
        page.fill("#input-WD", bids)
        page.click('.btn-browse[data-key="WD"]')
        page.wait_for_selector("#browseModal.show")
        page.wait_for_function("document.querySelectorAll('#browse-list > *').length > 0")
        crumbs = page.eval_on_selector_all("#browse-breadcrumb li", "els => els.map(e => e.textContent.trim())")
        self.assertEqual(crumbs, ["Root"] + list(Path(bids).parts[1:]))
        self.assertTrue(page.eval_on_selector("#browse-breadcrumb li", "e => e.classList.contains('x-small')"))
        page.click("#browse-list >> text=sub-01")
        page.wait_for_function("document.getElementById('selected-browse-path').innerText.endsWith('sub-01')")
        self.assertEqual(page.eval_on_selector("#browse-breadcrumb li:last-child", "e => e.classList.contains('active')"), True)
        page.click("#browse-breadcrumb >> text=bids")
        page.wait_for_function("document.getElementById('selected-browse-path').innerText.endsWith('/bids')")
        page.click("#btn-confirm-browse")
        page.wait_for_selector("#browseModal", state="hidden")
        self.assertEqual(page.input_value("#input-WD"), bids)
        # file mode (models file): files are listed and clicking one selects it
        go_to_stage(page, "model")
        page.click('.btn-browse[data-key="MODELS_FILE"]')
        page.wait_for_selector("#browseModal.show")
        page.wait_for_function("document.querySelectorAll('#browse-list > *').length > 0")
        page.click("#browse-list >> text=model.json")
        page.wait_for_selector("#browseModal", state="hidden")
        self.assertTrue(page.input_value("#input-MODELS_FILE").endswith("model.json"))
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
