import tempfile
import unittest
from pathlib import Path

from tests.browser_support import chromium_available, make_dataset, start_server, sync_playwright


@unittest.skipUnless(chromium_available(), "Playwright + Chromium not available")
class TestPreflightPanel(unittest.TestCase):
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
        page.goto(f"{self.base}/analysis/{self.project_id}", wait_until="networkidle")
        return page

    def test_button_renders_a_blocked_report_with_fix_hints(self):
        page = self.open_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.select_option("#validator-mode", "skip")
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .preflight-verdict")
        self.assertIn("blocked", page.inner_text("#preflight-panel").lower())  # the test project has no fMRIPrep tree
        self.assertTrue(page.locator("#preflight-panel .preflight-fix").count() >= 1)
        self.assertEqual(errors, [])

    def test_validator_choice_is_remembered_per_project(self):
        page = self.open_page()
        page.select_option("#validator-mode", "bids")
        page.reload(wait_until="networkidle")
        self.assertEqual(page.input_value("#validator-mode"), "bids")

    def test_server_messages_render_as_text_not_html(self):
        page = self.open_page()
        page.evaluate("""renderPreflight({verdict: 'blocked', checks: [{id: 'x', severity: 'error',
            subject: '01', message: '/data/<b>x</b>', fix: 'run <i>this</i>'}]})""")
        self.assertEqual(page.locator("#preflight-panel b, #preflight-panel i").count(), 0)
        text = page.inner_text("#preflight-panel")
        self.assertIn("<b>x</b>", text)
        self.assertIn("<i>this</i>", text)
