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

    def add_recipe(self, page, rid):
        page.select_option("#wiz-recipe-add", rid)
        page.click("#wiz-add-recipe")

    def valid_item_then_pmod(self, page):
        self.add_recipe(page, "valid_only")
        card = page.locator("#wiz-recipes .wiz-recipe").nth(0)
        card.locator("[data-param=condition]").select_option("item")
        card.locator("[data-param=column]").select_option("response_validity")
        card.locator("[data-param=value]").select_option("valid")
        page.wait_for_function("document.getElementById('wiz-review').innerText.includes('valid_item.item')")
        self.add_recipe(page, "parametric_modulator")
        pm = page.locator("#wiz-recipes .wiz-recipe").nth(1)
        pm.locator("[data-param=regressor]").select_option("valid_item.item")
        pm.locator("[data-param=column]").select_option("rt")
        page.wait_for_function("document.getElementById('wiz-review').innerText.includes('rt_mod')"
                               " || document.getElementById('wiz-review').innerText.includes('valid_item_rt_mod')")

    def test_scan_failures_are_shown_and_disable_the_form(self):
        for status, body, ctype, expect in [(500, "<html>boom</html>", "text/html", "500"),
                                            (404, json.dumps({"error": "gone <b>x</b>"}), "application/json", "gone <b>x</b>")]:
            page = self.browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.route("**/api/wizard/scan", lambda r: r.fulfill(status=status, body=body, content_type=ctype))
            page.goto(f"{self.base}/model-wizard/{self.project_id}", wait_until="networkidle")
            page.wait_for_function("document.getElementById('wiz-error').innerText !== ''")
            self.assertIn(expect, page.inner_text("#wiz-error"))
            self.assertEqual(page.locator("#wiz-error b").count(), 0)
            self.assertTrue(page.is_disabled("#wiz-save"))
            self.assertTrue(page.is_disabled("#wiz-add-recipe"))
            self.assertEqual(errors, [])

    def test_recipe_order_can_be_changed_and_pmod_must_be_last(self):
        page = self.open_wizard()
        self.valid_item_then_pmod(page)
        self.assertIn("Recipes run in this order", page.inner_text("body"))
        self.assertTrue(page.locator("#wiz-recipes .wiz-recipe").nth(0).get_by_label("Move recipe up").is_disabled())
        self.assertTrue(page.locator("#wiz-recipes .wiz-recipe").nth(1).get_by_label("Move recipe down").is_disabled())
        page.locator("#wiz-recipes .wiz-recipe").nth(1).get_by_label("Move recipe up").click()
        page.wait_for_function("document.getElementById('wiz-error').innerText !== ''")
        self.assertIn("valid_item.item", page.inner_text("#wiz-review"))  # previous preview stays
        page.locator("#wiz-recipes .wiz-recipe").nth(0).get_by_label("Move recipe down").click()
        page.wait_for_function("document.getElementById('wiz-error').innerText === ''")
        page.locator("#wiz-recipes .wiz-recipe").nth(1).get_by_label("Remove recipe").click()
        self.assertEqual(page.locator("#wiz-recipes .wiz-recipe").count(), 1)
        self.assertEqual(self.errors, [])

    def test_a_late_build_response_does_not_wipe_typing(self):
        import time
        page = self.open_wizard()
        page.click("#wiz-add-pair")
        page.route("**/api/wizard/build", lambda r: (time.sleep(0.6), r.continue_()))
        page.uncheck("#wiz-conditions input[value=b]")
        box = page.locator("#wiz-pair-table input")
        box.click()
        box.press_sequentially("a_vs")
        page.wait_for_function("!document.getElementById('wiz-review').innerText.includes('trial_type.b')")
        self.assertEqual(box.input_value(), "a_vs")
        self.assertTrue(box.evaluate("e => e === document.activeElement"))

    def test_overwrite_flow_on_409(self):
        page = self.open_wizard()
        seen = []

        def handler(route):
            body = route.request.post_data_json
            if body.get("save_path") and not seen:
                seen.append(1)
                return route.fulfill(status=409, body=json.dumps({"error": "exists"}), content_type="application/json")
            route.continue_()
        page.route("**/api/wizard/build", handler)
        page.on("dialog", lambda d: d.accept())
        page.fill("#wiz-save-path", str(self.root / "o409" / "m.json"))
        page.click("#wiz-save")
        page.wait_for_url(f"**/analysis/{self.project_id}")
        self.assertTrue((self.root / "o409" / "m.json").exists())

    def test_custom_nuisance_list(self):
        page = self.open_wizard()
        page.select_option("#wiz-nuisance", "custom")
        page.fill("#wiz-nuisance-custom", "trans_x, trans_y")
        page.press("#wiz-nuisance-custom", "Tab")
        page.wait_for_function("document.getElementById('wiz-review').innerText.includes('2 columns')")

    def test_pair_table_adds_a_contrast(self):
        page = self.open_wizard()
        page.click("#wiz-add-pair")
        page.fill("#wiz-pair-table input", "a_vs_b")
        page.locator("#wiz-pair-table select").nth(0).select_option("trial_type.a")
        page.locator("#wiz-pair-table select").nth(1).select_option("trial_type.b")
        page.wait_for_function("document.getElementById('wiz-review').innerText.includes('a_vs_b')")
        self.assertEqual(self.errors, [])

    def test_event_values_in_options_are_text(self):
        page = self.browser.new_page()

        def patch(route):
            data = route.fetch().json()
            data["columns"]["response_validity"].append("<b>x</b>")
            data["columns"]["trial_type"].append("<i>q</i>")
            route.fulfill(status=200, body=json.dumps(data), content_type="application/json")
        page.route("**/api/wizard/scan", patch)
        page.goto(f"{self.base}/model-wizard/{self.project_id}", wait_until="networkidle")
        page.wait_for_selector("#wiz-conditions input")
        self.add_recipe(page, "valid_only")
        self.assertEqual(page.locator("#wiz-conditions i, #wiz-recipes b").count(), 0)
        self.assertIn("<i>q</i>", page.inner_text("#wiz-conditions"))
        labels = page.locator("#wiz-recipes [data-param=value] option").all_text_contents()
        self.assertIn("<b>x</b>", labels)
