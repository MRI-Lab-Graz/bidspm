"""Real-browser safety net for the transformer builder page (templates/transformer_builder.html).

Drives the BIDS-folder and events-file browser modals against the real server, because their code
(static/js/transformer_builder_browser.js) is the part most likely to be refactored. Skips itself where
Playwright or Chromium is not installed.
"""
import tempfile
import unittest
from pathlib import Path

from tests.browser_support import chromium_available, make_dataset, start_server, sync_playwright


@unittest.skipUnless(chromium_available(), "Playwright + Chromium not available")
class TestTransformerBuilderBrowsers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        make_dataset(cls.root)
        cls.bids = str(cls.root / "bids")
        cls.server, cls.base, cls.project_id = start_server(cls.root)
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
        page.goto(f"{self.base}/transformer-builder/{self.project_id}", wait_until="networkidle")
        page.wait_for_timeout(300)
        return page

    # ---- helpers -------------------------------------------------------
    @staticmethod
    def crumbs(page, prefix):
        return page.eval_on_selector_all(f"#{prefix}-breadcrumb li", "els => els.map(e => e.textContent.trim())")

    @staticmethod
    def entries(page, prefix):
        return page.eval_on_selector_all(f"#{prefix}-browse-list > *", "els => els.map(e => e.textContent.trim())")

    def open_bids(self, page):
        page.fill("#input-bids-dir", self.bids)
        page.click("#btn-browse-bids")
        page.wait_for_selector("#tb-browse-modal.show")
        page.wait_for_function("document.querySelectorAll('#tb-browse-list > *').length > 0")

    def open_events(self, page):
        page.fill("#input-bids-dir", self.bids)
        page.fill("#input-events-file", "")
        page.click("#btn-browse-events")
        page.wait_for_selector("#ev-browse-modal.show")
        page.wait_for_function("document.querySelectorAll('#ev-browse-list > *').length > 0")

    # ---- tests ---------------------------------------------------------
    def test_loads_without_script_errors(self):
        self.open_page()
        self.assertEqual(self.errors, [])

    def test_bids_browser_lists_navigates_and_selects_a_folder(self):
        page = self.open_page()
        self.open_bids(page)
        parts = Path(self.bids).parts[1:]
        self.assertEqual(self.crumbs(page, "tb"), ["Root"] + list(parts))
        self.assertEqual(page.inner_text("#tb-selected-path"), self.bids)
        self.assertEqual(sorted(self.entries(page, "tb")), ["..", "sub-01", "sub-02"])  # directories only, no files

        page.click("#tb-browse-list >> text=sub-01")
        page.wait_for_function("document.getElementById('tb-selected-path').textContent.endsWith('sub-01')")
        self.assertEqual(self.crumbs(page, "tb")[-1], "sub-01")
        self.assertEqual(sorted(self.entries(page, "tb")), ["..", "func"])
        # the last crumb is the current folder and is not a link; earlier ones navigate
        self.assertEqual(page.eval_on_selector("#tb-breadcrumb li:last-child", "e => e.classList.contains('active')"), True)
        page.click("#tb-breadcrumb >> text=bids")
        page.wait_for_function("document.getElementById('tb-selected-path').textContent.endsWith('/bids')")
        page.click("#tb-breadcrumb >> text=Root")
        page.wait_for_function("document.getElementById('tb-selected-path').textContent === '/'")

        page.click("#btn-tb-browse-select")
        page.wait_for_selector("#tb-browse-modal", state="hidden")
        self.assertEqual(page.input_value("#input-bids-dir"), "/")  # 'Use This Folder' takes the folder being shown
        self.assertEqual(self.errors, [])

    def test_bids_browser_shows_server_errors_in_the_list(self):
        page = self.open_page()
        page.route("**/browse?*", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"error": "Permission denied: /secret"}'))
        page.click("#btn-browse-bids")
        page.wait_for_selector("#tb-browse-modal.show")
        page.wait_for_selector("#tb-browse-list .alert-danger")
        self.assertIn("Permission denied: /secret", page.inner_text("#tb-browse-list"))
        self.assertEqual(self.errors, [])

    def test_events_browser_shows_server_errors_in_the_list(self):
        page = self.open_page()
        page.route("**/browse?*", lambda route: route.fulfill(
            status=200, content_type="application/json", body='{"error": "Permission denied: /secret"}'))
        page.click("#btn-browse-events")
        page.wait_for_selector("#ev-browse-modal.show")
        page.wait_for_selector("#ev-browse-list .alert-danger")
        self.assertIn("Permission denied: /secret", page.inner_text("#ev-browse-list"))
        self.assertEqual(self.errors, [])

    def test_events_browser_requires_a_selection_then_selects_a_file(self):
        page = self.open_page()
        self.open_events(page)
        self.assertEqual(page.inner_text("#ev-selected-path"), "No file selected")
        page.click("#btn-ev-browse-select")  # nothing chosen yet
        self.assertEqual(page.inner_text("#ev-selected-path"), "Select an events.tsv file first")
        self.assertTrue(page.eval_on_selector("#ev-selected-path", "e => e.classList.contains('text-danger')"))

        page.click("#ev-browse-list >> text=sub-01")
        page.wait_for_selector("#ev-browse-list >> text=func")
        page.click("#ev-browse-list >> text=func")
        page.wait_for_selector("#ev-browse-list >> text=sub-01_task-motor_events.tsv")
        page.click("#ev-browse-list >> text=sub-01_task-motor_events.tsv")
        selected = page.inner_text("#ev-selected-path")
        self.assertTrue(selected.endswith("sub-01_task-motor_events.tsv"), selected)
        self.assertEqual(page.eval_on_selector("#ev-selected-path", "e => e.classList.contains('text-danger')"), False)
        self.assertTrue(page.eval_on_selector("#ev-browse-list .active", "e => e.textContent.includes('events.tsv')"))

        page.click("#btn-ev-browse-select")
        page.wait_for_selector("#ev-browse-modal", state="hidden")
        self.assertTrue(page.input_value("#input-events-file").endswith("sub-01_task-motor_events.tsv"))
        page.wait_for_function("document.getElementById('scan-status').textContent.length > 0")
        self.assertEqual(self.errors, [])

    def test_events_browser_double_click_selects_and_closes(self):
        page = self.open_page()
        self.open_events(page)
        page.click("#ev-browse-list >> text=sub-01")
        page.click("#ev-browse-list >> text=func")
        page.wait_for_selector("#ev-browse-list >> text=sub-01_task-motor_events.tsv")
        page.dblclick("#ev-browse-list >> text=sub-01_task-motor_events.tsv")
        page.wait_for_selector("#ev-browse-modal", state="hidden")
        self.assertTrue(page.input_value("#input-events-file").endswith("sub-01_task-motor_events.tsv"))
        self.assertEqual(self.errors, [])

    def test_events_browser_says_when_a_folder_has_no_events_files(self):
        page = self.open_page()
        self.open_events(page)
        page.click("#ev-browse-list >> text=sub-02")
        page.wait_for_selector("#ev-browse-list >> text=empty")
        page.click("#ev-browse-list >> text=empty")
        page.wait_for_selector("#ev-browse-list >> text=No *_events.tsv files in this folder.")
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
