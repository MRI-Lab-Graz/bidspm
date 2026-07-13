import base64
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np
from scipy.io import savemat

from lib import report_generator as rg


def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal valid-looking bytes; report_generator never decodes the image,
    # only base64-encodes the raw bytes for embedding.
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)


class TestSmallHelpers(unittest.TestCase):
    def test_b64_returns_data_uri(self):
        with TemporaryDirectory() as tmp:
            png = Path(tmp) / "fig.png"
            _write_png(png)
            uri = rg._b64(png)
            self.assertTrue(uri.startswith("data:image/png;base64,"))
            decoded = base64.b64decode(uri.split(",", 1)[1])
            self.assertEqual(decoded, png.read_bytes())

    def test_action_from_filename_matches_known_suffix(self):
        self.assertEqual(rg._action_from_filename("202601010000_1_sub-01_task-motor_realign.png"), "realign")
        self.assertEqual(rg._action_from_filename("sub-01_ses-1_qa.png"), "qa")

    def test_action_from_filename_falls_back_to_figure(self):
        self.assertEqual(rg._action_from_filename("no-suffix-match"), "figure")

    def test_read_json_safe_success_and_failure(self):
        with TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.json"
            good.write_text(json.dumps({"a": 1}), encoding="utf-8")
            self.assertEqual(rg._read_json_safe(good), {"a": 1})

            missing = Path(tmp) / "missing.json"
            self.assertIsNone(rg._read_json_safe(missing))

            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            self.assertIsNone(rg._read_json_safe(bad))

    def test_read_text_safe_success_and_failure(self):
        with TemporaryDirectory() as tmp:
            good = Path(tmp) / "note.md"
            good.write_text("hello", encoding="utf-8")
            self.assertEqual(rg._read_text_safe(good), "hello")
            self.assertEqual(rg._read_text_safe(Path(tmp) / "missing.md"), "")

    def test_parse_csv_table_success(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "contrast_results.csv"
            csv_path.write_text("name,t,p\nA,1.2,0.01\nB,2.3,0.02\n", encoding="utf-8")
            table = rg._parse_csv_table(csv_path)
            self.assertIsNotNone(table)
            self.assertEqual(table["name"], "contrast results")
            self.assertEqual(table["columns"], ["name", "t", "p"])
            self.assertEqual(len(table["rows"]), 2)

    def test_parse_csv_table_empty_returns_none(self):
        with TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "empty.csv"
            csv_path.write_text("name,t,p\n", encoding="utf-8")
            self.assertIsNone(rg._parse_csv_table(csv_path))

    def test_parse_csv_table_missing_file_returns_none(self):
        self.assertIsNone(rg._parse_csv_table(Path("/no/such/file.csv")))

    def test_ensure_list_variants(self):
        self.assertEqual(rg._ensure_list(None), [])
        self.assertEqual(rg._ensure_list([1, 2]), [1, 2])
        self.assertEqual(rg._ensure_list((1, 2)), [1, 2])
        self.assertEqual(rg._ensure_list("solo"), ["solo"])
        self.assertEqual(rg._ensure_list(np.array([])).__len__(), 0)
        self.assertEqual(list(rg._ensure_list(np.array([1, 2, 3]))), [1, 2, 3])


class TestSpmMatLoading(unittest.TestCase):
    def _make_spm_mat(self, tmp_dir: Path) -> Path:
        spm_path = tmp_dir / "SPM.mat"
        savemat(str(spm_path), {
            "SPM": {
                "xX": {
                    "X": np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]),
                    "name": np.array(["reg1", "reg2"], dtype=object),
                },
                "xCon": {
                    "name": "con1",
                    "STAT": "T",
                    "c": np.array([1.0, 0.0]),
                },
            }
        })
        return spm_path

    def test_load_spm_struct_success(self):
        with TemporaryDirectory() as tmp:
            spm_path = self._make_spm_mat(Path(tmp))
            spm = rg._load_spm_struct(spm_path)
            self.assertIsNotNone(spm)
            self.assertEqual(spm.xCon.name, "con1")

    def test_load_spm_struct_failure_returns_none(self):
        with TemporaryDirectory() as tmp:
            bad = Path(tmp) / "SPM.mat"
            bad.write_text("not a mat file", encoding="utf-8")
            self.assertIsNone(rg._load_spm_struct(bad))

    def test_design_matrix_data_uri_renders_png(self):
        with TemporaryDirectory() as tmp:
            spm_path = self._make_spm_mat(Path(tmp))
            spm = rg._load_spm_struct(spm_path)
            uri = rg._design_matrix_data_uri(spm)
            self.assertIsNotNone(uri)
            self.assertTrue(uri.startswith("data:image/png;base64,"))

    def test_design_matrix_data_uri_returns_none_on_bad_input(self):
        self.assertIsNone(rg._design_matrix_data_uri(SimpleNamespace(xX=SimpleNamespace(X=None, name=[]))))

    def test_spm_contrasts_table_builds_rows(self):
        with TemporaryDirectory() as tmp:
            spm_path = self._make_spm_mat(Path(tmp))
            spm = rg._load_spm_struct(spm_path)
            table = rg._spm_contrasts_table(spm, "subjectLevel")
            self.assertIsNotNone(table)
            self.assertEqual(table["name"], "Contrasts — subjectLevel")
            self.assertEqual(table["rows"][0]["Name"], "con1")
            self.assertEqual(table["rows"][0]["Type"], "T")

    def test_spm_contrasts_table_returns_none_when_no_xcon(self):
        self.assertIsNone(rg._spm_contrasts_table(SimpleNamespace(), "label"))


