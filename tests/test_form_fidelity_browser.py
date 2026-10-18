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
        # initApp is done once the model workspace has loaded (it runs after the form was filled from the project)
        page.wait_for_function("typeof modelEditorDraft === 'object' && modelEditorDraft !== null")
        page.wait_for_load_state("networkidle")  # the form fill after loadProjectConfig awaits task/space requests
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


if __name__ == "__main__":
    unittest.main()
