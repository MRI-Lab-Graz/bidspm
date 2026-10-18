"""The forms must not rewrite what the user did not touch (exploratory findings F6, F7, F8, F13, M3, M5-M8, ...).

Each test drives the real page with the inputs from the exploratory repro and reads the result back from the
saved model file or the project configuration.
"""
import copy
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from tests.browser_support import (MODEL, chromium_available, go_to_stage, make_dataset, post_json, start_server,
                                   sync_playwright)


def get_json(url):
    return json.loads(urllib.request.urlopen(url, timeout=20).read())


@unittest.skipUnless(chromium_available(), "Playwright + Chromium not available")
class FidelityCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        make_dataset(cls.root)
        cls.server, cls.base, _ = start_server(cls.root)
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(headless=True)
        cls.counter = 0

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

    def new_project(self, model=None, **config):
        """A project over the shared dataset; `model` (a dict) is written to its own model file."""
        type(self).counter += 1
        path = self.root / f"model_{self.counter}.json"
        path.write_text(json.dumps(model if model is not None else MODEL))
        self.model_path = path
        cfg = {"bids_folder": str(self.root / "bids"), "derivatives_folder": str(self.root / "derivs"),
               "models_file": str(path), "tasks": ["motor"]}
        cfg.update(config)
        self.pid = post_json(self.base + "/api/projects", {"name": f"p{self.counter}", "config": cfg})["project"]["id"]
        return self.pid

    def project_config(self):
        return get_json(f"{self.base}/api/projects/{self.pid}")["config"]

    def open(self, url, stage=None):
        page = self.browser.new_page()
        self.pages.append(page)
        page.on("dialog", lambda d: (self.dialogs.append(d.message), d.dismiss()))
        page.goto(self.base + url, wait_until="load")
        if stage:
            go_to_stage(page, stage)
        return page

    def open_analysis(self, stage=None):
        page = self.open(f"/analysis/{self.pid}", stage)
        page.wait_for_function("document.body.dataset.ready === '1'")  # initApp done: form filled, model loaded
        return page


