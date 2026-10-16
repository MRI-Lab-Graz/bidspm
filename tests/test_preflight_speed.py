import os
import time
from pathlib import Path
from unittest.mock import patch

from lib import preflight
from lib.preflight import run_preflight
from tests.preflight_support import make_trees, write_model


def _run(tmp_path, **kw):
    bids, fmriprep = make_trees(tmp_path)
    model = write_model(tmp_path, x=("trial_type.a", "trans_x", 1))
    return run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", model_file=model,
                         skip_model_validation=True, **{"validator": "skip", **kw})


# 1. header-only confounds read
def test_confounds_check_reads_only_the_header(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    model = write_model(tmp_path, x=("trial_type.a", "trans_x", "nope", 1))
    real = preflight._read_tsv
    calls = []

    def spy(path):
        calls.append(Path(path).name)
        if "confounds" in Path(path).name:
            raise AssertionError("confounds must not be fully parsed")
        return real(path)
    with patch.object(preflight, "_read_tsv", spy):
        result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", model_file=model,
                               skip_model_validation=True, validator="skip")
    assert [c["id"] for c in result["checks"] if "nope" in c["message"]] == ["confound_columns"]


def test_read_header_handles_bom_and_bad_bytes(tmp_path):
    f = tmp_path / "a.tsv"
    f.write_bytes("﻿a\tb\n1\t2\n".encode("utf-8"))
    assert preflight._read_header(f) == ["a", "b"]
    f.write_bytes(b"")
    assert preflight._read_header(f) == []
    f.write_bytes(b"a\n\xe9\xff\n")
    try:
        preflight._read_header(f)
    except UnicodeDecodeError:
        pass
    else:
        raise AssertionError("expected UnicodeDecodeError")


# 2. validator concurrent with subject checks
def test_validator_runs_concurrently_and_stays_first(tmp_path):
    bids, fmriprep = make_trees(tmp_path, subjects=("01", "02", "03"))
    item = preflight._item("validator", preflight.WARN, "slow")
    real = preflight.check_subject_task

    def slow_validator(*a, **k):
        time.sleep(0.3)
        return [item]

    def slow_subject(*a, **k):
        time.sleep(0.1)
        return real(*a, **k)
    with patch.object(preflight, "check_validator", slow_validator), \
            patch.object(preflight, "check_subject_task", slow_subject):
        t = time.time()
        result = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="auto")
        elapsed = time.time() - t
    assert elapsed < 0.55  # serial would be >= 0.6
    assert result["checks"][0] is item


def test_validator_skip_spawns_no_thread(tmp_path):
    with patch("concurrent.futures.ThreadPoolExecutor", side_effect=AssertionError("no thread")):
        _run(tmp_path)


def test_executor_is_shut_down_when_the_main_path_raises(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    with patch.object(preflight, "check_validator", lambda *a, **k: []), \
            patch.object(preflight, "check_subject_task", side_effect=RuntimeError("boom")):
        try:
            run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="auto")
        except RuntimeError:
            pass
        else:
            raise AssertionError("expected RuntimeError")


# 3. one listing per subject root
def _tree(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    for root in (bids, fmriprep):
        sub = root / "sub-01"
        for ses in ("ses-1", "ses-2"):
            (sub / ses / "func").mkdir(parents=True)
            for run in ("run-1", "run-2"):
                stem = f"sub-01_{ses}_task-x_{run}"
                (sub / ses / "func" / f"{stem}_events.tsv").write_text("onset\tduration\n1\t1\n")
                (sub / ses / "func" / f"{stem}_space-MNI_desc-preproc_bold.nii.gz").write_bytes(b"")
                (sub / ses / "func" / f"{stem}_desc-confounds_timeseries.tsv").write_text("a\n")
        (sub / "func" / "sub-01_task-xy_events.tsv").write_text("onset\tduration\n")  # decoy task
        (sub / "func" / "sub-01_task-xy_space-MNI_desc-preproc_bold.nii.gz").write_bytes(b"")
        (sub / "anat").mkdir()
        (sub / "anat" / "sub-01_task-x_events.tsv").write_text("")  # non-func decoy
        (sub / "anat" / "sub-01_task-x_space-MNI_desc-preproc_bold.nii.gz").write_bytes(b"")
    return bids, fmriprep


def _old(root, pattern):
    return sorted(p for p in (Path(root) / "sub-01").rglob(pattern) if p.parent.name == "func")


def test_func_listing_matches_the_old_rglob_semantics(tmp_path):
    bids, fmriprep = _tree(tmp_path)
    for root, pat in ((fmriprep, "*task-x_*space-MNI_*desc-preproc_bold.nii.gz"),
                      (fmriprep, "*task-x_*space-*_*desc-preproc_bold.nii.gz"),
                      (bids, "*task-x_*events.tsv"),
                      (fmriprep, "*task-x_*desc-confounds_timeseries.tsv")):
        listing = preflight._func_listing(root, "01")
        assert preflight._match(listing, pat) == _old(root, pat) != []


def test_one_walk_per_root_and_subject(tmp_path):
    bids, fmriprep = _tree(tmp_path)
    model = write_model(tmp_path, x=("trial_type.a", "a", 1))
    walks = []
    real = os.scandir

    def spy(path="."):
        walks.append(str(path))
        return real(path)
    with patch("os.scandir", spy), patch.object(Path, "rglob", side_effect=AssertionError("rglob")):
        run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", model_file=model,
                      skip_model_validation=True, validator="skip", subjects=["01"])
    sub_walks = [w for w in walks if w.endswith("sub-01")]
    assert sorted(sub_walks) == sorted({str(bids / "sub-01"), str(fmriprep / "sub-01")})
