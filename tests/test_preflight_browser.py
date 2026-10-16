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

    BLOCKED = {"error": "preflight failed", "preflight": {"verdict": "blocked", "checks": [
        {"id": "x", "severity": "error", "subject": None, "message": "no fMRIPrep <u>tree</u>", "fix": "run fMRIPrep"}]}}

    def run_with_route(self, path, status, body, content_type="application/json"):
        page = self.open_page()
        page.route(f"**{path}", lambda r: r.fulfill(status=status, body=body, content_type=content_type))
        return page

    def test_blocked_run_explains_why_in_terminal_and_panel(self):
        import json
        page = self.run_with_route("/run", 400, json.dumps(self.BLOCKED))
        page.evaluate("startExecution({actions: ['x']})")
        page.wait_for_function("document.getElementById('exec-status').innerText === 'IDLE'")
        term = page.evaluate("terminal.innerText")
        self.assertIn("no fMRIPrep <u>tree</u>", term)
        self.assertIn("run fMRIPrep", term)
        self.assertIn("blocked", page.inner_text("#preflight-panel").lower())

    def test_run_non_json_response_resets_status(self):
        page = self.run_with_route("/run", 500, "<html>boom</html>", "text/html")
        page.evaluate("startExecution({actions: ['x']})")
        page.wait_for_function("document.getElementById('exec-status').innerText === 'IDLE'")
        self.assertIn("500", page.evaluate("terminal.innerText"))

    def test_preflight_non_json_response_shows_blocked_failure(self):
        page = self.run_with_route("/api/preflight", 500, "<html>boom</html>", "text/html")
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .preflight-verdict")
        self.assertIn("Readiness check failed", page.inner_text("#preflight-panel"))
        self.assertTrue(page.is_enabled("#btn-preflight"))

    def test_successful_run_clears_stale_panel(self):
        page = self.open_page()
        page.evaluate("renderPreflight({verdict: 'blocked', checks: []})")
        page.route("**/run", lambda r: r.fulfill(status=200, body='{"execution_id": "nope"}', content_type="application/json"))
        page.evaluate("startExecution({actions: ['x']})")
        page.wait_for_function("document.getElementById('preflight-panel').children.length === 0")

    def test_missing_verdict_renders_unknown(self):
        page = self.open_page()
        page.evaluate("renderPreflight({checks: []})")
        self.assertIn("unknown", page.inner_text("#preflight-panel"))

    def test_validator_choice_is_keyed_per_project(self):
        page = self.open_page()
        page.select_option("#validator-mode", "skip")
        keys = page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('bidspm_validator_mode_'))")
        self.assertEqual(keys, [f"bidspm_validator_mode_{self.project_id}"])

    def test_note_and_checking_status_are_shown(self):
        page = self.open_page()
        self.assertIn("saved project settings", page.inner_text("#preflight-note"))
        page.route("**/api/preflight", lambda r: None)  # never answered: the status line stays
        page.click("#btn-preflight")
        page.wait_for_selector("#preflight-panel .preflight-status")
        self.assertIn("Checking readiness", page.inner_text("#preflight-panel"))
