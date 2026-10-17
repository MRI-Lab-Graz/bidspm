import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from tests.browser_support import chromium_available, post_json, start_server, sync_playwright
from tests.preflight_support import make_trees
from tests.test_readiness_panel_browser import HEAD, done, sse, subject_step

EVENTS = ("onset\tduration\ttrial_type\tresponse_validity\trt\n"
          "1\t1\ta\tvalid\t0.5\n5\t1\titem\tvalid\t0.7\n9\t1\titem\tinvalid\t0.4\n13\t1\tb\tvalid\t0.6\n")


STEPS = ["task", "recipes", "nuisance", "contrasts", "review"]


def wizard_go_to(page, step):
    """Click the strip button of a step (every earlier step must be complete) and wait until it is current."""
    page.wait_for_function("wiz.edit === wiz.built")  # moving on is refused while the preview is updating
    page.click(f"[data-wiz-btn={step}]")
    page.wait_for_selector(f"[data-wiz-btn={step}][aria-current=step]")


def add_recipe_card(page, rid):
    wizard_go_to(page, "recipes")
    page.click(f"#wiz-gallery .wiz-card[data-recipe={rid}]")


@unittest.skipUnless(chromium_available(), "Playwright + Chromium not available")
class TestWizardPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        _, fmriprep = make_trees(cls.root, task="x", events=EVENTS, space="MNI152NLin2009cAsym")
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

    def tearDown(self):  # leaked pages (e.g. the analysis page after a save) keep server connections busy
        for ctx in self.browser.contexts:
            for pg in ctx.pages:
                pg.close()

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
        add_recipe_card(page, "valid_only")
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
        page.evaluate("""renderReview({regressors: ['trial_type.<i>q</i>'], nuisance: [], contrasts: [], warnings: ['w <b>x</b>']})""")
        self.assertEqual(page.locator("#wiz-review b, #wiz-review i").count(), 0)
        self.assertIn("w <b>x</b>", page.inner_text("#wiz-review"))

    def test_save_writes_the_model_and_returns_to_analysis(self):
        page = self.open_wizard()
        wizard_go_to(page, "review")
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
        add_recipe_card(page, rid)

    def open_pairs(self, page):
        wizard_go_to(page, "contrasts")
        page.click("#wiz-pairs-details > summary")

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
            self.assertEqual(page.get_attribute("#wiz-next", "aria-disabled"), "true")
            self.assertIn("scan", page.inner_text("#wiz-hint").lower())
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
        self.open_pairs(page)
        page.click("#wiz-add-pair")
        page.route("**/api/wizard/build", lambda r: (time.sleep(0.6), r.continue_()))
        page.evaluate("document.querySelector('#wiz-conditions input[value=b]').click()")  # step 1 is hidden
        box = page.locator("#wiz-pair-table input")
        box.click()
        box.press_sequentially("a_vs")
        page.wait_for_function("!document.getElementById('wiz-review').innerText.includes('trial_type.b')")
        self.assertEqual(box.input_value(), "a_vs")
        self.assertTrue(box.evaluate("e => e === document.activeElement"))

    def test_overwrite_flow_on_409(self):
        page = self.open_wizard()
        wizard_go_to(page, "review")
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
        wizard_go_to(page, "nuisance")
        page.click("#wiz-nuisance-details > summary")
        page.check("#wiz-nuisance input[value=custom]")
        page.fill("#wiz-nuisance-custom", "trans_x, trans_y")
        page.press("#wiz-nuisance-custom", "Tab")
        page.wait_for_function("document.getElementById('wiz-review').innerText.includes('2 columns')")

    def test_pair_table_adds_a_contrast(self):
        page = self.open_wizard()
        self.open_pairs(page)
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
        wizard_go_to(page, "task")
        self.assertEqual(page.locator("#wiz-conditions i, #wiz-recipes b").count(), 0)
        self.assertIn("<i>q</i>", page.inner_text("#wiz-conditions"))
        labels = page.locator("#wiz-recipes [data-param=value] option").all_text_contents()
        self.assertIn("<b>x</b>", labels)

    def drop_b_route(self, page):
        def patch(route):
            data = route.fetch().json()
            if "preview" in data:
                data["preview"]["regressors"] = [r for r in data["preview"]["regressors"] if r != "trial_type.b"]
            route.fulfill(status=route.fetch().status, body=json.dumps(data), content_type="application/json")
        page.route("**/api/wizard/build", patch)

    def test_deferred_rerender_runs_after_focus_leaves_recipes(self):
        page = self.open_wizard()
        self.add_recipe(page, "parametric_modulator")
        sel = page.locator("#wiz-recipes [data-param=regressor]")
        self.assertIn("trial_type.b", sel.locator("option").all_text_contents())
        self.drop_b_route(page)
        sel.focus()
        sel.select_option("trial_type.a")
        page.wait_for_function("!document.getElementById('wiz-review').innerText.includes('trial_type.b')")
        page.evaluate("document.activeElement.blur()")
        page.wait_for_function("![...document.querySelectorAll('#wiz-recipes [data-param=regressor] option')]"
                               ".some(o => o.value === 'trial_type.b')")
        self.assertEqual(page.input_value("#wiz-recipes [data-param=regressor]"), "trial_type.a")

    def test_deferred_rerender_runs_after_focus_leaves_pairs(self):
        import time
        page = self.open_wizard()
        self.open_pairs(page)
        page.click("#wiz-add-pair")
        page.route("**/api/wizard/build", lambda r: (time.sleep(0.6), r.continue_()))
        page.evaluate("document.querySelector('#wiz-conditions input[value=b]').click()")  # step 1 is hidden
        box = page.locator("#wiz-pair-table input")
        box.click()
        box.press_sequentially("zz")
        page.wait_for_function("!document.getElementById('wiz-review').innerText.includes('trial_type.b')")
        self.assertEqual(box.input_value(), "zz")
        page.evaluate("document.activeElement.blur()")
        page.wait_for_function("![...document.querySelectorAll('#wiz-pair-table select option')]"
                               ".some(o => o.value === 'trial_type.b')")
        self.assertEqual(page.locator("#wiz-pair-table input").input_value(), "zz")

    def test_failed_scan_keeps_task_select_for_retry(self):
        page = self.browser.new_page()
        calls = []

        def scan(route):
            calls.append(1)
            if len(calls) == 2:
                return route.fulfill(status=500, body="<html>x</html>", content_type="text/html")
            data = route.fetch().json()
            data["tasks"] = ["x", "y"]
            route.fulfill(status=200, body=json.dumps(data), content_type="application/json")
        page.route("**/api/wizard/scan", scan)
        page.goto(f"{self.base}/model-wizard/{self.project_id}", wait_until="networkidle")
        page.wait_for_selector("#wiz-review .wiz-regressor")
        page.select_option("#wiz-task", "y")
        page.wait_for_function("document.getElementById('wiz-error').innerText !== ''")
        self.assertTrue(page.is_disabled("#wiz-save"))
        self.assertTrue(page.is_enabled("#wiz-task"))
        page.select_option("#wiz-task", "x")
        page.wait_for_function("document.getElementById('wiz-error').innerText === ''")
        self.assertTrue(page.is_enabled("#wiz-save"))

    def build_bodies(self, page):
        bodies = []
        page.on("request", lambda r: bodies.append(json.loads(r.post_data)) if r.url.endswith("/api/wizard/build") else None)
        return bodies

    def test_preview_builds_do_not_request_preflight(self):
        page = self.browser.new_page()
        bodies = self.build_bodies(page)
        page.goto(f"{self.base}/model-wizard/{self.project_id}", wait_until="networkidle")
        page.wait_for_selector("#wiz-review .wiz-regressor")
        page.uncheck("#wiz-conditions input[value=b]")
        page.wait_for_function("!document.getElementById('wiz-review').innerText.includes('trial_type.b')")
        self.assertTrue(bodies and all(b["preflight"] is False for b in bodies))
        self.assertEqual(page.locator("#wiz-review .preflight-verdict, #wiz-review .preflight-pending").count(), 0)

    def test_incomplete_recipe_is_not_sent_and_is_marked(self):
        page = self.browser.new_page()
        bodies = self.build_bodies(page)
        page.goto(f"{self.base}/model-wizard/{self.project_id}", wait_until="networkidle")
        page.wait_for_selector("#wiz-review .wiz-regressor")
        add_recipe_card(page, "merge_rename")
        page.wait_for_selector("#wiz-recipes .wiz-incomplete-note:not([hidden])")
        wizard_go_to(page, "task")
        page.uncheck("#wiz-conditions input[value=b]")  # forces another build
        page.wait_for_function("!document.getElementById('wiz-review').innerText.includes('trial_type.b')")
        self.assertTrue(all(b["choices"]["recipes"] == [] for b in bodies))
        self.assertTrue(page.locator("#wiz-error").is_hidden())
        wizard_go_to(page, "recipes")
        self.assertIn("incomplete", page.inner_text("#wiz-recipes"))

    def test_save_refuses_while_a_recipe_is_incomplete(self):
        page = self.browser.new_page()
        bodies = self.build_bodies(page)
        page.goto(f"{self.base}/model-wizard/{self.project_id}", wait_until="networkidle")
        page.wait_for_selector("#wiz-review .wiz-regressor")
        target = self.root / "never_written.json"
        wizard_go_to(page, "review")
        page.fill("#wiz-save-path", str(target))
        add_recipe_card(page, "merge_rename")
        page.wait_for_selector("#wiz-recipes .wiz-incomplete-note:not([hidden])")
        page.evaluate("save()")  # the stepper no longer reaches Review with an incomplete recipe; save() still refuses
        page.wait_for_function("document.getElementById('wiz-error').innerText.includes('incomplete recipe')")
        page.wait_for_timeout(500)
        self.assertFalse(any(b.get("save_path") for b in bodies))
        self.assertFalse(target.exists())

    # ---- stepper ---------------------------------------------------------------------------------------
    def visible_steps(self, page):
        return page.eval_on_selector_all("[data-wiz-step]", "els => els.filter(e => e.offsetParent !== null).map(e => e.dataset.wizStep)")

    def test_only_one_step_is_visible_at_a_time(self):
        page = self.open_wizard()
        for i, step in enumerate(STEPS):
            self.assertEqual(self.visible_steps(page), [step])
            self.assertTrue(page.locator("#wiz-rail").is_visible())
            if i < len(STEPS) - 1:
                page.click("#wiz-next")
                page.wait_for_selector(f"[data-wiz-btn={STEPS[i + 1]}][aria-current=step]")
        self.assertTrue(page.locator("#wiz-next").is_hidden())

    def test_strip_marks_done_current_upcoming_with_summaries(self):
        page = self.open_wizard()
        cls = lambda s: page.get_attribute(f"[data-wiz-btn={s}]", "class").split()
        self.assertIn("current", cls("task"))
        self.assertIn("upcoming", cls("recipes"))
        self.assertEqual(page.inner_text("[data-wiz-btn=task] .stage-btn-summary").strip(), "")
        self.valid_item_then_pmod(page)
        wizard_go_to(page, "nuisance")
        page.check("#wiz-nuisance input[value=motion6]")
        wizard_go_to(page, "contrasts")
        self.assertIn("done", cls("task"))
        self.assertIn("done", cls("recipes"))
        self.assertIn("current", cls("contrasts"))
        self.assertIn("upcoming", cls("review"))
        self.assertIn("x", page.inner_text("[data-wiz-btn=task] .stage-btn-summary"))
        self.assertIn("2 recipes", page.inner_text("[data-wiz-btn=recipes] .stage-btn-summary"))
        page.wait_for_function("document.querySelector('[data-wiz-btn=nuisance] .stage-btn-summary').innerText.includes('motion6')")
        self.assertIn("6", page.inner_text("[data-wiz-btn=nuisance] .stage-btn-summary"))

    def test_next_is_blocked_with_a_visible_reason(self):
        page = self.open_wizard()
        wizard_go_to(page, "recipes")
        self.assertEqual(page.get_attribute("#wiz-next", "aria-disabled"), "false")
        add_recipe_card(page, "merge_rename")
        page.wait_for_function("document.getElementById('wiz-next').getAttribute('aria-disabled') === 'true'")
        self.assertIn("incomplete", page.inner_text("#wiz-hint"))
        page.click("#wiz-next", force=True)  # aria-disabled keeps it focusable and clickable
        self.assertEqual(self.visible_steps(page), ["recipes"])
        page.wait_for_function("wiz.edit === wiz.built")
        page.click("[data-wiz-btn=review]")  # a forward jump is refused with a reason too
        self.assertEqual(self.visible_steps(page), ["recipes"])
        self.assertIn("incomplete", page.inner_text("#wiz-hint"))
        page.locator("#wiz-recipes .wiz-recipe").get_by_label("Remove recipe").click()
        page.wait_for_function("document.getElementById('wiz-next').getAttribute('aria-disabled') === 'false'")
        self.assertEqual(page.inner_text("#wiz-hint").strip(), "")

    def test_next_is_blocked_when_no_regressor_is_left(self):
        page = self.open_wizard()
        for c in ("a", "item", "b"):
            page.uncheck(f"#wiz-conditions input[value={c}]")
        page.wait_for_function("document.getElementById('wiz-next').getAttribute('aria-disabled') === 'true'")
        self.assertIn("regressor", page.inner_text("#wiz-hint"))
        page.click("#wiz-next", force=True)
        self.assertEqual(self.visible_steps(page), ["task"])
        page.check("#wiz-conditions input[value=a]")
        page.wait_for_function("document.getElementById('wiz-next').getAttribute('aria-disabled') === 'false'")

    def test_scan_failure_keeps_next_blocked(self):
        page = self.browser.new_page()
        page.route("**/api/wizard/scan", lambda r: r.fulfill(status=500, body="boom", content_type="text/plain"))
        page.goto(f"{self.base}/model-wizard/{self.project_id}", wait_until="networkidle")
        page.wait_for_function("document.getElementById('wiz-error').innerText !== ''")
        self.assertEqual(page.get_attribute("#wiz-next", "aria-disabled"), "true")
        self.assertIn("scan", page.inner_text("#wiz-hint").lower())
        page.click("#wiz-next", force=True)
        self.assertEqual(self.visible_steps(page), ["task"])

    def test_gallery_adds_a_recipe_and_opens_its_form(self):
        page = self.open_wizard()
        wizard_go_to(page, "recipes")
        catalog = page.evaluate("wiz.scan.catalog")
        cards = page.locator("#wiz-gallery .wiz-card")
        self.assertEqual(cards.count(), len(catalog))
        for c in catalog:
            text = page.inner_text(f"#wiz-gallery .wiz-card[data-recipe={c['id']}]")
            self.assertIn(c["title"], text)
            self.assertIn(c["description"], text)
        self.assertIn("No special handling needed", page.inner_text("#wiz-recipes-empty"))
        page.click("#wiz-gallery .wiz-card[data-recipe=valid_only]")
        self.assertEqual(page.locator("#wiz-recipes .wiz-recipe").count(), 1)
        self.assertTrue(page.locator("#wiz-recipes-empty").is_hidden())
        page.wait_for_function("document.activeElement && document.activeElement.closest('#wiz-recipes')")
        self.assertEqual(page.locator("#wiz-add-recipe, #wiz-recipe-add").count(), 0)

    def test_rail_is_visible_on_every_step_and_updates(self):
        page = self.open_wizard()
        page.uncheck("#wiz-conditions input[value=b]")
        page.wait_for_function("!document.getElementById('wiz-rail').innerText.includes('trial_type.b')")
        for step in STEPS:
            wizard_go_to(page, step)
            self.assertTrue(page.locator("#wiz-rail").is_visible())
            self.assertIn("trial_type.a", page.inner_text("#wiz-rail"))
        self.assertTrue(page.locator("#wiz-rail #wiz-review").count() == 1)

    def test_advanced_disclosures_are_collapsed_by_default(self):
        page = self.open_wizard()
        wizard_go_to(page, "nuisance")
        self.assertFalse(page.evaluate("document.getElementById('wiz-nuisance-details').open"))
        self.assertTrue(page.locator("#wiz-nuisance-custom").is_hidden())
        wizard_go_to(page, "contrasts")
        self.assertFalse(page.evaluate("document.getElementById('wiz-pairs-details').open"))
        self.assertTrue(page.locator("#wiz-pair-table").is_hidden())
        self.assertTrue(page.get_by_role("link", name="contrast builder").is_visible())
        self.assertTrue(page.is_checked("#wiz-auto-contrasts"))

    def test_back_and_strip_jump(self):
        page = self.open_wizard()
        page.click("#wiz-next")
        page.click("#wiz-next")
        page.wait_for_selector("[data-wiz-btn=nuisance][aria-current=step]")
        page.click("#wiz-back")
        page.wait_for_selector("[data-wiz-btn=recipes][aria-current=step]")
        wizard_go_to(page, "contrasts")
        wizard_go_to(page, "task")  # a visited step is one click away
        self.assertEqual(self.visible_steps(page), ["task"])
        self.assertTrue(page.locator("#wiz-back").is_hidden())

    def test_keyboard_navigation_moves_aria_current_and_focus(self):
        page = self.open_wizard()
        page.focus("#wiz-next")
        page.keyboard.press("Enter")
        page.wait_for_selector("[data-wiz-btn=recipes][aria-current=step]")
        self.assertEqual(page.locator("[aria-current=step]").count(), 1)
        self.assertEqual(page.evaluate("document.activeElement.id"), "wiz-heading")
        self.assertIn("Recipes", page.inner_text("#wiz-heading"))
        self.assertEqual(page.get_attribute("#wiz-next", "type"), "button")

    def test_server_strings_in_gallery_forms_and_rail_are_text(self):
        page = self.browser.new_page()

        def scan(route):
            data = route.fetch().json()
            data["columns"]["trial_type"].append("<i>q</i>")
            data["catalog"][0]["description"] = "d <b>x</b>"
            route.fulfill(status=200, body=json.dumps(data), content_type="application/json")

        def build(route):
            data = route.fetch().json()
            data["preview"]["regressors"].append("trial_type.<i>q</i>")
            route.fulfill(status=200, body=json.dumps(data), content_type="application/json")
        page.route("**/api/wizard/scan", scan)
        page.route("**/api/wizard/build", build)
        page.goto(f"{self.base}/model-wizard/{self.project_id}", wait_until="networkidle")
        page.wait_for_function("document.getElementById('wiz-rail').innerText.includes('<i>q</i>')")
        wizard_go_to(page, "recipes")
        page.locator("#wiz-gallery .wiz-card").first.click()
        self.assertIn("<b>x</b>", page.inner_text("#wiz-gallery"))
        self.assertEqual(page.locator("#wiz-gallery b, #wiz-recipes b, #wiz-rail i, #wiz-rail b, [data-wiz-btn] i").count(), 0)

    # ---- review round fixes -----------------------------------------------------------------------------
    def two_task_page(self):
        page = self.browser.new_page()

        def scan(route):
            body = route.request.post_data_json
            data = route.fetch(post_data=json.dumps({**body, "task": "x"})).json()
            data["tasks"] = ["x", "y"]
            data["task"] = body.get("task") or "x"
            route.fulfill(status=200, body=json.dumps(data), content_type="application/json")
        def build(route):  # the server only knows task x
            body = route.request.post_data_json
            body["choices"]["task"] = "x"
            route.continue_(post_data=json.dumps(body))
        page.route("**/api/wizard/scan", scan)
        page.route("**/api/wizard/build", build)
        bodies = self.build_bodies(page)
        page.goto(f"{self.base}/model-wizard/{self.project_id}", wait_until="networkidle")
        page.wait_for_selector("#wiz-review .wiz-regressor")
        return page, bodies

    def test_custom_nuisance_survives_a_task_change(self):
        page, bodies = self.two_task_page()
        wizard_go_to(page, "nuisance")
        page.click("#wiz-nuisance-details > summary")
        page.fill("#wiz-nuisance-custom", "trans_x, trans_y")
        page.press("#wiz-nuisance-custom", "Tab")
        page.wait_for_function("document.getElementById('wiz-review').innerText.includes('2 columns')")
        wizard_go_to(page, "task")
        page.select_option("#wiz-task", "y")
        page.wait_for_function("wiz.scan && wiz.scan.task === 'y' && wiz.edit === wiz.built")
        wizard_go_to(page, "nuisance")
        self.assertTrue(page.is_checked("#wiz-nuisance input[value=custom]"))
        self.assertEqual(page.input_value("#wiz-nuisance-custom"), "trans_x, trans_y")
        self.assertTrue(page.evaluate("document.getElementById('wiz-nuisance-details').open"))
        self.assertEqual(bodies[-1]["choices"]["nuisance"], ["trans_x", "trans_y"])

    def test_nuisance_radios_form_one_group_with_arrow_keys(self):
        page = self.open_wizard()
        wizard_go_to(page, "nuisance")
        self.assertEqual(page.locator("#wiz-nuisance legend").inner_text().strip(), "Nuisance regressors")
        radios = page.locator("#wiz-nuisance input[type=radio]")
        n = radios.count()
        self.assertEqual(page.locator("input[name=wiz-nuisance]").count(), n)
        page.focus("#wiz-nuisance input:checked")
        for _ in range(n):
            page.keyboard.press("ArrowDown")
        self.assertTrue(page.evaluate("document.activeElement.name === 'wiz-nuisance'"))

    def rejecting_route(self, page):
        page.route("**/api/wizard/build", lambda r: r.fulfill(
            status=400, body=json.dumps({"error": "bad recipe"}), content_type="application/json")
            if r.request.post_data_json["choices"]["recipes"] else r.continue_())

    def test_next_is_blocked_while_the_build_fails(self):
        page = self.open_wizard()
        self.rejecting_route(page)
        self.valid_item_then_pmod_first_only(page)
        page.wait_for_function("document.getElementById('wiz-next').getAttribute('aria-disabled') === 'true'")
        self.assertIn("do not build", page.inner_text("#wiz-hint"))
        page.click("#wiz-next", force=True)
        self.assertEqual(self.visible_steps(page), ["recipes"])
        page.unroute("**/api/wizard/build")
        page.locator("#wiz-recipes .wiz-recipe").get_by_label("Remove recipe").click()
        page.wait_for_function("document.getElementById('wiz-next').getAttribute('aria-disabled') === 'false'")

    def valid_item_then_pmod_first_only(self, page):
        self.add_recipe(page, "valid_only")
        card = page.locator("#wiz-recipes .wiz-recipe").nth(0)
        card.locator("[data-param=condition]").select_option("item")
        card.locator("[data-param=column]").select_option("response_validity")
        card.locator("[data-param=value]").select_option("valid")

    def test_next_is_refused_while_the_preview_is_stale(self):
        page = self.open_wizard()
        held = []
        page.route("**/api/wizard/build", lambda r: held.append(r))
        with page.expect_request("**/api/wizard/build"):
            page.uncheck("#wiz-conditions input[value=b]")
        self.assertEqual(page.get_attribute("#wiz-next", "aria-disabled"), "false")  # no flash during the debounce
        page.click("#wiz-next")
        self.assertEqual(self.visible_steps(page), ["task"])
        self.assertIn("Updating the preview", page.inner_text("#wiz-hint"))
        page.click("[data-wiz-btn=review]")
        self.assertEqual(self.visible_steps(page), ["task"])
        held.pop().continue_()
        page.wait_for_function("wiz.edit === wiz.built")
        page.click("#wiz-next")
        page.wait_for_selector("[data-wiz-btn=recipes][aria-current=step]")

    def test_back_then_incomplete_recipe_refuses_a_strip_jump(self):
        page = self.open_wizard()
        wizard_go_to(page, "nuisance")
        page.click("#wiz-back")
        page.wait_for_selector("[data-wiz-btn=recipes][aria-current=step]")
        page.click("#wiz-gallery .wiz-card[data-recipe=merge_rename]")
        page.wait_for_function("wiz.edit === wiz.built")
        page.click("[data-wiz-btn=review]")
        self.assertEqual(self.visible_steps(page), ["recipes"])
        self.assertIn("incomplete", page.inner_text("#wiz-hint"))

    def test_recipe_values_survive_leaving_and_returning(self):
        page = self.open_wizard()
        self.valid_item_then_pmod_first_only(page)
        wizard_go_to(page, "task")
        wizard_go_to(page, "recipes")
        card = page.locator("#wiz-recipes .wiz-recipe").nth(0)
        self.assertEqual(card.locator("[data-param=condition]").input_value(), "item")
        self.assertEqual(card.locator("[data-param=value]").input_value(), "valid")

    def test_gallery_cards_are_named_for_screen_readers_and_focus_the_new_form(self):
        page = self.open_wizard()
        wizard_go_to(page, "recipes")
        for c in page.evaluate("wiz.scan.catalog"):
            self.assertEqual(page.get_attribute(f"#wiz-gallery [data-recipe={c['id']}]", "aria-label"), f"Add recipe: {c['title']}")
        page.get_by_role("button", name="Add recipe: " + page.evaluate("wiz.scan.catalog[0].title")).click()
        self.assertTrue(page.evaluate("!!document.activeElement.closest('#wiz-recipes .wiz-recipe')"))
        self.assertEqual(page.get_attribute("#wiz-recipes .wiz-recipe", "tabindex"), "-1")

    # ---- live readiness check in the review step ---------------------------------------------------
    def readiness_page(self, stream=None, hold_builds=False):
        """Wizard with the start/stream/cancel endpoints mocked; returns (page, builds, starts, cancels)."""
        page = self.browser.new_page()
        self.errors = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        builds, starts, cancels = [], [], []

        def build(route):
            if hold_builds:
                return None
            resp = route.fetch()
            if resp.status == 200:
                builds.append(resp.json())
            route.fulfill(response=resp)

        page.route("**/api/wizard/build", build)
        page.route("**/api/preflight/start", lambda r: (starts.append(r.request.post_data_json), r.fulfill(
            status=200, body='{"id": "j1"}', content_type="application/json")))
        page.route("**/api/preflight/stream/**", (lambda r: r.fulfill(status=200, body=stream, content_type="text/event-stream"))
                   if stream is not None else (lambda r: None))
        page.route("**/api/preflight/cancel/**", lambda r: (cancels.append(r.request.url), r.fulfill(
            status=200, body='{"status": "cancelling"}', content_type="application/json")))
        page.goto(f"{self.base}/model-wizard/{self.project_id}", wait_until="load")
        if not hold_builds:
            page.wait_for_selector("#wiz-review .wiz-regressor")
            wizard_go_to(page, "review")
        else:
            page.wait_for_function("wiz.scan !== null")
            page.evaluate("wiz.step = 'review'; WizardSteps.render()")
        return page, builds, starts, cancels

    def test_check_posts_the_built_model_with_stats_and_no_validator(self):
        page, builds, starts, _ = self.readiness_page(sse(HEAD + [subject_step(1), done()]))
        page.click("#wiz-check")
        page.wait_for_function("document.querySelector('#wiz-readiness .preflight-verdict')")
        body = starts[0]
        self.assertEqual(body["model_json"], builds[-1]["model"])
        self.assertEqual((body["validator"], body["actions"]), ("off", ["stats"]))
        self.assertEqual(body["config"]["TASKS"], ["x"])
        self.assertEqual({"BIDS_DIR", "FMRIPREP_DIR", "SPACE"} - set(body["config"]), set())

    def test_verdict_renders_inside_the_review_step_not_the_rail(self):
        page, *_ = self.readiness_page(sse(HEAD + [subject_step(1), done()]))
        page.click("#wiz-check")
        page.wait_for_selector("#wiz-readiness .preflight-verdict")
        self.assertEqual(page.locator("#wiz-rail .preflight-verdict").count(), 0)
        self.assertTrue(page.evaluate("!!document.querySelector('[data-wiz-step=review] #wiz-readiness')"))

    def test_check_is_disabled_with_a_reason_before_the_first_build(self):
        page, *_ = self.readiness_page(hold_builds=True)
        self.assertTrue(page.is_disabled("#wiz-check"))
        self.assertIn("Build a valid preview first", page.inner_text("#wiz-check-hint"))
        self.assertTrue(page.is_visible("#wiz-check-hint"))

    def test_check_is_disabled_while_the_preview_is_dirty_and_back_after(self):
        page, *_ = self.readiness_page()
        self.assertTrue(page.is_enabled("#wiz-check"))
        held = []
        page.route("**/api/wizard/build", lambda r: held.append(r))
        with page.expect_request("**/api/wizard/build"):
            page.evaluate("document.querySelector('#wiz-conditions input[value=b]').click()")
        self.assertTrue(page.is_disabled("#wiz-check"))
        self.assertIn("Build a valid preview first", page.inner_text("#wiz-check-hint"))
        page.unroute("**/api/wizard/build")
        held.pop().continue_()
        page.wait_for_function("!document.getElementById('wiz-check').disabled")
        self.assertEqual(page.inner_text("#wiz-check-hint"), "")

    def test_a_choice_change_after_a_finished_check_marks_it_out_of_date(self):
        page, *_ = self.readiness_page(sse(HEAD + [subject_step(1), done()]))
        page.click("#wiz-check")
        page.wait_for_selector("#wiz-readiness .preflight-verdict")
        self.assertEqual(page.locator("#wiz-readiness .wiz-stale").count(), 0)
        page.evaluate("document.querySelector('#wiz-conditions input[value=b]').click()")
        page.wait_for_selector("#wiz-readiness .wiz-stale")
        note = page.locator("#wiz-readiness .wiz-stale")
        self.assertIn("out of date", note.inner_text().lower())
        self.assertEqual(note.get_attribute("aria-live"), "off")
        self.assertIn("Readiness:", page.inner_text("#wiz-readiness"))  # the old verdict stays visible, labelled
        page.wait_for_function("wiz.edit === wiz.built")
        page.click("#wiz-check")
        page.wait_for_function("!document.querySelector('#wiz-readiness .wiz-stale')")

    def test_cancel_posts_to_the_job(self):
        page, _, _, cancels = self.readiness_page()  # the stream never answers
        page.click("#wiz-check")
        page.click("#wiz-readiness .rp-cancel")
        page.wait_for_function("document.getElementById('wiz-readiness').innerText.includes('Cancelled')")
        self.assertTrue(any(u.endswith("/api/preflight/cancel/j1") for u in cancels))

    def test_real_readiness_check_reaches_a_verdict_for_the_built_model(self):
        page = self.browser.new_page()
        sent = []
        page.on("request", lambda r: sent.append(r.post_data_json) if r.url.endswith("/api/preflight/start") else None)
        page.goto(f"{self.base}/model-wizard/{self.project_id}", wait_until="networkidle")
        page.wait_for_selector("#wiz-review .wiz-regressor")
        wizard_go_to(page, "review")
        page.click("#wiz-check")
        page.wait_for_selector("#wiz-readiness .preflight-verdict", timeout=60000)
        self.assertRegex(page.inner_text("#wiz-readiness .preflight-verdict"), r"ready")
        self.assertIn("1 / 1 subject checks", page.inner_text("#wiz-readiness .rp-count"))
        self.assertEqual(sent[0]["model_json"]["Nodes"][0]["Level"], "Run")
