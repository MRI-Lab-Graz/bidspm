import tempfile
import unittest
from pathlib import Path

from tests.browser_support import (chromium_available, go_to_stage, make_dataset, post_json, start_server,
                                   sync_playwright)

STAGES = ["folders", "model", "options", "run"]
# One representative control per stage, plus ids that must stay in the DOM although hidden.
SAMPLE = {"folders": "#input-WD", "model": "#btn-create-model", "options": "#smooth", "run": "#btn-save-start"}
KEPT_IDS = ["input-WD", "input-BIDS_DIR", "input-DERIVATIVES_DIR", "input-FMRIPREP_DIR", "input-MODELS_FILE",
            "input-SPACE", "input-FWHM", "input-VERBOSITY", "tasks-container", "btn-check-paths", "btn-validate",
            "btn-preflight", "validator-mode", "preflight-panel", "preflight-note", "model-validation-status",
            "analysis-model-workspace-section", "smooth", "stats", "pilot", "stats_workers", "run_node_name",
            "input-docker_image", "estimation_engine", "btn-save-start", "btn-save-only", "btn-run-cached",
            "btn-stop", "btn-load-config", "run-issues-row", "terminal", "validation-result", "path-alerts"]


@unittest.skipUnless(chromium_available(), "Playwright + Chromium not available")
class TestAnalysisStages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        make_dataset(tmp)
        (tmp / "wd").mkdir()
        (tmp / "fmriprep").mkdir()
        cls.server, cls.base, cls.partial_id = start_server(tmp)  # WD and fMRIPrep folder empty: Folders incomplete
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
        tmp = Path(self.tmp.name)
        self.full_id = post_json(self.base + "/api/projects", {"name": "full", "config": {  # edits autosave: one each
            "output_folder": str(tmp / "wd"), "bids_folder": str(tmp / "bids"),
            "derivatives_folder": str(tmp / "derivs"), "fmriprep_folder": str(tmp / "fmriprep"),
            "models_file": str(tmp / "model.json"), "tasks": ["motor"], "space": "MNI152NLin2009cAsym", "fwhm": 6,
            "actions": ["smooth", "stats"]}})["project"]["id"]
        self.pages = []
        self.errors = []

    def tearDown(self):
        for p in self.pages:
            p.close()

    def open_page(self, pid=None, suffix="", init_script=None):
        page = self.browser.new_page()
        self.pages.append(page)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        if init_script:
            page.add_init_script(init_script)
        page.goto(f"{self.base}/analysis/{pid or self.full_id}{suffix}", wait_until="load")
        page.wait_for_function("window.analysisStages !== undefined")
        return page

    def current(self, page):
        return page.evaluate("analysisStages.current()")

    def test_first_visit_starts_at_first_incomplete_stage(self):
        self.assertEqual(self.current(self.open_page(self.partial_id)), "folders")
        self.assertEqual(self.current(self.open_page(self.full_id)), "run")  # nothing incomplete: review and run

    def test_only_current_stage_controls_are_visible_and_everything_stays_in_the_dom(self):
        page = self.open_page(self.partial_id)
        for name in STAGES:
            go_to_stage(page, name)
            for other, selector in SAMPLE.items():
                self.assertEqual(page.is_visible(selector), other == name, f"{selector} while on {name}")
        missing = page.evaluate("ids => ids.filter(i => !document.getElementById(i))", KEPT_IDS)
        self.assertEqual(missing, [])

    def test_run_controls_are_only_visible_in_the_run_stage(self):
        page = self.open_page()
        for name in STAGES:
            go_to_stage(page, name)
            for sel in ("#btn-save-start", "#terminal", "#btn-preflight", "#stage-summary"):
                self.assertEqual(page.is_visible(sel), name == "run", f"{sel} while on {name}")
            hidden = page.evaluate("document.getElementById('preflight-panel').closest('[data-stage]')"
                                   ".classList.contains('stage-hidden')")
            self.assertEqual(hidden, name != "run")

    def test_next_is_blocked_with_a_reason_until_the_fields_are_set(self):
        page = self.open_page(self.partial_id)
        self.assertFalse(page.is_enabled("#stage-next"))
        hint = page.inner_text("#stage-hint")
        self.assertIn("Working Directory", hint)
        page.fill("#input-WD", "/tmp/wd")
        self.assertIn("fMRIPrep", page.inner_text("#stage-hint"))
        page.fill("#input-FMRIPREP_DIR", "/tmp/fp")
        page.wait_for_function("document.getElementById('stage-hint').textContent.trim() === ''")
        self.assertTrue(page.is_enabled("#stage-next"))
        page.click("#stage-next")
        self.assertEqual(self.current(page), "model")

    def test_clicking_a_blocked_next_stays_and_opens_the_advanced_field(self):
        page = self.open_page(self.partial_id)
        page.fill("#input-WD", "/tmp/wd")
        page.fill("#input-FMRIPREP_DIR", "/tmp/fp")
        page.evaluate("""() => { const f = document.getElementById('input-DERIVATIVES_DIR'); f.value = '';
            f.dispatchEvent(new Event('input', {bubbles: true})); f.closest('details').open = false; }""")
        page.click("#stage-next", force=True)  # aria-disabled: Playwright would wait forever otherwise
        self.assertEqual(self.current(page), "folders")
        self.assertIn("Derivatives", page.inner_text("#stage-hint"))
        self.assertTrue(page.is_visible("#input-DERIVATIVES_DIR"))
        self.assertEqual(page.evaluate("document.activeElement.id"), "input-DERIVATIVES_DIR")

    def test_model_and_options_gate_next(self):
        page = self.open_page()
        go_to_stage(page, "model")
        page.fill("#input-MODELS_FILE", "")
        self.assertFalse(page.is_enabled("#stage-next"))
        self.assertIn("model", page.inner_text("#stage-hint").lower())
        page.fill("#input-MODELS_FILE", "/tmp/m.json")
        self.assertTrue(page.is_enabled("#stage-next"))
        go_to_stage(page, "options")
        page.uncheck("#smooth")
        page.uncheck("#stats")
        self.assertFalse(page.is_enabled("#stage-next"))
        self.assertIn("action", page.inner_text("#stage-hint").lower())
        page.check("#stats")
        self.assertTrue(page.is_enabled("#stage-next"))

    def test_back_and_jump_to_a_visited_stage(self):
        page = self.open_page()
        go_to_stage(page, "options")
        page.click("#stage-back")
        self.assertEqual(self.current(page), "model")
        go_to_stage(page, "run")
        page.click("[data-stage-btn=folders]")
        self.assertEqual(self.current(page), "folders")
        page.click("[data-stage-btn=options]")  # every earlier stage is valid
        self.assertEqual(self.current(page), "options")

    def test_jump_to_a_later_stage_is_refused_with_the_reason(self):
        page = self.open_page(self.partial_id)
        page.click("[data-stage-btn=model]")
        self.assertEqual(self.current(page), "folders")
        self.assertIn("Working Directory", page.inner_text("#stage-hint"))

    def test_last_stage_is_remembered_across_reload(self):
        page = self.open_page()
        go_to_stage(page, "options")
        page.reload(wait_until="load")
        page.wait_for_function("window.analysisStages !== undefined")
        self.assertEqual(self.current(page), "options")

    def test_remembered_stage_never_skips_an_incomplete_one(self):
        page = self.open_page(self.partial_id)
        page.evaluate("localStorage.setItem('bidspm_stage_' + currentProjectId, 'run')")
        page.reload(wait_until="load")
        page.wait_for_function("window.analysisStages !== undefined")
        self.assertEqual(self.current(page), "folders")

    def test_deep_link_wins_over_the_stored_stage(self):
        page = self.open_page()
        go_to_stage(page, "options")
        page = self.open_page(suffix="#stage=model")
        self.assertEqual(self.current(page), "model")

    def test_returning_from_the_transformer_builder_lands_on_the_model_stage(self):
        page = self.open_page(suffix="#analysis-model-workspace-section")
        self.assertEqual(self.current(page), "model")

    def test_summaries_describe_finished_stages_and_follow_field_changes(self):
        page = self.open_page()
        summary = lambda: page.inner_text("#stage-summary")
        self.assertIn("bids", summary())
        self.assertIn("MNI152NLin2009cAsym", summary())
        self.assertIn("model.json", summary())
        self.assertIn("smooth, stats", summary())
        page.evaluate("""() => { const f = document.getElementById('input-FWHM'); f.value = '8';
            f.dispatchEvent(new Event('input', {bubbles: true})); }""")
        page.wait_for_function("document.getElementById('stage-summary').textContent.includes('8 mm')")
        self.assertIn("model.json", page.inner_text("[data-stage-btn=model]"))
        self.assertIn("bids", page.inner_text("[data-stage-btn=folders]"))
        self.assertEqual(page.inner_text("[data-stage-btn=run] .stage-btn-summary").strip(), "")

    def test_summary_is_rendered_as_text(self):
        page = self.open_page()
        page.evaluate("""() => { const f = document.getElementById('input-MODELS_FILE'); f.value = '/x/<b>m.json';
            f.dispatchEvent(new Event('input', {bubbles: true})); }""")
        page.wait_for_function("document.getElementById('stage-summary').textContent.includes('<b>m.json')")
        self.assertEqual(page.locator("#stage-summary b, [data-stage-btn] b").count(), 0)

    def test_aria_current_follows_the_stage(self):
        page = self.open_page()
        for name in STAGES:
            go_to_stage(page, name)
            current = page.eval_on_selector_all("[data-stage-btn][aria-current]", "els => els.map(e => e.dataset.stageBtn)")
            self.assertEqual(current, [name])
            self.assertEqual(page.get_attribute(f"[data-stage-btn={name}]", "class").split().count("current"), 1)
        self.assertTrue(page.is_visible("nav[aria-label='Analysis stages']"))

    def test_keyboard_reaches_next_and_focus_lands_on_the_stage_heading(self):
        page = self.open_page()
        go_to_stage(page, "model")
        page.focus("[data-stage-btn=folders]")
        for _ in range(12):
            if page.evaluate("document.activeElement.id") == "stage-next":
                break
            page.keyboard.press("Tab")
        self.assertEqual(page.evaluate("document.activeElement.id"), "stage-next")
        page.keyboard.press("Enter")
        self.assertEqual(self.current(page), "options")
        self.assertEqual(page.evaluate("document.activeElement.id"), "stage-heading")
        self.assertIn("Options", page.inner_text("#stage-heading"))

    def test_page_works_when_localstorage_throws(self):
        page = self.open_page(init_script="""
            Storage.prototype.getItem = () => { throw new Error('denied'); };
            Storage.prototype.setItem = () => { throw new Error('denied'); };""")
        self.assertEqual(self.current(page), "run")
        page.click("[data-stage-btn=folders]")
        self.assertEqual(self.current(page), "folders")
        page.click("#stage-next")
        self.assertEqual(self.current(page), "model")
        self.assertEqual(self.errors, [])

    def test_blocked_run_brings_the_readiness_panel_into_view(self):
        page = self.open_page()
        blocked = ('{"error": "preflight failed", "preflight": {"verdict": "blocked", "checks": ['
                   '{"id": "x", "severity": "error", "subject": null, "message": "no fmriprep", "fix": "fix it"}]}}')
        page.route("**/run", lambda r: r.fulfill(status=400, body=blocked, content_type="application/json"))
        go_to_stage(page, "options")
        page.evaluate("startExecution({actions: ['smooth']})")
        page.wait_for_function("analysisStages.current() === 'run'")
        page.wait_for_selector("#preflight-panel .preflight-verdict")
        self.assertTrue(page.is_visible("#preflight-panel .preflight-verdict"))

    def test_failed_start_brings_the_terminal_into_view(self):
        page = self.open_page()
        page.route("**/run", lambda r: r.fulfill(status=500, body="boom", content_type="text/plain"))
        go_to_stage(page, "options")
        page.evaluate("startExecution({actions: ['smooth']})")
        page.wait_for_function("analysisStages.current() === 'run'")
        self.assertIn("ERROR", page.inner_text("#terminal"))
