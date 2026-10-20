"""Script-execution regressions (exploratory findings F1-F5): text that comes from the dataset (file and folder names,
participants.tsv), from the model JSON or from typed values must show up LITERALLY in the page and never run.

Every test feeds the payloads through the real page from the real source and asserts that nothing executed
(`window.__xss` unset, no dialog) and that the visible text equals the payload.
"""
import json
import tempfile
import unittest
from pathlib import Path

from tests.browser_support import (MODEL, chromium_available, go_to_stage, post_json, start_server, sync_playwright)

IMG = '<img src=x onerror="window.__xss=1">'
SVG = '"><svg onload=window.__xss=1>'
SVG2 = "<svg onload=window.__xss=1>"  # no quote: a '"' in a TSV header trips the csv module (separate finding)
ODD = 'a"b\'c&amp;dé'
TASK = "<img src=x onerror=alert(1)>"  # a task label cannot carry '_' (BIDS entity separator), so alert() instead
SUBJECTS = [IMG, ODD]  # sub-<this> folders


def hostile_model():
    node = {"Level": "Run", "Name": IMG, "GroupBy": ["run", "subject"],
            "Model": {"X": ["trial_type.a", f"trial_type.{IMG}", SVG, 1], "Type": "glm",
                      "HRF": {"Variables": ["trial_type.a"], "Model": "spm"}},
            "Contrasts": [{"Name": SVG, "ConditionList": [f"trial_type.{IMG}"], "Weights": [1], "Test": "t"}]}
    dataset = {"Level": "Dataset", "Name": "dataset", "GroupBy": ["contrast"], "Model": {"X": [1], "Type": "glm"},
               "DummyContrasts": {"Test": "t"}}
    return dict(MODEL, Name=IMG, Description=SVG, Nodes=[node, dataset])


