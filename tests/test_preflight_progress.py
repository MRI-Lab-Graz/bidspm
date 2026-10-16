import json
import shutil
import subprocess
import threading
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from lib.preflight import run_preflight
from tests.preflight_support import make_trees

ROOT = Path(__file__).resolve().parent.parent


def collect(tmp_path, subjects=("01", "02", "03"), **kw):
    bids, fmriprep = make_trees(tmp_path, subjects=subjects)
    events = []
    args = dict(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")
    args.update(kw)
    report = run_preflight(**args, progress=events.append)
    return report, events


def steps(events):
    return [e for e in events if e["phase"] == "subjects" and e["state"] == "progress"]


def test_subject_progress_counts_1_to_n_and_ends_with_done(tmp_path):
    report, events = collect(tmp_path)
    assert [(e["index"], e["total"]) for e in steps(events)] == [(1, 3), (2, 3), (3, 3)]
    assert [e["subject"] for e in steps(events)] == ["01", "02", "03"]
    assert events[-1]["phase"] == "done" and events[-1]["verdict"] == report["verdict"]
    elapsed = [e["elapsed"] for e in events]
    assert elapsed[0] >= 0 and elapsed == sorted(elapsed)


def test_partial_items_arrive_with_the_subject_that_caused_them(tmp_path):
    bids, fmriprep = make_trees(tmp_path, subjects=("01", "02"))
    next((fmriprep / "sub-02").rglob("*desc-preproc_bold.nii.gz")).unlink()
    events = []
    run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip", progress=events.append)
    by_subject = {e["subject"]: e["items"] for e in steps(events)}
    assert not [i for i in by_subject["01"] if i["severity"] == "error"]
    assert [i["id"] for i in by_subject["02"] if i["severity"] == "error"] == ["preproc_missing"]


def test_every_item_is_reported_in_exactly_one_event(tmp_path):
    report, events = collect(tmp_path)
    streamed = [i for e in events for i in e["items"]]
    assert sorted(map(json.dumps, streamed)) == sorted(map(json.dumps, report["checks"]))


def test_cancel_stops_between_subjects_and_reports_cancelled(tmp_path):
    seen = []
    bids, fmriprep = make_trees(tmp_path, subjects=("01", "02", "03"))
    report = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip",
                           progress=seen.append, cancelled=lambda: len(steps(seen)) >= 1)
    assert report["verdict"] == "cancelled"
    assert len(steps(seen)) == 1
    assert [e["verdict"] for e in seen if e["phase"] == "done"] == ["cancelled"]


def blocked_validator(release, started=None):
    def stub(*a, **k):
        if started:
            started.set()
        release.wait(10)
        return []
    return stub


def started(events, phase, state):
    return any(e["phase"] == phase and e["state"] == state for e in events)


def test_cancel_returns_while_the_validator_is_still_running(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    release, seen = threading.Event(), []
    try:
        with patch("lib.preflight.check_validator", side_effect=blocked_validator(release)):
            report = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="bids",
                                   progress=seen.append, cancelled=lambda: len(steps(seen)) >= 1)
        assert report["verdict"] == "cancelled" and not release.is_set()
        assert report["checks"] == [] and not started(seen, "validator", "done")
    finally:
        release.set()


def test_cancel_after_the_last_subject_is_honoured_while_waiting_for_the_validator(tmp_path):
    bids, fmriprep = make_trees(tmp_path, subjects=("01",))
    release, seen = threading.Event(), []
    try:
        with patch("lib.preflight.check_validator", side_effect=blocked_validator(release)):
            report = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="bids",
                                   progress=seen.append, cancelled=lambda: len(steps(seen)) >= 1)
        assert report["verdict"] == "cancelled" and len(steps(seen)) == 1 and not release.is_set()
    finally:
        release.set()


def test_cancel_with_no_checkable_subjects_is_honoured_while_waiting_for_the_validator(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    release, seen = threading.Event(), []
    try:
        with patch("lib.preflight.check_validator", side_effect=blocked_validator(release)):
            report = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="bids",
                                   subjects=["99"], progress=seen.append,
                                   cancelled=lambda: started(seen, "subjects", "start"))
        assert report["verdict"] == "cancelled" and not release.is_set()
        assert [e["verdict"] for e in seen if e["phase"] == "done"] == ["cancelled"]
    finally:
        release.set()


def test_cancel_before_the_first_subject_checks_none(tmp_path):
    seen = []
    bids, fmriprep = make_trees(tmp_path)
    report = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip",
                           progress=seen.append, cancelled=lambda: started(seen, "subjects", "start"))
    assert report["verdict"] == "cancelled" and not steps(seen)


def test_cancel_keeps_the_items_of_a_validator_that_already_finished(tmp_path):
    item = {"id": "validator", "severity": "warn", "subject": None, "message": "m", "fix": ""}
    finished, seen = threading.Event(), []

    def stub(*a, **k):
        finished.set()
        return [item]

    def progress(e):
        seen.append(e)
        if e["phase"] == "validator" and e["state"] == "start":
            finished.wait(5)
            time.sleep(0.05)  # let the worker thread publish its result
    bids, fmriprep = make_trees(tmp_path)
    with patch("lib.preflight.check_validator", side_effect=stub):
        report = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="bids",
                               progress=progress, cancelled=lambda: started(seen, "subjects", "start"))
    assert report["verdict"] == "cancelled" and report["checks"] == [item]


def test_validator_events_when_it_runs(tmp_path):
    with patch("lib.preflight.check_validator", return_value=[]):
        _, events = collect(tmp_path, validator="bids")
    states = [(e["phase"], e["state"]) for e in events if e["phase"] == "validator"]
    assert states[0] == ("validator", "start") and states[-1] == ("validator", "done")


