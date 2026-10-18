"""The analysis page <-> transformer builder hand-off, end to end in headless Chromium.

analysis: openTransformerBuilder() stores a launch context in sessionStorage and navigates to the builder;
builder:  reads it (target level, task, node), builds a pipeline, Apply stores the payload in sessionStorage and
          navigates back;
analysis: openModelEditor() consumes the payload into the model draft, which can then be saved to disk.
Skips itself where Playwright or Chromium is not installed.
"""
import json
import tempfile
import unittest
from pathlib import Path

from tests.browser_support import chromium_available, make_dataset, start_server, sync_playwright

LAUNCH_KEY = "bidspm.transformerLaunchContext"
PENDING_KEY = "bidspm.pendingTransformerModel"


@unittest.skipUnless(chromium_available(), "Playwright + Chromium not available")
class TestTransformerHandoff(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        # a fresh project and model file per test: the round trip rewrites the model on disk
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        make_dataset(self.root)
        self.server, self.base, self.project_id = start_server(self.root)
        self.errors = []
        self.page = self.browser.new_page()
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.page.on("console", lambda m: self.errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)

    def tearDown(self):
        self.page.close()
        self.server.terminate()
        self.server.wait(timeout=10)
        self.tmp.cleanup()

    # ---- helpers -------------------------------------------------------
    def open_analysis_editor(self):
        page = self.page
        page.goto(f"{self.base}/analysis/{self.project_id}", wait_until="networkidle")
        page.evaluate("openModelEditor({scrollIntoView: false, showStatus: false})")
        page.wait_for_function("modelEditorDraft && modelEditorDraft.Nodes && modelEditorDraft.Nodes.length > 0")

    def go_to_builder(self, open_node=True):
        if open_node:  # the node's accordion panel is open when the user clicks "Transformer Builder"
            self.page.evaluate("modelEditorOpenPaths = new Set(['Nodes[0]'])")
        with self.page.expect_navigation():
            self.page.evaluate("openTransformerBuilder('Run')")
        self.page.wait_for_function("document.getElementById('scan-status').textContent.includes('Found 3 columns')",
                                    timeout=15000)

    def add_concatenate(self, output="cond_out"):
        page = self.page
        page.click('.btn-add-op[data-op="Concatenate"]')
        page.click("#op-1 .col-drop-zone")
        page.click(".col-picker-item >> text=trial_type")
        page.fill('#op-1 input[data-field="Output"]', output)

    # ---- tests ---------------------------------------------------------
    def test_launch_context_reaches_the_builder(self):
        self.open_analysis_editor()
        self.go_to_builder()
        self.assertTrue(self.page.url.endswith(f"/transformer-builder/{self.project_id}"), self.page.url)
        ctx = json.loads(self.page.evaluate(f"sessionStorage.getItem('{LAUNCH_KEY}')"))
        self.assertEqual(ctx["projectId"], self.project_id)
        self.assertTrue(ctx["modelPath"].endswith("model.json"))
        self.assertEqual((ctx["nodeLevel"], ctx["nodeIndex"], ctx["nodeName"]), ("Run", 0, "run"))
        self.assertEqual((ctx["taskFilter"], ctx["sourceScope"]), ("motor", "events"))
        self.assertEqual(ctx["modelSnapshot"]["Name"], "browser test model")
        # ... and the builder honours it
        self.assertEqual(self.page.input_value("#select-target-level"), "Run")
        self.assertEqual(self.page.input_value("#select-task"), "motor")
        self.assertTrue(self.page.input_value("#select-target-model").endswith("model.json"))
        self.assertEqual(self.page.inner_text("#launch-context-hint"),
                         "Preselected from active model: target level Run and task motor.")
        self.assertEqual(self.errors, [])

    def test_launch_without_an_open_node_has_no_node_but_keeps_level_and_task(self):
        self.open_analysis_editor()
        self.go_to_builder(open_node=False)
        ctx = json.loads(self.page.evaluate(f"sessionStorage.getItem('{LAUNCH_KEY}')"))
        self.assertEqual((ctx["nodeLevel"], ctx["nodeIndex"], ctx["nodeName"], ctx["taskFilter"]), ("Run", None, None, "motor"))

    def test_applied_pipeline_comes_back_into_the_model_and_can_be_saved(self):
        self.open_analysis_editor()
        self.go_to_builder()
        self.add_concatenate("cond_out")
        with self.page.expect_navigation():
            self.page.click("#btn-apply-model")
        self.assertTrue(f"/analysis/{self.project_id}" in self.page.url and "#analysis-model-workspace-section" in self.page.url,
                        self.page.url)
        self.page.wait_for_function(
            "modelEditorDraft && modelEditorDraft.Nodes && modelEditorDraft.Nodes[0].Transformations", timeout=15000)

        transformations = self.page.evaluate("modelEditorDraft.Nodes[0].Transformations")
        self.assertEqual(transformations["Transformer"], "bidspm")
        instruction = transformations["Instructions"][0]
        self.assertEqual((instruction["Name"], instruction["Input"], instruction["Output"]),
                         ("Concatenate", ["trial_type"], "cond_out"))
        # the payload and the launch context are consumed, not left behind for the next visit
        self.assertIsNone(self.page.evaluate(f"sessionStorage.getItem('{PENDING_KEY}')"))
        self.assertIsNone(self.page.evaluate(f"sessionStorage.getItem('{LAUNCH_KEY}')"))
        self.assertIn("transformer", self.page.inner_text("#model-editor-status").lower())

        # saving writes it into the model file on disk
        self.page.click("#btn-save-model-editor")
        self.page.wait_for_function(
            "document.getElementById('model-editor-status').innerText.toLowerCase().includes('saved')", timeout=10000)
        saved = json.loads((self.root / "model.json").read_text())
        self.assertEqual(saved["Nodes"][0]["Transformations"]["Instructions"][0]["Output"], "cond_out")
        self.assertEqual(self.errors, [])

    def test_apply_without_instructions_warns_and_stays_on_the_builder(self):
        self.open_analysis_editor()
        self.go_to_builder()
        self.page.click("#btn-apply-model")
        self.page.wait_for_function("document.getElementById('scan-status').textContent.includes('Add at least one')")
        self.assertIn("/transformer-builder/", self.page.url)
        self.assertIsNone(self.page.evaluate(f"sessionStorage.getItem('{PENDING_KEY}')"))

    def test_apply_with_an_operation_missing_its_input_names_the_field_and_stays(self):
        self.open_analysis_editor()
        self.go_to_builder()
        self.page.click('.btn-add-op[data-op="Filter"]')
        self.page.fill('#op-1 input[data-field="Query"]', "trial_type == 'a'")
        self.page.fill('#op-1 input[data-field="Output"]', "only_a")
        self.page.click("#btn-apply-model")
        self.page.wait_for_function("document.getElementById('scan-status').textContent.includes('Input')")
        self.assertIn("Op 1 (Filter)", self.page.inner_text("#scan-status"))
        self.assertIn("/transformer-builder/", self.page.url)
        self.assertIsNone(self.page.evaluate(f"sessionStorage.getItem('{PENDING_KEY}')"))

    def test_apply_with_a_threshold_without_bounds_is_refused_not_dropped(self):
        self.open_analysis_editor()
        self.go_to_builder()
        self.page.click('.btn-add-op[data-op="Threshold"]')
        self.page.click("#op-1 .col-drop-zone")
        self.page.click(".col-picker-item >> text=trial_type")
        self.page.fill('#op-1 input[data-field="Output"]', "limited")
        self.page.click("#btn-apply-model")
        self.page.wait_for_function("document.getElementById('scan-status').textContent.includes('threshold')")
        self.assertIn("/transformer-builder/", self.page.url)
        self.assertIsNone(self.page.evaluate(f"sessionStorage.getItem('{PENDING_KEY}')"))

    def test_apply_with_a_missing_output_name_warns_and_stays(self):
        self.open_analysis_editor()
        self.go_to_builder()
        self.add_concatenate(output="")
        self.page.click("#btn-apply-model")
        self.page.wait_for_function("document.getElementById('scan-status').textContent.includes('Output name')")
        self.assertIn("/transformer-builder/", self.page.url)
        self.assertIsNone(self.page.evaluate(f"sessionStorage.getItem('{PENDING_KEY}')"))


if __name__ == "__main__":
    unittest.main()