class TestCollectSubjectAndDiscovery(unittest.TestCase):
    def test_collect_subject_gathers_figures_tables_and_boilerplate(self):
        with TemporaryDirectory() as tmp:
            derivatives = Path(tmp) / "derivatives"
            stats_dir = derivatives / "bidspm-stats" / "sub-01"

            fig_png = stats_dir / "figures" / "202601010000_1_sub-01_task-motor_realign.png"
            _write_png(fig_png)

            results_png = stats_dir / "results" / "sub-01_task-motor_ffx.png"
            _write_png(results_png)
            results_csv = stats_dir / "results" / "contrast_table.csv"
            results_csv.parent.mkdir(parents=True, exist_ok=True)
            results_csv.write_text("name,t\nA,1.0\n", encoding="utf-8")

            boiler_dir = derivatives / "reports"
            boiler_dir.mkdir(parents=True, exist_ok=True)
            (boiler_dir / "stats_model-demo_citation.md").write_text("Cite us.", encoding="utf-8")

            subject = rg._collect_subject("01", derivatives, ["motor"], model_name="demo")

            self.assertEqual(subject.label, "01")
            captions = {f.caption for f in subject.figures}
            self.assertIn("Realignment (motion correction)", captions)
            self.assertEqual(len(subject.contrast_tables), 1)
            self.assertIn("Cite us.", subject.boilerplate)

    def test_collect_subject_handles_missing_dirs(self):
        with TemporaryDirectory() as tmp:
            derivatives = Path(tmp) / "derivatives"
            subject = rg._collect_subject("02", derivatives, ["rest"])
            self.assertEqual(subject.figures, [])
            self.assertEqual(subject.contrast_tables, [])
            self.assertEqual(subject.boilerplate, "")

    def test_discover_subjects_dedupes_across_pipelines(self):
        with TemporaryDirectory() as tmp:
            derivatives = Path(tmp)
            (derivatives / "bidspm-preproc" / "sub-01").mkdir(parents=True)
            (derivatives / "bidspm-stats" / "sub-01").mkdir(parents=True)
            (derivatives / "bidspm-stats" / "sub-02").mkdir(parents=True)
            self.assertEqual(rg._discover_subjects(derivatives), ["01", "02"])

    def test_detect_dataset_name_from_description(self):
        with TemporaryDirectory() as tmp:
            derivatives = Path(tmp) / "derivatives"
            derivatives.mkdir(parents=True)
            (derivatives / "dataset_description.json").write_text(
                json.dumps({"Name": "My Study"}), encoding="utf-8"
            )
            self.assertEqual(rg._detect_dataset_name(derivatives), "My Study")

    def test_detect_dataset_name_falls_back_to_parent_dirname(self):
        with TemporaryDirectory() as tmp:
            derivatives = Path(tmp) / "study_root" / "derivatives"
            derivatives.mkdir(parents=True)
            self.assertEqual(rg._detect_dataset_name(derivatives), "study_root")

    def test_detect_bidspm_version_found_and_missing(self):
        with TemporaryDirectory() as tmp:
            derivatives = Path(tmp)
            stats_dir = derivatives / "bidspm-stats"
            stats_dir.mkdir(parents=True)
            (stats_dir / "dataset_description.json").write_text(
                json.dumps({"GeneratedBy": [{"Version": "4.0.0"}]}), encoding="utf-8"
            )
            self.assertEqual(rg._detect_bidspm_version(derivatives), "4.0.0")

            empty_derivatives = Path(tmp) / "other"
            empty_derivatives.mkdir()
            self.assertEqual(rg._detect_bidspm_version(empty_derivatives), "unknown")


class TestGenerateReports(unittest.TestCase):
    def _build_minimal_dataset(self, derivatives: Path) -> None:
        (derivatives / "bidspm-stats" / "sub-01").mkdir(parents=True)
        (derivatives / "bidspm-stats" / "sub-02").mkdir(parents=True)

    def test_generate_reports_writes_group_index_and_subject_pages(self):
        with TemporaryDirectory() as tmp:
            derivatives = Path(tmp) / "derivatives"
            self._build_minimal_dataset(derivatives)

            index_path = rg.generate_reports(derivatives, tasks=["motor"], dataset_name="Demo Study")

            self.assertTrue(index_path.exists())
            self.assertIn("Demo Study", index_path.read_text(encoding="utf-8"))
            self.assertTrue((derivatives / "reports" / "sub-01_report.html").exists())
            self.assertTrue((derivatives / "reports" / "sub-02_report.html").exists())

    def test_generate_reports_raises_when_no_subjects_found(self):
        with TemporaryDirectory() as tmp:
            derivatives = Path(tmp) / "derivatives"
            derivatives.mkdir(parents=True)
            with self.assertRaises(ValueError):
                rg.generate_reports(derivatives, tasks=["motor"])

    def test_generate_reports_restricts_rendering_to_subjects_to_render(self):
        with TemporaryDirectory() as tmp:
            derivatives = Path(tmp) / "derivatives"
            self._build_minimal_dataset(derivatives)

            rg.generate_reports(
                derivatives, tasks=["motor"], subjects_to_render=["01"],
            )

            self.assertTrue((derivatives / "reports" / "sub-01_report.html").exists())
            self.assertFalse((derivatives / "reports" / "sub-02_report.html").exists())
            # Group index always covers every subject regardless of the render subset.
            index_text = (derivatives / "reports" / "index.html").read_text(encoding="utf-8")
            self.assertIn("sub-01", index_text)
            self.assertIn("sub-02", index_text)


if __name__ == "__main__":
    unittest.main()