class TestModelRoundTrip(FidelityCase):
    def open_model(self, **config):
        return self.open_analysis("model")

    def type_into_options_field(self, page, text):
        page.evaluate("""text => {
            const row = Array.from(document.querySelectorAll('#model-editor-accordion .json-row'))
                .find(r => r.querySelector('.json-path')?.textContent.endsWith('.Options.HighPassFilterCutoffHz'));
            const input = row.querySelector('input');
            input.type = 'text';  // a number input refuses 1e999 itself; the exploratory repro pasted it
            input.value = text;
            input.dispatchEvent(new Event('change', {bubbles: true}));
        }""", text)

    def save_model(self, page):
        page.evaluate("document.getElementById('btn-save-model-editor').click()")
        page.wait_for_function("document.getElementById('model-editor-status').textContent.includes('Model saved')")

    def test_saving_without_edits_keeps_the_model_as_it_was(self):
        model = copy.deepcopy(MODEL)
        model["Nodes"][0]["Model"]["X"] = ["trial_type.a", 1, 2.5, {"k": [1]}, " trial_type.b ", "trial_type.a", "trial_type.b"]
        self.new_project(model)
        page = self.open_model()
        self.save_model(page)
        saved = json.loads(self.model_path.read_text())
        self.assertEqual(saved["Nodes"][0]["Model"]["X"], model["Nodes"][0]["Model"]["X"])
        self.assertIs(type(saved["Nodes"][0]["Model"]["X"][1]), int)

    def test_saving_without_edits_keeps_dataset_nodes_exactly(self):
        model = copy.deepcopy(MODEL)
        model["Nodes"] += [
            {"Level": "Dataset", "Name": "ds_x", "GroupBy": ["contrast"],
             "Model": {"X": [1, {"a": 1}, "  padded "], "Type": "glm"}},
            {"Level": "Dataset", "Name": "ds_nomodel", "GroupBy": ["contrast"]},
        ]
        self.new_project(model)
        page = self.open_model()
        self.save_model(page)
        saved = self.model_path.read_text()
        self.assertEqual(json.dumps(json.loads(saved)), json.dumps(model))

    def test_empty_contrasts_are_dropped_on_save(self):
        # Deliberate (not an F6 regression): empty Contrasts lists are invalid per the Stats Models spec.
        model = copy.deepcopy(MODEL)
        model["Nodes"][0]["Contrasts"] = []
        model["Nodes"][0]["DummyContrasts"] = {"Contrasts": [], "Test": "t"}
        self.new_project(model)
        page = self.open_model()
        self.save_model(page)
        node = json.loads(self.model_path.read_text())["Nodes"][0]
        self.assertNotIn("Contrasts", node)
        self.assertEqual(node["DummyContrasts"], {"Test": "t"})

    def test_a_cleared_number_field_removes_the_key_instead_of_writing_zero(self):
        model = copy.deepcopy(MODEL)
        model["Nodes"][0]["Model"]["Options"] = {"HighPassFilterCutoffHz": 0.008}
        self.new_project(model)
        page = self.open_model()
        self.type_into_options_field(page, "")
        self.save_model(page)
        options = json.loads(self.model_path.read_text())["Nodes"][0]["Model"].get("Options", {})
        self.assertNotIn("HighPassFilterCutoffHz", options)

    def test_a_non_finite_number_is_refused_with_a_message(self):
        model = copy.deepcopy(MODEL)
        model["Nodes"][0]["Model"]["Options"] = {"HighPassFilterCutoffHz": 0.008}
        self.new_project(model)
        page = self.open_model()
        self.type_into_options_field(page, "1e999")
        page.wait_for_function("document.getElementById('model-editor-status').textContent.includes('number')")
        self.save_model(page)
        self.assertEqual(json.loads(self.model_path.read_text())["Nodes"][0]["Model"]["Options"],
                         {"HighPassFilterCutoffHz": 0.008})

    def status(self, page):
        return page.inner_text("#model-editor-status")

    def field_value(self, page, suffix):
        return page.evaluate("""suffix => Array.from(document.querySelectorAll('#model-editor-accordion .json-row'))
            .find(r => r.querySelector('.json-path')?.textContent.endsWith(suffix)).querySelector('input').value""", suffix)

    def test_the_refusal_names_the_field_and_keeps_the_previous_value(self):
        model = copy.deepcopy(MODEL)
        model["Nodes"][0]["Model"]["Options"] = {"HighPassFilterCutoffHz": 0.008}
        self.new_project(model)
        page = self.open_model()
        self.type_into_options_field(page, "1e999")
        self.assertIn("HighPassFilterCutoffHz must be a finite number", self.status(page))
        self.assertEqual(self.field_value(page, ".HighPassFilterCutoffHz"), "0.008")

    def test_a_lone_minus_in_a_real_number_input_is_refused_not_deleted(self):
        model = copy.deepcopy(MODEL)
        model["Nodes"][0]["Model"]["Options"] = {"HighPassFilterCutoffHz": 0.008}
        self.new_project(model)
        page = self.open_model()
        page.evaluate("""() => { const i = Array.from(document.querySelectorAll('#model-editor-accordion .json-row'))
            .find(r => r.querySelector('.json-path')?.textContent.endsWith('.HighPassFilterCutoffHz')).querySelector('input');
            for (let c = i.closest('.collapse'); c; c = c.parentElement?.closest('.collapse')) c.classList.add('show');
            i.focus(); i.select(); }""")
        page.keyboard.type("-")
        page.keyboard.press("Tab")
        self.assertIn("HighPassFilterCutoffHz must be a finite number", self.status(page))
        self.assertEqual(self.field_value(page, ".HighPassFilterCutoffHz"), "0.008")

    def test_a_non_positive_high_pass_cutoff_is_refused(self):
        model = copy.deepcopy(MODEL)
        model["Nodes"][0]["Model"]["Options"] = {"HighPassFilterCutoffHz": 0.008}
        self.new_project(model)
        page = self.open_model()
        for bad in ("0", "-0.5"):
            self.type_into_options_field(page, bad)
            self.assertIn("HighPassFilterCutoffHz must be greater than 0", self.status(page))
            self.assertEqual(self.field_value(page, ".HighPassFilterCutoffHz"), "0.008")


