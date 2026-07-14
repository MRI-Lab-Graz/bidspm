import tempfile
import unittest
from pathlib import Path

import lib.core as core
from lib.config import Config


def _make_config(root: Path) -> Config:
    wd = root / "wd"
    wd.mkdir(parents=True, exist_ok=True)
    return Config(
        WD=wd,
        BIDS_DIR=root / "bids",
        DERIVATIVES_DIR=root / "derivatives",
        SPACE="MNI152NLin2009cAsym",
        FWHM=6.0,
        MODELS_FILE="",
        TASKS=["motor"],
        FMRIPREP_DIR=root / "fmriprep",
        VERBOSITY=2,
        CONTAINER_TYPE="docker",
    )


class TestCheckDatasetEdgeFilters(unittest.TestCase):
    def test_no_dataset_nodes_returns_no_warnings(self):
        model = {"Nodes": [{"Name": "subject_level", "Level": "Subject"}]}
        self.assertEqual(core._check_dataset_edge_filters(model), [])

    def test_missing_filter_contrast_warns(self):
        model = {
            "Nodes": [{"Name": "group", "Level": "Dataset"}],
            "Edges": [{"Source": "subject_level", "Destination": "group"}],
        }
        warnings = core._check_dataset_edge_filters(model)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Filter.contrast is not set", warnings[0])

    def test_present_filter_contrast_silences_warning(self):
        model = {
            "Nodes": [{"Name": "group", "Level": "Dataset"}],
            "Edges": [{
                "Source": "subject_level", "Destination": "group",
                "Filter": {"contrast": ["motor_gt_rest"]},
            }],
        }
        self.assertEqual(core._check_dataset_edge_filters(model), [])

    def test_ignores_non_dict_edges(self):
        model = {
            "Nodes": [{"Name": "group", "Level": "Dataset"}],
            "Edges": ["not-a-dict"],
        }
        self.assertEqual(core._check_dataset_edge_filters(model), [])


class TestNormalizeLegacyModelKeys(unittest.TestCase):
    def test_renames_type_to_test_for_contrast(self):
        node = {"ConditionList": ["a"], "Weights": [1], "Type": "t"}
        fixes = core._normalize_legacy_model_keys(node)
        self.assertEqual(fixes, 1)
        self.assertEqual(node["Test"], "t")
        self.assertNotIn("Type", node)

    def test_renames_type_to_test_for_dummy_contrast(self):
        node = {"Contrasts": [{"Name": "a"}], "Type": "F"}
        fixes = core._normalize_legacy_model_keys(node)
        self.assertEqual(fixes, 1)
        self.assertEqual(node["Test"], "F")

    def test_adds_glm_type_for_model_node(self):
        node = {"X": ["intercept"]}
        fixes = core._normalize_legacy_model_keys(node)
        self.assertEqual(fixes, 1)
        self.assertEqual(node["Type"], "glm")

    def test_recurses_into_nested_lists_and_dicts(self):
        model = {"Nodes": [{"X": ["intercept"]}, {"ConditionList": ["a"], "Weights": [1], "Type": "pass"}]}
        fixes = core._normalize_legacy_model_keys(model)
        self.assertEqual(fixes, 2)

    def test_no_changes_needed_returns_zero(self):
        node = {"Name": "plain"}
        self.assertEqual(core._normalize_legacy_model_keys(node), 0)


class TestStripEmptyTransformations(unittest.TestCase):
    def test_removes_transformations_with_no_instructions(self):
        node = {"Transformations": {"Instructions": []}}
        fixes = core._strip_empty_transformations(node)
        self.assertEqual(fixes, 1)
        self.assertNotIn("Transformations", node)

    def test_keeps_transformations_with_instructions(self):
        node = {"Transformations": {"Instructions": [{"Name": "Demean"}]}}
        fixes = core._strip_empty_transformations(node)
        self.assertEqual(fixes, 0)
        self.assertIn("Transformations", node)

    def test_recurses_into_nested_structures(self):
        model = {"Nodes": [{"Transformations": {"Instructions": []}}]}
        fixes = core._strip_empty_transformations(model)
        self.assertEqual(fixes, 1)
        self.assertNotIn("Transformations", model["Nodes"][0])


class TestNormalizeSoftwareBlocks(unittest.TestCase):
    def test_list_of_strings_becomes_dict(self):
        node = {"Software": ["SPM", "FSL"]}
        fixes = core._normalize_software_blocks(node)
        self.assertEqual(fixes, 1)
        self.assertEqual(node["Software"], {"SPM": {}, "FSL": {}})

    def test_list_of_dicts_with_name_becomes_dict(self):
        node = {"Software": [{"Name": "SPM", "Version": "12"}]}
        core._normalize_software_blocks(node)
        self.assertEqual(node["Software"], {"SPM": {"Version": "12"}})

    def test_string_becomes_dict(self):
        node = {"Software": "SPM"}
        core._normalize_software_blocks(node)
        self.assertEqual(node["Software"], {"SPM": {}})

    def test_empty_list_becomes_none(self):
        node = {"Software": []}
        fixes = core._normalize_software_blocks(node)
        self.assertEqual(fixes, 1)
        self.assertIsNone(node["Software"])

    def test_no_software_key_no_change(self):
        node = {"Name": "plain"}
        self.assertEqual(core._normalize_software_blocks(node), 0)


class TestGetRunNodeName(unittest.TestCase):
    def test_finds_run_level_node(self):
        model = {"Nodes": [{"Name": "subject_level", "Level": "Subject"}, {"Name": "run_level", "Level": "Run"}]}
        self.assertEqual(core._get_run_node_name(model), "run_level")

    def test_falls_back_to_first_node_when_no_run_level(self):
        model = {"Nodes": [{"Name": "only_node", "Level": "Subject"}]}
        self.assertEqual(core._get_run_node_name(model), "only_node")

    def test_returns_none_when_no_nodes(self):
        self.assertIsNone(core._get_run_node_name({"Nodes": []}))


class TestNormalizeNodeLabel(unittest.TestCase):
    def test_strips_non_alphanumerics_and_lowercases(self):
        self.assertEqual(core._normalize_node_label("Subject-Level_1"), "subjectlevel1")

    def test_handles_none(self):
        self.assertEqual(core._normalize_node_label(None), "")


class TestAtlasCacheIsWarm(unittest.TestCase):
    def test_false_when_cache_dir_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_config(Path(tmp))
            self.assertFalse(core._atlas_cache_is_warm(config))

    def test_true_when_all_atlas_files_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_config(Path(tmp))
            atlas_dir = config.WD / "atlas"
            atlas_dir.mkdir(parents=True, exist_ok=True)
            for filename in core._ATLAS_CACHE_FILES:
                (atlas_dir / filename).write_text("", encoding="utf-8")
            self.assertTrue(core._atlas_cache_is_warm(config))

    def test_false_when_one_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = _make_config(Path(tmp))
            atlas_dir = config.WD / "atlas"
            atlas_dir.mkdir(parents=True, exist_ok=True)
            for filename in core._ATLAS_CACHE_FILES[:-1]:
                (atlas_dir / filename).write_text("", encoding="utf-8")
            self.assertFalse(core._atlas_cache_is_warm(config))


if __name__ == "__main__":
    unittest.main()
