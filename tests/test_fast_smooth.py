import gzip
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import nibabel as nib
import numpy as np

from lib import fast_smooth as fs
from lib.config import Config


def _make_config(root: Path, fwhm=6.0) -> Config:
    wd = root / "wd"
    bids_dir = root / "bids"
    derivatives_dir = root / "derivatives"
    fmriprep_dir = derivatives_dir / "fmriprep"
    for path in [wd, bids_dir, derivatives_dir, fmriprep_dir]:
        path.mkdir(parents=True, exist_ok=True)
    return Config(
        WD=wd,
        BIDS_DIR=bids_dir,
        DERIVATIVES_DIR=derivatives_dir,
        SPACE="MNI152NLin2009cAsym",
        FWHM=fwhm,
        MODELS_FILE="",
        TASKS=["motor"],
        FMRIPREP_DIR=fmriprep_dir,
        VERBOSITY=2,
        SUBJECTS=["01"],
        CONTAINER_TYPE="local",
    )


def _write_nifti(path: Path, shape=(4, 4, 4, 3)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.random.default_rng(0).random(shape).astype(np.float32)
    affine = np.eye(4)
    img = nib.Nifti1Image(data, affine)
    nib.save(img, str(path))


class TestSmthPath(unittest.TestCase):
    def test_smth_path_replaces_desc_preproc(self):
        preproc = Path("/deriv/sub-01_task-motor_desc-preproc_bold.nii")
        self.assertEqual(
            fs._smth_path(preproc, 6.0).name,
            "sub-01_task-motor_desc-smth6.0_bold.nii",
        )


class TestSmthSidecar(unittest.TestCase):
    def test_build_sidecar_extracts_raw_sources_and_fields(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            preproc_json = root / "sub-01_task-motor_desc-preproc_bold.json"
            preproc_json.write_text(json.dumps({
                "Sources": ["bids:raw:sub-01/func/sub-01_task-motor_bold.nii.gz", "other:thing"],
                "RepetitionTime": 2.0,
                "SliceTimingCorrected": True,
                "Unrelated": "ignored",
            }), encoding="utf-8")
            preproc_path = root / "sub-01_task-motor_desc-preproc_bold.nii"

            sidecar = fs._build_smth_sidecar(preproc_json, preproc_path, root, 6.0)

            self.assertEqual(sidecar["RawSources"], ["sub-01/func/sub-01_task-motor_bold.nii.gz"])
            self.assertEqual(sidecar["RepetitionTime"], 2.0)
            self.assertTrue(sidecar["SliceTimingCorrected"])
            self.assertNotIn("Unrelated", sidecar)
            self.assertEqual(sidecar["SpmFilename"], f"s6.0{preproc_path.name}")

    def test_build_sidecar_without_json_omits_optional_fields(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            preproc_path = root / "sub-01_task-motor_desc-preproc_bold.nii"
            sidecar = fs._build_smth_sidecar(root / "missing.json", preproc_path, root, 6.0)
            self.assertNotIn("RawSources", sidecar)
            self.assertNotIn("RepetitionTime", sidecar)
            self.assertEqual(sidecar["Description"], "RECOMMENDED")


class TestSmoothOneFile(unittest.TestCase):
    def test_smooth_one_file_preserves_affine_and_writes_sidecar(self):
        with TemporaryDirectory() as tmp:
            derivatives_root = Path(tmp)
            preproc_path = derivatives_root / "sub-01" / "sub-01_task-motor_desc-preproc_bold.nii"
            _write_nifti(preproc_path)

            out_path = fs.smooth_one_file(preproc_path, 6.0, derivatives_root)

            self.assertTrue(out_path.exists())
            self.assertIn("desc-smth6.0", out_path.name)

            out_img = nib.load(str(out_path))
            in_img = nib.load(str(preproc_path))
            self.assertTrue(np.allclose(out_img.affine, in_img.affine))
            self.assertEqual(int(out_img.header["qform_code"]), 2)
            self.assertEqual(int(out_img.header["sform_code"]), 2)

            sidecar_path = out_path.with_suffix("").with_suffix(".json")
            self.assertTrue(sidecar_path.exists())


class TestFmriprepToPreprocPath(unittest.TestCase):
    def test_strips_gz_suffix(self):
        fmriprep_root = Path("/fmriprep")
        preproc_root = Path("/preproc")
        src = fmriprep_root / "sub-01" / "func" / "sub-01_task-motor_bold.nii.gz"
        target = fs._fmriprep_to_preproc_path(src, fmriprep_root, preproc_root)
        self.assertEqual(target, preproc_root / "sub-01" / "func" / "sub-01_task-motor_bold.nii")


class TestGzipHelpers(unittest.TestCase):
    def test_gzip_uncompressed_size_matches_real_payload(self):
        with TemporaryDirectory() as tmp:
            gz_path = Path(tmp) / "data.nii.gz"
            payload = b"x" * 12345
            with gzip.open(gz_path, "wb") as f:
                f.write(payload)
            self.assertEqual(fs._gzip_uncompressed_size(gz_path), len(payload))

    def test_gzip_uncompressed_size_returns_none_for_missing_file(self):
        self.assertIsNone(fs._gzip_uncompressed_size(Path("/no/such/file.gz")))

    def test_is_complete_copy_true_when_sizes_match(self):
        with TemporaryDirectory() as tmp:
            payload = b"y" * 999
            gz_path = Path(tmp) / "src.nii.gz"
            with gzip.open(gz_path, "wb") as f:
                f.write(payload)
            dst = Path(tmp) / "dst.nii"
            dst.write_bytes(payload)
            self.assertTrue(fs._is_complete_copy(dst, gz_path))

    def test_is_complete_copy_false_when_truncated(self):
        with TemporaryDirectory() as tmp:
            payload = b"z" * 999
            gz_path = Path(tmp) / "src.nii.gz"
            with gzip.open(gz_path, "wb") as f:
                f.write(payload)
            dst = Path(tmp) / "dst.nii"
            dst.write_bytes(payload[:100])  # truncated / interrupted copy
            self.assertFalse(fs._is_complete_copy(dst, gz_path))

    def test_is_complete_copy_false_when_dst_missing(self):
        with TemporaryDirectory() as tmp:
            payload = b"w" * 50
            gz_path = Path(tmp) / "src.nii.gz"
            with gzip.open(gz_path, "wb") as f:
                f.write(payload)
            self.assertFalse(fs._is_complete_copy(Path(tmp) / "missing.nii", gz_path))


class TestCopyPreprocFromFmriprep(unittest.TestCase):
    def test_copies_new_files_and_sidecar_from_fmriprep(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _make_config(root)

            src = config.FMRIPREP_DIR / "sub-01" / "func" / (
                "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
            )
            src.parent.mkdir(parents=True, exist_ok=True)
            payload = b"payload-bytes"
            with gzip.open(src, "wb") as f:
                f.write(payload)
            src_json = src.with_suffix("").with_suffix(".json")
            src_json.write_text(json.dumps({"RepetitionTime": 2.0}), encoding="utf-8")

            copied = fs.copy_preproc_from_fmriprep(config, "01", "motor")

            self.assertEqual(len(copied), 1)
            dst = copied[0]
            self.assertTrue(dst.exists())
            self.assertEqual(dst.read_bytes(), payload)
            self.assertTrue(dst.with_suffix(".json").exists())

    def test_recopies_truncated_existing_copy(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _make_config(root)

            src = config.FMRIPREP_DIR / "sub-01" / "func" / (
                "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz"
            )
            src.parent.mkdir(parents=True, exist_ok=True)
            payload = b"full-payload-content"
            with gzip.open(src, "wb") as f:
                f.write(payload)

            preproc_root = config.DERIVATIVES_DIR / "bidspm-preproc"
            dst = fs._fmriprep_to_preproc_path(src, config.FMRIPREP_DIR, preproc_root)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(payload[:3])  # simulate interrupted prior copy

            copied = fs.copy_preproc_from_fmriprep(config, "01", "motor")

            self.assertEqual(copied[0].read_bytes(), payload)

    def test_falls_back_to_existing_preproc_when_fmriprep_dir_missing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _make_config(root)
            # No fMRIPrep subject dir created at all.
            preproc_root = config.DERIVATIVES_DIR / "bidspm-preproc" / "sub-01"
            existing = preproc_root / (
                "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-preproc_bold.nii"
            )
            existing.parent.mkdir(parents=True, exist_ok=True)
            existing.write_bytes(b"already-there")

            copied = fs.copy_preproc_from_fmriprep(config, "01", "motor")
            self.assertEqual(copied, [existing])

    def test_returns_empty_when_nothing_available(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _make_config(root)
            self.assertEqual(fs.copy_preproc_from_fmriprep(config, "01", "motor"), [])


class TestCopyConfoundsFromFmriprep(unittest.TestCase):
    def test_copies_confounds_tsv_and_json(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _make_config(root)

            src = config.FMRIPREP_DIR / "sub-01" / "func" / (
                "sub-01_task-motor_desc-confounds_timeseries.tsv"
            )
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text("a\tb\n1\t2\n", encoding="utf-8")
            src.with_suffix(".json").write_text("{}", encoding="utf-8")

            copied = fs.copy_confounds_from_fmriprep(config, "01", "motor")

            self.assertEqual(len(copied), 1)
            self.assertTrue(copied[0].exists())
            self.assertTrue(copied[0].with_suffix(".json").exists())

    def test_returns_empty_when_fmriprep_subject_dir_missing(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _make_config(root)
            self.assertEqual(fs.copy_confounds_from_fmriprep(config, "01", "motor"), [])


class TestSmoothSubject(unittest.TestCase):
    def test_no_input_when_nothing_available(self):
        with TemporaryDirectory() as tmp:
            config = _make_config(Path(tmp))
            result = fs.smooth_subject(config, "01", "motor")
            self.assertEqual(result["status"], "no_input")
            self.assertIn("sub-01", result["message"])

    def test_ok_smooths_available_file(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _make_config(root)
            preproc_root = config.DERIVATIVES_DIR / "bidspm-preproc"
            preproc_path = preproc_root / "sub-01" / (
                "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-preproc_bold.nii"
            )
            _write_nifti(preproc_path)

            result = fs.smooth_subject(config, "01", "motor")

            self.assertEqual(result["status"], "ok")
            smoothed = fs._smth_path(preproc_path, config.FWHM)
            self.assertTrue(smoothed.exists())

    def test_skipped_when_already_smoothed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _make_config(root)
            preproc_root = config.DERIVATIVES_DIR / "bidspm-preproc"
            preproc_path = preproc_root / "sub-01" / (
                "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-preproc_bold.nii"
            )
            _write_nifti(preproc_path)
            fs.smooth_one_file(preproc_path, config.FWHM, preproc_root)

            result = fs.smooth_subject(config, "01", "motor")
            self.assertEqual(result["status"], "skipped")

    def test_force_reprocesses_already_smoothed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _make_config(root)
            preproc_root = config.DERIVATIVES_DIR / "bidspm-preproc"
            preproc_path = preproc_root / "sub-01" / (
                "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-preproc_bold.nii"
            )
            _write_nifti(preproc_path)
            fs.smooth_one_file(preproc_path, config.FWHM, preproc_root)

            result = fs.smooth_subject(config, "01", "motor", force=True)
            self.assertEqual(result["status"], "ok")

    def test_error_status_when_smoothing_raises(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = _make_config(root)
            preproc_root = config.DERIVATIVES_DIR / "bidspm-preproc"
            preproc_path = preproc_root / "sub-01" / (
                "sub-01_task-motor_space-MNI152NLin2009cAsym_desc-preproc_bold.nii"
            )
            _write_nifti(preproc_path)

            with patch("lib.fast_smooth.smooth_one_file", side_effect=RuntimeError("boom")):
                result = fs.smooth_subject(config, "01", "motor")

            self.assertEqual(result["status"], "error")
            self.assertIn("boom", result["message"])


class TestSmoothSubjectsParallel(unittest.TestCase):
    def test_aggregates_results_across_subjects(self):
        with TemporaryDirectory() as tmp:
            config = _make_config(Path(tmp))
            results = fs.smooth_subjects_parallel(config, ["01", "02"], "motor", max_workers=1)

            self.assertEqual(set(results.keys()), {"01", "02"})
            for subject_result in results.values():
                self.assertEqual(subject_result["status"], "no_input")


if __name__ == "__main__":
    unittest.main()