class TestProjectFormValues(FidelityCase):
    def set_and_save(self, page, **values):
        for key, value in values.items():
            page.eval_on_selector(f"#input-{key}", "(e, v) => { e.value = v; e.dispatchEvent(new Event('change')); }", value)
        page.evaluate("document.getElementById('btn-save-only').click()")

    def test_zero_fwhm_and_verbosity_are_kept(self):
        self.new_project()
        page = self.open_analysis("options")
        self.set_and_save(page, FWHM="0", VERBOSITY="0")
        page.wait_for_function("document.getElementById('validation-result').textContent.includes('saved')")
        config = self.project_config()
        self.assertEqual((config["fwhm"], config["verbosity"]), (0, 0))
        page = self.open_analysis("options")
        self.assertEqual(page.input_value("#input-FWHM"), "0")
        self.assertEqual(page.input_value("#input-VERBOSITY"), "0")

    def test_negative_fwhm_is_refused_with_a_message(self):
        self.new_project(fwhm=5)
        page = self.open_analysis("options")
        self.set_and_save(page, FWHM="-1")
        page.wait_for_function("document.getElementById('validation-result').textContent.includes('FWHM')")
        self.assertEqual(self.project_config()["fwhm"], 5)


class TestEmptyRunOptionsRefused(FidelityCase):
    def refused(self, field, label):
        self.new_project(fwhm=5, verbosity=1)
        page = self.open_analysis("options")
        page.eval_on_selector(f"#input-{field}", "e => { e.value = ''; e.dispatchEvent(new Event('change')); }")
        page.evaluate("document.getElementById('btn-save-only').click()")
        page.wait_for_function("t => document.getElementById('validation-result').textContent.includes(t)", arg=label)
        self.assertEqual(page.input_value(f"#input-{field}"), "")
        config = self.project_config()
        self.assertEqual((config["fwhm"], config["verbosity"]), (5, 1))

    def test_empty_fwhm_is_refused_not_saved_as_6(self):
        self.refused("FWHM", "FWHM")

    def test_empty_verbosity_is_refused_not_saved_as_2(self):
        self.refused("VERBOSITY", "Verbosity")


class TestEditProjectDialog(FidelityCase):
    def test_edit_without_changes_keeps_an_unlisted_space_and_the_other_image(self):
        self.new_project(space="MNI152NLin2009cAsym:res-2", container_type="apptainer",
                         apptainer_image="/x/a.sif", docker_image="myrepo/custom:1")
        before = self.project_config()
        page = self.open("/projects")
        page.evaluate(f"document.querySelector('.btn-edit-project[data-project-id=\"{self.pid}\"]').click()")
        page.wait_for_selector("#edit-project-name", state="visible")
        page.wait_for_function("document.getElementById('edit-project-name').value !== ''")
        page.click("#btn-save-project")
        page.wait_for_function("document.querySelector('#editProjectModal.show') === null")
        after = self.project_config()
        for key in ("space", "container_type", "apptainer_image", "docker_image", "bids_folder"):
            self.assertEqual(after[key], before[key], key)


