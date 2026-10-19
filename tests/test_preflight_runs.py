"""R2: readiness pairs events, preproc BOLD and confounds per run (BIDS entities) and checks every run."""
from lib.preflight import check_subject_task
from tests.preflight_support import confounds_for, make_trees

NEEDS = (set(), ["trans_x"], False, set())
LATE = "onset\tduration\ttrial_type\n100\t1\ta\n"  # 101 s, beyond a 10 x 2 s scan


def _items(bids, fmri, needs=NEEDS):
    items, _, _ = check_subject_task(bids, fmri, "01", "x", "MNI", needs)
    return items


def _one(items, id):
    found = [i for i in items if i["id"] == id]
    assert len(found) == 1, items
    return found[0]


def test_two_clean_runs_are_ready(tmp_path):
    assert _items(*make_trees(tmp_path, runs=("1", "2"))) == []


def test_scan_length_is_checked_for_every_run(tmp_path):
    bids, fmri = make_trees(tmp_path, runs=("1", "2"), nvols=10)
    (bids / "sub-01/func/sub-01_task-x_run-2_events.tsv").write_text(LATE)
    item = _one(_items(bids, fmri), "scan_length")
    assert "run-2" in item["message"] and item["severity"] == "warn"


def test_run_with_bold_but_no_events_is_an_error_naming_the_run(tmp_path):
    bids, fmri = make_trees(tmp_path, runs=("1", "2"))
    (bids / "sub-01/func/sub-01_task-x_run-2_events.tsv").unlink()
    item = _one(_items(bids, fmri), "run_unpaired")
    assert item["severity"] == "error" and "run-2" in item["message"] and "run-1" not in item["message"]


def test_run_with_events_but_no_bold_is_preproc_missing_naming_the_run(tmp_path):
    bids, fmri = make_trees(tmp_path, runs=("1", "2"))
    (fmri / "sub-01/func/sub-01_task-x_run-2_space-MNI_desc-preproc_bold.nii.gz").unlink()
    item = _one(_items(bids, fmri), "preproc_missing")
    assert item["severity"] == "error" and "run-2" in item["message"]


def test_run_without_confounds_is_named(tmp_path):
    bids, fmri = make_trees(tmp_path, runs=("1", "2"))
    (fmri / "sub-01/func/sub-01_task-x_run-2_desc-confounds_timeseries.tsv").unlink()
    item = _one(_items(bids, fmri), "confounds_missing")
    assert item["severity"] == "error" and "run-2" in item["message"]


def test_confound_rows_are_checked_per_run(tmp_path):
    bids, fmri = make_trees(tmp_path, runs=("1", "2"), nvols=10)
    (fmri / "sub-01/func/sub-01_task-x_run-1_desc-confounds_timeseries.tsv").write_text(confounds_for(9))
    item = _one(_items(bids, fmri), "confound_rows")
    assert "run-1" in item["message"] and "9 rows" in item["message"]


def test_sessions_are_paired_by_their_ses_entity(tmp_path):
    bids, fmri = make_trees(tmp_path, sessions=("1", "2"), runs=("1",))
    (bids / "sub-01/ses-2/func/sub-01_ses-2_task-x_run-1_events.tsv").unlink()
    item = _one(_items(bids, fmri), "run_unpaired")
    assert "ses-2" in item["message"]


def test_dataset_level_events_apply_to_every_run(tmp_path):
    bids, fmri = make_trees(tmp_path, runs=("1", "2"))
    for p in (bids / "sub-01/func").glob("*_events.tsv"):
        p.unlink()
    (bids / "task-x_events.tsv").write_text("onset\tduration\ttrial_type\n1\t1\ta\n")
    assert _items(bids, fmri) == []
