import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from tests.browser_support import chromium_available, post_json, start_server, sync_playwright
from tests.preflight_support import make_trees

EVENTS = ("onset\tduration\ttrial_type\tresponse_validity\trt\n"
          "1\t1\ta\tvalid\t0.5\n5\t1\titem\tvalid\t0.7\n9\t1\titem\tinvalid\t0.4\n13\t1\tb\tvalid\t0.6\n")


@unittest.skipUnless(chromium_available(), "Playwright + Chromium not available")
class TestWizardPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        _, fmriprep = make_trees(cls.root, task="x", events=EVENTS)
        cls.server, cls.base, cls.project_id = start_server(cls.root)
        req = urllib.request.Request(
            f"{cls.base}/api/projects/{cls.project_id}", json.dumps({"config": {"fmriprep_folder": str(fmriprep)}}).encode(),
            {"Content-Type": "application/json"}, method="PUT")
        urllib.request.urlopen(req, timeout=10)
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.tmp.cleanup()

    def open_wizard(self):
        page = self.browser.new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto(f"{self.base}/model-wizard/{self.project_id}", wait_until="networkidle")
        page.wait_for_selector("#wiz-review .wiz-regressor")
        return page

    def test_page_loads_scans_and_previews(self):
        page = self.open_wizard()
        self.assertIn("trial_type.a", page.inner_text("#wiz-review"))
        self.assertEqual(page.input_value("#wiz-task"), "x")
        self.assertEqual(self.errors, [])

    def test_adding_a_valid_only_recipe_updates_the_preview(self):
        page = self.open_wizard()
        page.select_option("#wiz-recipe-add", "valid_only")
        page.click("#wiz-add-recipe")
        card = page.locator("#wiz-recipes .wiz-recipe")
        card.locator("[data-param=condition]").select_option("item")
        card.locator("[data-param=column]").select_option("response_validity")
        card.locator("[data-param=value]").select_option("valid")
        page.wait_for_function("document.getElementById('wiz-review').innerText.includes('valid_item.item')")
        self.assertIn("invalid", page.inner_text("#wiz-review .wiz-warnings"))
        self.assertEqual(self.errors, [])

    def test_unchecking_a_condition_excludes_it(self):
        page = self.open_wizard()
        page.uncheck("#wiz-conditions input[value=b]")
        page.wait_for_function("!document.getElementById('wiz-review').innerText.includes('trial_type.b')")
        self.assertIn("trial_type.a", page.inner_text("#wiz-review"))

    def test_engine_error_is_shown_not_thrown(self):
        page = self.open_wizard()
        page.route("**/api/wizard/build", lambda r: r.fulfill(
            status=400, body=json.dumps({"error": "x <b>y</b>"}), content_type="application/json"))
        page.uncheck("#wiz-conditions input[value=b]")
        page.wait_for_function("document.getElementById('wiz-error').innerText.includes('x <b>y</b>')")
        self.assertEqual(page.locator("#wiz-error b").count(), 0)
        self.assertIn("trial_type.a", page.inner_text("#wiz-review"))  # previous preview stays
        page.unroute("**/api/wizard/build")
        page.check("#wiz-conditions input[value=b]")
        page.wait_for_function("document.getElementById('wiz-error').innerText === ''")
        self.assertEqual(self.errors, [])

    def test_server_strings_in_the_review_are_text(self):
        page = self.open_wizard()
        page.evaluate("""renderReview({regressors: ['trial_type.<i>q</i>'], nuisance: [], contrasts: [], warnings: ['w <b>x</b>']},
            {verdict: 'blocked', checks: [{severity: 'error', subject: null, message: 'm <u>z</u>', fix: 'f <s>k</s>'}]})""")
        self.assertEqual(page.locator("#wiz-review b, #wiz-review i, #wiz-review u, #wiz-review s").count(), 0)
        self.assertIn("m <u>z</u>", page.inner_text("#wiz-review"))

    def test_save_writes_the_model_and_returns_to_analysis(self):
        page = self.open_wizard()
        target = self.root / "out" / "saved.json"
        page.fill("#wiz-save-path", str(target))
        page.click("#wiz-save")
        page.wait_for_url(f"**/analysis/{self.project_id}")
        self.assertEqual(json.loads(target.read_text())["Nodes"][0]["Level"], "Run")
        cfg = json.loads(urllib.request.urlopen(f"{self.base}/api/projects/{self.project_id}/config").read())
        self.assertEqual(cfg["models_file"], str(target))

    def test_new_model_button_opens_the_wizard(self):
        page = self.browser.new_page()
        page.goto(f"{self.base}/analysis/{self.project_id}", wait_until="load")
        page.evaluate("createNewModel()")
        page.wait_for_url(f"**/model-wizard/{self.project_id}")