class TestContrastBuilderValidation(FidelityCase):
    def model_with_contrast(self):
        model = copy.deepcopy(MODEL)
        model["Nodes"][0]["Contrasts"] = [{"Name": "A", "ConditionList": ["trial_type.a"], "Weights": [1], "Test": "t"}]
        return model

    def open_builder(self):
        self.new_project(self.model_with_contrast())
        page = self.open_analysis("model")
        page.click("#btn-open-contrast-builder")
        page.wait_for_selector("#cb-contrast-list .cb-contrast-card")
        return page

    def test_duplicate_names_and_empty_condition_lists_are_refused(self):
        page = self.open_builder()
        page.click("#cb-add-contrast-btn")  # a second, empty contrast
        page.locator(".cb-contrast-name-input").nth(1).fill("A")
        page.click("#cb-apply-btn")
        status = page.inner_text("#cb-status")
        self.assertIn("unique", status)
        self.assertIn("no conditions", status)
        self.assertEqual(len(page.evaluate("modelEditorDraft.Nodes[0].Contrasts")), 1)

    def test_an_empty_name_is_refused(self):
        page = self.open_builder()
        page.locator(".cb-contrast-name-input").first.fill("  ")
        page.click("#cb-apply-btn")
        self.assertIn("name", page.inner_text("#cb-status"))
        self.assertEqual(page.evaluate("modelEditorDraft.Nodes[0].Contrasts[0].Name"), "A")

    def test_an_empty_or_non_numeric_weight_is_refused_and_kept(self):
        page = self.open_builder()
        for bad in ("", "abc", "1e999"):
            page.eval_on_selector(".cb-weight-input", "(i, v) => { i.type = 'text'; i.value = v; i.dispatchEvent(new Event('change')); }", bad)
            self.assertIn("Weight must be a finite number", page.inner_text("#cb-status"))
            self.assertEqual(page.input_value(".cb-weight-input"), "1")
            page.evaluate("document.getElementById('cb-status').innerHTML = ''")
        page.click("#cb-apply-btn")
        self.assertEqual(page.evaluate("modelEditorDraft.Nodes[0].Contrasts[0].Weights"), [1])

    def test_a_valid_contrast_is_applied(self):
        page = self.open_builder()
        page.locator(".cb-contrast-name-input").first.fill("B")
        page.click("#cb-apply-btn")
        page.wait_for_function("document.getElementById('cb-status').textContent.includes('Applied')")
        self.assertEqual(page.evaluate("modelEditorDraft.Nodes[0].Contrasts[0].Name"), "B")


class TestProjectRunOptions(FidelityCase):
    def test_saved_tasks_missing_from_the_dataset_survive_a_save(self):
        model = copy.deepcopy(MODEL)  # the model lists the task too, and the page syncs the ticks from the model
        model["Input"]["task"] = ["motor", "ghost"]
        self.new_project(model, tasks=["motor", "ghost"])
        page = self.open_analysis("folders")
        self.assertIn("not found in BIDS", page.inner_text("#tasks-container"))
        page.evaluate("document.getElementById('btn-save-only').click()")
        page.wait_for_function("document.getElementById('validation-result').textContent.includes('saved')")
        self.assertEqual(sorted(self.project_config()["tasks"]), ["ghost", "motor"])

    def test_saved_tasks_are_not_called_missing_when_task_detection_failed(self):
        model = copy.deepcopy(MODEL)
        model["Input"]["task"] = ["motor", "ghost"]
        self.new_project(model, tasks=["motor", "ghost"])
        page = self.browser.new_page()
        self.pages.append(page)
        page.route("**/get_bids_tasks*", lambda route: route.fulfill(status=500, body="boom"))
        page.goto(f"{self.base}/analysis/{self.pid}", wait_until="load")
        go_to_stage(page, "folders")
        page.wait_for_function("typeof modelEditorDraft === 'object' && modelEditorDraft !== null")
        page.wait_for_function("document.querySelectorAll('#tasks-container .task-checkbox:checked').length === 2")
        text = page.inner_text("#tasks-container")
        self.assertIn("Error detecting tasks", text)
        self.assertNotIn("not found in BIDS", text)

    def test_run_options_are_restored_and_saved(self):
        self.new_project(actions=["smooth", "bms"], pilot=True, bms_models=["/m/a_smdl.json"], stats_workers=8,
                         node_name="variant1", skip_validation=False)
        page = self.open_analysis("options")
        checked = lambda: page.eval_on_selector_all("input[name=action]:checked", "els => els.map(e => e.value)")
        self.assertEqual(sorted(checked()), ["bms", "smooth"])
        self.assertTrue(page.is_checked("#pilot"))
        self.assertEqual(page.eval_on_selector_all("#bms-model-list input", "els => els.map(e => e.value)"), ["/m/a_smdl.json"])
        self.assertEqual(page.input_value("#stats_workers"), "8")
        self.assertEqual(page.input_value("#run_node_name"), "variant1")
        self.assertFalse(page.is_checked("#skip_validation"))
        page.fill("#stats_workers", "3")
        page.fill("#run_node_name", "variant2")
        page.eval_on_selector("#stats_workers", "e => e.dispatchEvent(new Event('change'))")
        page.evaluate("document.getElementById('btn-save-only').click()")
        page.wait_for_function("document.getElementById('validation-result').textContent.includes('saved')")
        config = self.project_config()
        self.assertEqual((config["stats_workers"], config["node_name"], config["bms_models"], config["skip_validation"]),
                         (3, "variant2", ["/m/a_smdl.json"], False))
        self.assertEqual(sorted(config["actions"]), ["bms", "smooth"])
        self.assertTrue(config["pilot"])

    def test_a_failing_save_says_so(self):
        self.new_project()
        page = self.open_analysis("options")
        page.route("**/api/projects/*/config", lambda route: route.fulfill(
            status=500, content_type="application/json", body=json.dumps({"error": "disk full"})))
        page.evaluate("document.getElementById('btn-save-only').click()")
        page.wait_for_function("document.getElementById('validation-result').textContent.includes('disk full')")
        self.assertNotIn("configuration saved", page.inner_text("#validation-result"))

    def test_the_apptainer_placeholder_is_not_saved_as_a_value(self):
        self.new_project()
        page = self.open_analysis("options")
        page.click("#options-advanced > summary")
        self.assertEqual(page.input_value("#input-apptainer_image"), "")
        self.assertTrue(page.get_attribute("#input-apptainer_image", "placeholder").endswith(".sif"))
        page.evaluate("document.getElementById('btn-save-only').click()")
        page.wait_for_function("document.getElementById('validation-result').textContent.includes('saved')")
        self.assertEqual(self.project_config()["apptainer_image"], "")


