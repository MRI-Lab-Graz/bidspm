"""F9: readiness must not say 'ready' for a confounds file that cannot match the BOLD."""
from lib.preflight import check_subject_task
from tests.preflight_support import confounds_for, make_trees

NEEDS = (set(), ["trans_x"], False, set())
HEADER = "trans_x\ttrans_y\ttrans_z"


def _ids(tmp_path, confounds=None, nvols=100, **kw):
    bids, fmri = make_trees(tmp_path, confounds=confounds, nvols=nvols, **kw)
    items, _, _ = check_subject_task(bids, fmri, "01", "x", "MNI", NEEDS)
    return {i["id"]: i for i in items}


def test_matching_rows_and_volumes_is_clean(tmp_path):
    assert _ids(tmp_path) == {}


def test_one_row_confounds_for_100_volumes(tmp_path):
    item = _ids(tmp_path, confounds=HEADER + "\n0\t0\t0\n")["confound_rows"]
    assert item["severity"] == "error"
    assert "confounds has 1 rows but the BOLD has 100 volumes" in item["message"]


def test_header_only_confounds(tmp_path):
    item = _ids(tmp_path, confounds=HEADER + "\n")["confound_rows"]
    assert item["severity"] == "error" and "no data rows" in item["message"]


def test_header_only_without_trailing_newline(tmp_path):
    assert "confound_rows" in _ids(tmp_path, confounds=HEADER)


def test_row_count_without_trailing_newline_still_matches(tmp_path):
    assert _ids(tmp_path, confounds=confounds_for(100).rstrip("\n")) == {}


def test_non_numeric_first_row(tmp_path):
    ids = _ids(tmp_path, confounds=HEADER + "\n" + "abc\t0\t0\n" + "0\t0\t0\n" * 99)
    assert ids["confound_values"]["severity"] == "error"
    assert "trans_x" in ids["confound_values"]["message"] and "abc" in ids["confound_values"]["message"]
    assert "confound_rows" not in ids


def test_non_numeric_in_unused_column_is_ignored(tmp_path):
    assert _ids(tmp_path, confounds="trans_x\tjunk\nn/a\tabc\n" + "0\tabc\n" * 99) == {}


def test_unreadable_bold_header_skips_the_row_check(tmp_path):
    bids, fmri = make_trees(tmp_path, confounds=HEADER + "\n0\t0\t0\n")
    for p in fmri.rglob("*desc-preproc_bold.nii.gz"):
        p.write_bytes(b"not a nifti")
    items, _, _ = check_subject_task(bids, fmri, "01", "x", "MNI", NEEDS)
    assert "confound_rows" not in {i["id"] for i in items}


def test_run_entities_pair_each_confounds_file_with_its_own_bold(tmp_path):
    bids, fmri = make_trees(tmp_path)
    func = fmri / "sub-01" / "func"
    import nibabel as nib
    import numpy as np
    nib.save(nib.Nifti1Image(np.zeros((2, 2, 2, 10), "f4"), np.eye(4)), func / "sub-01_task-x_run-1_space-MNI_desc-preproc_bold.nii.gz")
    (func / "sub-01_task-x_run-1_desc-confounds_timeseries.tsv").write_text(confounds_for(10))
    items, _, _ = check_subject_task(bids, fmri, "01", "x", "MNI", NEEDS)
    # the run-less 100-row file matches several BOLD files -> skipped; run-1 file has 10 rows for 10 volumes
    assert "confound_rows" not in {i["id"] for i in items}