@unittest.skipUnless(chromium_available(), "Playwright + Chromium not available")
class TestHostileTextIsInert(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        bids = tmp / "bids"
        func = bids / "sub-01" / "func"
        func.mkdir(parents=True)
        (bids / "dataset_description.json").write_text(json.dumps({"Name": "t", "BIDSVersion": "1.9.0"}))
        (func / f"sub-01_task-{TASK}_bold.nii.gz").write_bytes(b"")
        (func / f"sub-01_task-{TASK}_events.tsv").write_text("onset\tduration\ttrial_type\n1\t1\ta\n")
        (func / "sub-01_task-motor_events.tsv").write_text(f"onset\tduration\ttrial_type\t{IMG}\n1\t1\t{SVG}\tq\n")
        for name in SUBJECTS:
            (bids / f"sub-{name}" / "func").mkdir(parents=True)
        (bids / "participants.tsv").write_text(
            f"participant_id\t{IMG}\t{SVG2}\nsub-01\tq\t3\nsub-02\tr\t4\n")
        (tmp / "fmriprep").mkdir()
        (tmp / "derivs").mkdir()
        cls.browse = tmp / "browse"
        for name in (IMG, SVG, ODD):
            (cls.browse / name).mkdir(parents=True)
        (cls.browse / f"{IMG}.json").write_text("{}")
        (tmp / "model.json").write_text(json.dumps(hostile_model()))
        cls.server, cls.base, _ = start_server(tmp)
        cls.pid = post_json(cls.base + "/api/projects", {"name": IMG, "description": SVG, "config": {
            "bids_folder": str(bids), "fmriprep_folder": str(tmp / "fmriprep"), "derivatives_folder": str(tmp / "derivs"),
            "models_file": str(tmp / "model.json"), "tasks": []}})["project"]["id"]
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.tmp.cleanup()

    def setUp(self):
        self.pages, self.dialogs = [], []

    def tearDown(self):
        for p in self.pages:
            p.close()

    def open(self, url):
        page = self.browser.new_page()
        self.pages.append(page)
        page.on("dialog", lambda d: (self.dialogs.append(d.message), d.dismiss()))
        page.goto(self.base + url, wait_until="load")
        return page

    def assert_inert(self, page):
        page.wait_for_timeout(300)  # an onerror handler fires asynchronously after the failed image load
        self.assertEqual(self.dialogs, [])
        self.assertIsNone(page.evaluate("window.__xss"))

    def texts(self, page, selector):
        return page.eval_on_selector_all(selector, "els => els.map(e => e.textContent.trim())")

    def test_task_names_from_bids_file_names(self):
        page = self.open(f"/analysis/{self.pid}")
        page.wait_for_selector("#tasks-container .task-checkbox")
        self.assertEqual(sorted(self.texts(page, "#tasks-container label")), sorted([TASK, "motor"]))
        self.assertIn(TASK, page.eval_on_selector_all(".task-checkbox", "els => els.map(e => e.value)"))
        self.assert_inert(page)

    def test_folder_and_file_names_in_the_analysis_browse_modal(self):
        page = self.open(f"/analysis/{self.pid}")
        go_to_stage(page, "folders")
        page.fill("#input-BIDS_DIR", str(self.browse))
        page.click(".btn-browse[data-key=BIDS_DIR]")
        page.wait_for_selector("#browse-list button")
        self.assertEqual(sorted(self.texts(page, "#browse-list button")), sorted(["..", IMG, SVG, ODD]))
        self.assert_inert(page)

    def test_hostile_folder_in_the_analysis_browse_breadcrumb(self):
        page = self.open(f"/analysis/{self.pid}")
        go_to_stage(page, "folders")
        page.fill("#input-BIDS_DIR", str(self.browse / IMG))
        page.click(".btn-browse[data-key=BIDS_DIR]")
        page.wait_for_selector("#browse-list")
        page.wait_for_function("document.getElementById('selected-browse-path').innerText.endsWith('onerror=\"window.__xss=1\">')")
        self.assertEqual(self.texts(page, "#browse-breadcrumb li")[-1], IMG)
        self.assert_inert(page)

    def test_folder_names_in_the_projects_page_browsers(self):
        page = self.open("/projects")
        page.click("#btn-new-project")
        page.fill("#project-bids-folder", str(self.browse / IMG))
        page.click(".folder-browse-btn[data-target=project-bids-folder]")
        page.wait_for_function("document.getElementById('folder-selected-path').textContent.endsWith('onerror=\"window.__xss=1\">')")
        self.assertEqual(self.texts(page, "#folder-browse-breadcrumb li")[-1], IMG)
        page.click("#folderBrowserModal .btn-secondary[data-bs-dismiss=modal]")  # the open dialog blocks the page behind it
        page.wait_for_selector("#folderBrowserModal", state="hidden")
        page.fill("#project-bids-folder", str(self.browse))
        page.click(".folder-browse-btn[data-target=project-bids-folder]")
        page.wait_for_function("document.querySelectorAll('#folder-browse-list > a').length > 3")
        self.assertEqual(sorted(self.texts(page, "#folder-browse-list > a")), sorted(["..", IMG, SVG, ODD]))
        self.assert_inert(page)

    def test_names_in_the_projects_page_import_browser(self):
        page = self.open("/projects")
        page.click("#btn-import-config")
        for part in self.browse.parts[1:]:
            page.locator("#import-browse-list > a", has_text=part).first.click()
            page.wait_for_function("p => document.getElementById('import-browse-breadcrumb').lastElementChild.textContent === p", arg=part)
        self.assertEqual(sorted(self.texts(page, "#import-browse-list > a")), sorted(["..", IMG, SVG, ODD, f"{IMG}.json"]))
        page.locator("#import-browse-list > a", has_text=ODD).click()
        page.wait_for_function("p => document.getElementById('import-browse-breadcrumb').lastElementChild.textContent === p", arg=ODD)
        self.assert_inert(page)

    def test_subject_folders_in_the_participants_modal_round_trip_their_id(self):
        page = self.open(f"/analysis/{self.pid}")
        go_to_stage(page, "options")
        page.click("#btn-select-participants")
        page.wait_for_selector(".participant-checkbox")
        self.assertEqual(sorted(self.texts(page, "#participantsModal .participant-checkbox + label")),
                         sorted(f"sub-{n}" for n in SUBJECTS + ["01"]))
        self.assertEqual(sorted(page.eval_on_selector_all(".participant-checkbox", "els => els.map(e => e.value)")),
                         sorted(SUBJECTS + ["01"]))
        # the id survives selecting: unticking everything but the quoted one yields exactly that id
        page.evaluate("""odd => document.querySelectorAll('.participant-checkbox').forEach(c => { c.checked = c.value === odd; })""", ODD)
        page.click("#participants-run-selected")
        page.wait_for_function("document.getElementById('participants-summary').textContent.trim() !== 'All participants'")
        self.assertEqual(page.evaluate("Array.from(selectedParticipants)"), [ODD])
        self.assert_inert(page)

    def test_participants_tsv_columns_in_the_dataset_node_panel(self):
        page = self.open(f"/analysis/{self.pid}")
        go_to_stage(page, "model")
        page.wait_for_function("modelEditorParticipantsInfo.columns.length > 0")
        page.evaluate("renderModelAccordionEditor()")
        text = page.evaluate("Array.from(document.querySelectorAll('div.small')).map(e => e.textContent).filter(t => t.startsWith('Categorical:') || t.startsWith('Numeric:')).join('|')")
        self.assertIn(IMG, text)
        self.assertIn(SVG2, text)
        self.assert_inert(page)

    def test_model_entries_in_editor_chips_and_status_messages(self):
        page = self.open(f"/analysis/{self.pid}")
        go_to_stage(page, "model")
        page.evaluate("openModelEditor({scrollIntoView: false, showStatus: false})")
        page.wait_for_function("document.querySelectorAll('#model-editor-accordion > *').length > 0")
        status = lambda: page.inner_text("#model-editor-status")
        page.evaluate("toggleModelXRegressorHrf('Nodes[0].Model.X[2]')")
        self.assertIn("HRF on for " + SVG, status())
        page.evaluate("toggleModelXRegressorHrf('Nodes[0].Model.X[2]')")
        self.assertIn("HRF off for " + SVG, status())
        page.evaluate("IMG => setModelEditorStatus(`Node renamed to \"${IMG}\".`, 'info')", IMG)
        self.assertIn(f'Node renamed to "{IMG}".', page.inner_text("#model-editor-status"))
        page.evaluate("SVG => addRegressorToModelX('Nodes[0].Model.X', SVG)", SVG)
        self.assertIn("Regressor already selected: " + SVG, status())
        self.assert_inert(page)

    def test_conditions_in_the_contrast_builder_and_its_status(self):
        page = self.open(f"/analysis/{self.pid}")
        go_to_stage(page, "model")
        page.wait_for_function("typeof modelEditorDraft === 'object' && modelEditorDraft !== null")
        page.click("#btn-open-contrast-builder")
        page.wait_for_selector("#cb-condition-pool .cb-condition-chip")
        page.fill("#cb-custom-condition", f"trial_type.{IMG}")
        page.click("#cb-add-custom-btn")
        chips = self.texts(page, "#cb-condition-pool .cb-condition-chip")
        self.assertTrue(any(IMG in c for c in chips), chips)
        self.assert_inert(page)

    def test_model_hints_panel_shows_server_text_literally(self):
        page = self.open(f"/analysis/{self.pid}")
        page.wait_for_function("window.BidspmAnalysisModelHints !== undefined")
        text = page.evaluate("""async ([img, svg]) => {
            const out = [];
            for (const reply of [
                {dataset: {bids_tasks: [img], events: {event_columns: [img], sample_values: {trial_type: [svg]}}}, warnings: [img]},
                {error: svg}]) {
                const panel = document.createElement('div');
                document.body.appendChild(panel);
                await window.BidspmAnalysisModelHints.refreshModelHints({
                    panel, modelPath: 'm.json', bidsDir: '/b',
                    getModelContentFromPath: async () => ({Input: {task: [img]}, Nodes: []}),
                    fetchImpl: async () => ({json: async () => reply})});
                out.push(panel.textContent);
            }
            return out.join('|');
        }""", [IMG, SVG])
        self.assertEqual(text.count(IMG), 4)  # task, event column, warning, model task
        self.assertEqual(text.count(SVG), 2)  # sample value, error
        self.assert_inert(page)

    def test_run_issues_from_the_log_stream_are_text(self):
        page = self.open(f"/analysis/{self.pid}")
        page.evaluate("""img => {
            runIssues = [{level: 'error', subject: img, message: img}];
            renderRunIssues();
        }""", IMG)
        self.assertEqual(" ".join(self.texts(page, "#run-issues-list")[0].split()), f"error sub-{IMG} \u2014 {IMG}")
        self.assert_inert(page)


if __name__ == "__main__":
    unittest.main()