class TestModelEditorNames(FidelityCase):
    def two_node_model(self):
        model = copy.deepcopy(MODEL)
        model["Nodes"].append({"Level": "Dataset", "Name": "dataset", "GroupBy": ["contrast"],
                               "Model": {"X": [1], "Type": "glm"}, "DummyContrasts": {"Test": "t"}})
        model["Edges"] = [{"Source": "run", "Destination": "dataset"}]
        return model

    def test_renaming_a_node_to_an_existing_name_is_refused(self):
        self.new_project(self.two_node_model())
        page = self.open_analysis("model")
        page.evaluate("""() => {
            const input = Array.from(document.querySelectorAll('input')).filter(i => i.placeholder.startsWith('Node name'))[1];
            input.value = 'run';
            input.dispatchEvent(new Event('change', {bubbles: true}));
        }""")
        page.wait_for_function("document.getElementById('model-editor-status').textContent.includes('already')")
        self.assertEqual(page.evaluate("modelEditorDraft.Nodes.map(n => n.Name)"), ["run", "dataset"])
        self.assertEqual(page.evaluate("modelEditorDraft.Edges"), [{"Source": "run", "Destination": "dataset"}])

    def test_regressor_names_are_compared_normalised_and_control_characters_refused(self):
        self.new_project()
        page = self.open_analysis("model")
        x = lambda: page.evaluate("modelEditorDraft.Nodes[0].Model.X")
        page.evaluate("addRegressorToModelX('Nodes[0].Model.X', 'caf\\u00e9')")
        page.evaluate("addRegressorToModelX('Nodes[0].Model.X', 'cafe\\u0301')")
        self.assertEqual(x().count("caf\u00e9"), 1)
        self.assertEqual(len(x()), 4)
        page.evaluate("addRegressorToModelX('Nodes[0].Model.X', 'a\\u0000b')")
        self.assertEqual(len(x()), 4)
        self.assertIn("control", page.inner_text("#model-editor-status"))