def test_validator_items_are_emitted_when_it_finishes_and_stay_first_in_the_report(tmp_path):
    item = {"id": "validator", "severity": "warn", "subject": None, "message": "m", "fix": ""}

    def slow(*a, **k):
        time.sleep(0.05)
        return [item]
    with patch("lib.preflight.check_validator", side_effect=slow):
        report, events = collect(tmp_path, validator="bids")
    assert report["checks"][0] == item and report["checks"].count(item) == 1
    assert sum(e["items"].count(item) for e in events) == 1
    assert any(item in e["items"] for e in events if e["phase"] == "validator")


def test_a_failing_callback_never_breaks_the_check(tmp_path):
    bids, fmriprep = make_trees(tmp_path)

    def boom(event):
        raise RuntimeError("callback bug")
    report = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip",
                           progress=boom, cancelled=boom)
    assert report["verdict"] in ("ready", "warnings")


def test_no_callback_behaves_as_before(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    assert run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip")["verdict"] == "warnings"


@pytest.mark.parametrize("kw", [{"progress": "print"}, {"cancelled": True}])
def test_non_callable_callbacks_raise_a_clear_type_error(tmp_path, kw):
    bids, fmriprep = make_trees(tmp_path)
    with pytest.raises(TypeError, match="callable"):
        run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip", **kw)


def test_done_fires_once_when_the_folders_are_wrong(tmp_path):
    events = []
    report = run_preflight(bids_dir=tmp_path / "nope", fmriprep_dir=tmp_path / "nope2", validator="skip", progress=events.append)
    done = [e for e in events if e["phase"] == "done"]
    assert report["verdict"] == "blocked" and [e["verdict"] for e in done] == ["blocked"]
    assert events[-1] is done[0]
    assert {i["id"] for i in done[0]["items"] + [i for e in events for i in e["items"] if e is not done[0]]} == {"bids_dir", "fmriprep_dir"}


def test_done_fires_exactly_once_on_a_normal_run(tmp_path):
    _, events = collect(tmp_path)
    assert [e["phase"] for e in events].count("done") == 1


def test_total_counts_only_checked_subjects_times_tasks(tmp_path):
    bids, fmriprep = make_trees(tmp_path, subjects=("01", "02"))
    make_trees(tmp_path / "other", subjects=("03",))
    shutil.copytree(tmp_path / "other" / "fmriprep" / "sub-03", fmriprep / "sub-03")
    events = []
    run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x", "y"], space="MNI", validator="skip", progress=events.append)
    start = next(e for e in events if e["phase"] == "subjects" and e["state"] == "start")
    assert start["total"] == 4  # sub-03 exists only in fMRIPrep: 2 present subjects x 2 tasks, not 3 x 2
    assert [(e["index"], e["total"]) for e in steps(events)] == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_no_subjects_to_check_emits_a_zero_total_start_and_no_steps(tmp_path):
    bids, fmriprep = make_trees(tmp_path, subjects=("01",))
    events = []
    report = run_preflight(bids_dir=bids, fmriprep_dir=fmriprep, tasks=["x"], space="MNI", validator="skip",
                           subjects=["99"], progress=events.append)
    start = next(e for e in events if e["phase"] == "subjects" and e["state"] == "start")
    assert start["total"] == 0 and not steps(events)
    assert report["verdict"] == "blocked" and events[-1]["phase"] == "done"


def test_cli_progress_writes_counters_to_stderr_and_pure_json_to_stdout(tmp_path):
    bids, fmriprep = make_trees(tmp_path, subjects=("01", "02"))
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"BIDS_DIR": str(bids), "FMRIPREP_DIR": str(fmriprep), "SPACE": "MNI", "TASKS": ["x"], "MODELS_FILE": ""}))
    proc = subprocess.run([sys.executable, "bidspm.py", "--preflight", "--skip-validator", "--progress", "-s", str(cfg)],
                          cwd=ROOT, capture_output=True, text=True)
    assert json.loads(proc.stdout)["verdict"] == "warnings"
    assert "sub-01" in proc.stderr and "[1/2]" in proc.stderr and "[2/2]" in proc.stderr


def test_cli_progress_writer_failures_never_break_the_json_on_stdout(tmp_path, capsys, monkeypatch):
    import argparse
    import bidspm

    class Broken:
        def write(self, text):
            raise OSError("stderr closed")

        def flush(self):
            raise OSError("stderr closed")
    bids, fmriprep = make_trees(tmp_path)
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"BIDS_DIR": str(bids), "FMRIPREP_DIR": str(fmriprep), "SPACE": "MNI", "TASKS": ["x"], "MODELS_FILE": ""}))
    monkeypatch.setattr(sys, "stderr", Broken())
    args = argparse.Namespace(model="", skip_validator=True, validator="skip", action=None, progress=True)
    with pytest.raises(SystemExit) as exit_:
        bidspm.handle_preflight(str(cfg), args)
    assert exit_.value.code == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "warnings"


def test_cli_progress_lines_read_well_and_progress_without_preflight_warns(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"BIDS_DIR": str(bids), "FMRIPREP_DIR": str(fmriprep), "SPACE": "MNI", "TASKS": ["x"], "MODELS_FILE": ""}))
    proc = subprocess.run([sys.executable, "bidspm.py", "--preflight", "--skip-validator", "--progress", "-s", str(cfg)],
                          cwd=ROOT, capture_output=True, text=True)
    assert "done done" not in proc.stderr and "verdict: warnings" in proc.stderr
    assert "checking the folders" in proc.stderr
    proc = subprocess.run([sys.executable, "bidspm.py", "--progress", "--list-tasks", "-s", str(cfg)],
                          cwd=ROOT, capture_output=True, text=True)
    assert "--progress" in proc.stderr and "--preflight" in proc.stderr
