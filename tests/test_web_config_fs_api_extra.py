import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bidspm_gui import app as flask_app


class TestCheckPathsRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app.config.update(TESTING=True)
        cls.client = flask_app.test_client()

    def test_check_paths_reports_existing_and_missing_and_defaults_models_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing_dir = Path(tmp) / "bids"
            existing_dir.mkdir()

            response = self.client.post(
                "/check_paths",
                json={"WD": str(existing_dir), "BIDS_DIR": str(Path(tmp) / "missing")},
            )

            payload = response.get_json()
            self.assertTrue(payload["WD"])
            self.assertFalse(payload["BIDS_DIR"])
            self.assertTrue(payload["MODELS_FILE"])  # unset MODELS_FILE defaults to True

    def test_check_paths_checks_models_file_when_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_file = Path(tmp) / "model.json"
            response = self.client.post("/check_paths", json={"MODELS_FILE": str(model_file)})
            self.assertFalse(response.get_json()["MODELS_FILE"])


class TestGetSchemaRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app.config.update(TESTING=True)
        cls.client = flask_app.test_client()

    def test_get_schema_returns_existing_schema_file(self):
        response = self.client.get("/get_schema")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)

    def test_get_schema_returns_empty_dict_when_missing(self):
        with patch("webapp.web_config_fs_api.os.path.exists", return_value=False):
            response = self.client.get("/get_schema")
        self.assertEqual(response.get_json(), {})


class TestValidateConfigMissingSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app.config.update(TESTING=True)
        cls.client = flask_app.test_client()

    def test_returns_404_when_schema_file_missing(self):
        with patch("webapp.web_config_fs_api.os.path.exists", return_value=False):
            response = self.client.post("/validate_config", json={"content": {}})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.get_json()["valid"])


class TestBrowseDefaultsAndFallback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app.config.update(TESTING=True)
        cls.client = flask_app.test_client()

    def test_browse_falls_back_to_cwd_for_nonexistent_path(self):
        response = self.client.get("/browse", query_string={"path": "/no/such/directory/at/all"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Path(response.get_json()["current_path"]).is_dir())

    def test_browse_uses_default_json_sif_suffix_filter_when_no_extensions_given(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "alpha.json").write_text("{}", encoding="utf-8")
            (root / "beta.sif").write_text("image", encoding="utf-8")
            (root / "gamma.txt").write_text("ignore", encoding="utf-8")

            response = self.client.get("/browse", query_string={"path": str(root)})
            names = {item["name"] for item in response.get_json()["items"]}

        self.assertIn("alpha.json", names)
        self.assertIn("beta.sif", names)
        self.assertNotIn("gamma.txt", names)


class TestLoadContainerFileDefaults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app.config.update(TESTING=True)
        cls.client = flask_app.test_client()

    def test_returns_default_payload_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            response = self.client.get(
                "/load_container_file", query_string={"path": str(Path(tmp) / "missing.json")},
            )
        payload = response.get_json()
        self.assertEqual(payload["container_type"], "apptainer")
        self.assertIn("apptainer_image", payload)


class TestBrowseExtensionsFilter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app.config.update(TESTING=True)
        cls.client = flask_app.test_client()

    def test_browse_filters_by_requested_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "model.smdl.json").write_text("{}", encoding="utf-8")
            (root / "notes.txt").write_text("hi", encoding="utf-8")

            response = self.client.get(
                "/browse", query_string={"path": str(root), "extensions": "json"},
            )
            names = {item["name"] for item in response.get_json()["items"] if item["type"] == "file"}
            self.assertIn("model.smdl.json", names)
            self.assertNotIn("notes.txt", names)


class TestSaveFileContentBranches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app.config.update(TESTING=True)
        cls.client = flask_app.test_client()

    def test_save_file_content_without_validate_json_writes_raw_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "notes.txt"
            response = self.client.post(
                "/file_content",
                json={"path": str(target), "content": "plain text", "validate_json": False},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(target.read_text(encoding="utf-8"), "plain text")

    def test_save_file_content_reports_generic_write_errors_as_500(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "notes.txt"
            with patch("webapp.web_config_fs_api.open", side_effect=OSError("disk full")):
                response = self.client.post(
                    "/file_content",
                    json={"path": str(target), "content": "x", "validate_json": False},
                )
        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.get_json()["success"])


class TestBrowseAndFileContentErrorBranches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flask_app.config.update(TESTING=True)
        cls.client = flask_app.test_client()

    def test_browse_reports_scandir_errors_as_500(self):
        with patch("webapp.web_config_fs_api.os.scandir", side_effect=PermissionError("denied")):
            response = self.client.get("/browse", query_string={"path": "/"})
        self.assertEqual(response.status_code, 500)
        self.assertIn("error", response.get_json())

    def test_file_content_get_reports_read_errors_as_500(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "file.txt"
            target.write_text("hi", encoding="utf-8")
            with patch("webapp.web_config_fs_api.open", side_effect=OSError("boom")):
                response = self.client.get("/file_content", query_string={"path": str(target)})
        self.assertEqual(response.status_code, 500)
        self.assertIn("Error reading file", response.get_data(as_text=True))

    def test_mkdir_reports_errors_as_500(self):
        with patch("webapp.web_config_fs_api.os.makedirs", side_effect=OSError("denied")):
            response = self.client.post("/mkdir", json={"path": "/no/permission/here"})
        self.assertEqual(response.status_code, 500)
        self.assertIn("error", response.get_json())

    def test_list_configs_returns_empty_list_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("webapp.web_config_fs_api.os.listdir", side_effect=OSError("denied")):
                response = self.client.get("/configs", query_string={"folder": tmp})
        self.assertEqual(response.get_json(), [])


if __name__ == "__main__":
    unittest.main()