class TestProjectsPageDialogs(FidelityCase):
    def open_projects(self):
        return self.open("/projects")

    def test_a_description_with_line_breaks_survives_an_edit(self):
        self.new_project()
        post_json(f"{self.base}/api/projects", {"name": "multi", "description": "line1\nline2", "config": {}})
        pid = [p for p in get_json(f"{self.base}/api/projects")["projects"] if p["name"] == "multi"][0]["id"]
        page = self.open_projects()
        page.evaluate(f"document.querySelector('.btn-edit-project[data-project-id=\"{pid}\"]').click()")
        page.wait_for_function("document.getElementById('edit-project-name').value === 'multi'")
        page.click("#btn-save-project")
        page.wait_for_function("document.querySelector('#editProjectModal.show') === null")
        self.assertEqual(get_json(f"{self.base}/api/projects/{pid}")["description"], "line1\nline2")

    def test_a_duplicate_project_name_is_warned_about_but_allowed(self):
        self.new_project()
        existing = f"p{self.counter}"
        page = self.open_projects()
        page.click("#btn-new-project")
        page.fill("#project-name", f"  {existing.upper()} ")
        self.assertIn("already exists", page.inner_text("#project-name-warning"))
        self.assertTrue(page.is_enabled("#btn-create-project"))
        page.fill("#project-name", "a brand new name")
        self.assertEqual(page.inner_text("#project-name-warning").strip(), "")

    def test_editing_warns_about_another_projects_name_but_not_its_own(self):
        self.new_project()
        first = f"p{self.counter}"
        self.new_project()
        page = self.open_projects()
        page.evaluate(f"document.querySelector('.btn-edit-project[data-project-id=\"{self.pid}\"]').click()")
        page.wait_for_function("document.getElementById('edit-project-name').value !== ''")
        self.assertEqual(page.inner_text("#edit-project-name-warning").strip(), "")
        page.fill("#edit-project-name", first)
        self.assertIn("already exists", page.inner_text("#edit-project-name-warning"))


@unittest.skipUnless(chromium_available(), "Playwright + Chromium not available")
class TestValidatorModeStorage(FidelityCase):
    def test_a_garbage_stored_mode_falls_back_to_auto(self):
        self.new_project()
        page = self.browser.new_page()
        self.pages.append(page)
        page.add_init_script(f"localStorage.setItem('bidspm_validator_mode_{self.pid}', 'garbage')")
        page.goto(f"{self.base}/analysis/{self.pid}", wait_until="load")
        self.assertEqual(page.input_value("#validator-mode"), "auto")


class TestLegacySaveRefusals(FidelityCase):
    HOSTILE = '<img src=x onerror="window.__xss=1">'

    def refused_page(self, endpoint):
        page = self.open("/analysis")
        page.route(f"**/{endpoint}", lambda route: route.fulfill(
            status=400, content_type="application/json", body=json.dumps({"error": self.HOSTILE})))
        return page

    def assert_error_shown(self, page):
        page.wait_for_function("document.getElementById('validation-result').textContent.includes('onerror')")
        text = page.inner_text("#validation-result")
        self.assertIn(self.HOSTILE, text)
        self.assertNotIn("saved", text.lower())
        self.assertIsNone(page.evaluate("window.__xss"))

    def test_save_only_shows_the_servers_refusal(self):
        page = self.refused_page("save_settings")
        page.evaluate("document.getElementById('btn-save-only').click()")
        self.assert_error_shown(page)

    def test_save_and_start_stops_on_a_refusal_and_does_not_start(self):
        page = self.refused_page("save_settings")
        runs = []
        page.route("**/run", lambda route: (runs.append(route.request.url), route.abort()))
        page.evaluate("runStatsCoverageGate = async () => ({allow: true, subjectsOverride: []})")
        page.evaluate("document.getElementById('btn-save-start').click()")
        self.assert_error_shown(page)
        self.assertEqual(runs, [])


if __name__ == "__main__":
    unittest.main()
