"""Jobs API: POST /api/preflight/start, GET /api/preflight/stream/<id>, POST /api/preflight/cancel/<id>."""
import json
import os
import threading
from unittest.mock import patch

import pytest

from bidspm_gui import app
from tests.preflight_support import make_trees
from webapp import web_preflight_api as api

RUNNER = "webapp.web_preflight_api.run_preflight_from_config"
WAIT = 20  # generous upper bound for Event waits, never a timing margin


@pytest.fixture(autouse=True)
def clean_registry():
    with api._JOBS_LOCK:
        api._JOBS.clear()
    yield
    with api._JOBS_LOCK:
        jobs = list(api._JOBS.values())
    for job in jobs:  # never leave a blocked worker behind
        job.cancel_event.set()
        job.done_event.wait(WAIT)


def cfg(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    return {"BIDS_DIR": str(bids), "FMRIPREP_DIR": str(fmriprep), "SPACE": "MNI", "TASKS": ["x"]}


def start(client, body):
    res = client.post("/api/preflight/start", json=body)
    assert res.status_code == 200, res.data
    return res.get_json()["id"]


def parse(raw):
    events = []
    for block in raw.split("\n\n"):
        lines = [ln for ln in block.split("\n") if ln and not ln.startswith(":")]
        if lines:
            data = next(ln[6:] for ln in lines if ln.startswith("data: "))
            sid = next((ln[4:] for ln in lines if ln.startswith("id: ")), None)
            events.append((sid, json.loads(data)))
    return events


def stream(client, job_id, query=""):
    res = client.get(f"/api/preflight/stream/{job_id}{query}")
    return res, parse(res.get_data(as_text=True))


def job_of(job_id):
    with api._JOBS_LOCK:
        return api._JOBS[job_id]


def finished(job_id):
    """Terminal state reached AND the worker's registry bookkeeping (eviction) is done."""
    job = job_of(job_id)
    assert job.done_event.wait(WAIT)
    job.thread.join(WAIT)
    return not job.thread.is_alive()


def test_stream_ends_with_done_report_equal_to_sync_endpoint(tmp_path):
    client = app.test_client()
    body = {"config": cfg(tmp_path), "validator": "skip"}
    res, events = stream(client, start(client, body))
    assert res.mimetype == "text/event-stream"
    assert [sid for sid, _ in events] == [str(i) for i in range(len(events))]
    assert [e["seq"] for _, e in events] == list(range(len(events)))
    assert events[-1][1]["phase"] == "done" and events[-1][1]["state"] == "done"
    assert [e["phase"] for _, e in events].count("done") == 1
    assert events[-1][1]["report"] == client.post("/api/preflight", json=body).get_json()


def test_sse_headers(tmp_path):
    client = app.test_client()
    res, _ = stream(client, start(client, {"config": cfg(tmp_path), "validator": "skip"}))
    assert "no-cache" in res.headers["Cache-Control"] and res.headers["X-Accel-Buffering"] == "no"


def test_reconnect_from_replays_only_the_tail(tmp_path):
    client = app.test_client()
    job = start(client, {"config": cfg(tmp_path), "validator": "skip"})
    _, events = stream(client, job)
    assert len(events) > 3
    _, tail = stream(client, job, "?from=3")
    assert tail == events[3:]


@pytest.mark.parametrize("value", ["abc", "-4", "", "1.5", "99999999999999999999x"])
def test_bad_from_is_treated_as_zero(tmp_path, value):
    client = app.test_client()
    job = start(client, {"config": cfg(tmp_path), "validator": "skip"})
    _, events = stream(client, job)
    res, again = stream(client, job, f"?from={value}")
    assert res.status_code == 200 and again == events


def test_cancel_running_job(tmp_path):
    started = threading.Event()

    def runner(config, progress=None, cancelled=None, **kw):
        started.set()
        while not cancelled():
            threading.Event().wait(0.01)
        return {"verdict": "cancelled", "checks": []}

    client = app.test_client()
    with patch(RUNNER, side_effect=runner):
        job = start(client, {"config": {}})
        assert started.wait(WAIT)
        assert client.post(f"/api/preflight/cancel/{job}").get_json() == {"status": "cancelling"}
        _, events = stream(client, job)
        assert finished(job)
    assert events[-1][1]["phase"] == "done" and events[-1][1]["report"]["verdict"] == "cancelled"
    assert client.post(f"/api/preflight/cancel/{job}").get_json() == {"status": "finished"}
    assert client.post("/api/preflight/cancel/nope").get_json() == {"status": "unknown"}


def test_unknown_stream_id_gives_one_error_event():
    _, events = stream(app.test_client(), "nope")
    assert events == [(None, {"phase": "error", "message": "job not found"})]


def test_model_json_temp_file_exists_while_running_and_is_removed(tmp_path):
    seen = {}

    def runner(config, model="", progress=None, **kw):
        seen["model"] = model
        seen["isfile"] = os.path.isfile(model)
        seen["content"] = json.load(open(model))
        return {"verdict": "ok", "checks": []}

    client = app.test_client()
    with patch(RUNNER, side_effect=runner):
        job = start(client, {"config": {}, "model_json": {"Name": "m"}})
        stream(client, job)
        assert finished(job)
    assert seen["isfile"] and seen["content"] == {"Name": "m"}
    assert not os.path.exists(seen["model"])


def test_model_json_removed_even_if_runner_raises():
    seen = {}

    def runner(config, model="", **kw):
        seen["model"] = model
        raise RuntimeError("boom")

    client = app.test_client()
    with patch(RUNNER, side_effect=runner):
        job = start(client, {"config": {}, "model_json": {"Name": "m"}})
        stream(client, job)
        assert finished(job)
    assert seen["model"] and not os.path.exists(seen["model"])


@pytest.mark.parametrize("body", [
    [1, 2], "x", {"config": "oops"}, {"config": []}, {"config": {}, "actions": "stats"},
    {"config": {}, "model_json": "nope"}, {"config": {}, "model_json": [1]},
    {"config": {}, "model": 5}, {"config": {}, "validator": 3},
])
def test_malformed_bodies_are_json_400(body):
    res = app.test_client().post("/api/preflight/start", json=body)
    assert res.status_code == 400 and res.is_json and res.get_json()["error"]


def test_non_json_body_is_json_400():
    res = app.test_client().post("/api/preflight/start", data="not json", content_type="text/plain")
    assert res.status_code == 400 and res.is_json


def test_registry_keeps_at_most_20_finished_jobs():
    client = app.test_client()
    ok = {"verdict": "ok", "checks": []}
    with patch(RUNNER, return_value=ok):
        for _ in range(25):
            job = start(client, {"config": {}})
            assert finished(job)
    with api._JOBS_LOCK:
        assert len(api._JOBS) == 20 and job in api._JOBS


def test_running_job_is_never_evicted():
    release = threading.Event()

    entered = threading.Event()

    def blocker(config, **kw):
        entered.set()
        release.wait(WAIT)
        return {"verdict": "ok", "checks": []}

    client = app.test_client()
    with patch(RUNNER, side_effect=blocker):
        running = start(client, {"config": {}})
        assert entered.wait(WAIT)
    ok = {"verdict": "ok", "checks": []}
    with patch(RUNNER, return_value=ok):
        for _ in range(25):
            assert finished(start(client, {"config": {}}))
    with api._JOBS_LOCK:
        assert running in api._JOBS and not api._JOBS[running].done_event.is_set()
        assert len(api._JOBS) == 21  # 20 finished + the running one
    release.set()


def test_runner_exception_ends_stream_with_error_event():
    client = app.test_client()
    with patch(RUNNER, side_effect=RuntimeError("validator exploded")):
        job = start(client, {"config": {}})
        _, events = stream(client, job)
    last = events[-1][1]
    assert last["phase"] == "error" and last["state"] == "done" and "validator exploded" in last["message"]
    assert finished(job)
    assert client.post(f"/api/preflight/cancel/{job}").get_json() == {"status": "finished"}


def test_empty_config_still_ends_with_blocked_verdict():
    client = app.test_client()
    _, events = stream(client, start(client, {"config": {}, "validator": "skip"}))
    assert events[-1][1]["phase"] == "done" and events[-1][1]["report"]["verdict"] == "blocked"


def test_registry_lock_is_free_while_running_and_while_yielding():
    inside = {}
    release = threading.Event()
    entered = threading.Event()

    def runner(config, progress=None, **kw):
        inside["free"] = api._JOBS_LOCK.acquire(blocking=False)
        if inside["free"]:
            api._JOBS_LOCK.release()
        progress({"phase": "folders", "state": "start", "message": "m"})
        entered.set()
        release.wait(WAIT)
        return {"verdict": "ok", "checks": []}

    client = app.test_client()
    with patch(RUNNER, side_effect=runner):
        job = start(client, {"config": {}})
        assert entered.wait(WAIT)
        res = client.get(f"/api/preflight/stream/{job}", buffered=False)
        chunks = iter(res.response)
        first = next(chunks)  # the generator is suspended at a yield right now
        assert b"folders" in first
        got = api._JOBS_LOCK.acquire(blocking=False)
        if got:
            api._JOBS_LOCK.release()
        release.set()
        res.close()
        assert finished(job)
    assert inside["free"] and got


def test_client_disconnect_does_not_stop_job_or_leak_threads():
    release = threading.Event()
    entered = threading.Event()

    def runner(config, progress=None, **kw):
        progress({"phase": "folders", "state": "start", "message": "m"})
        entered.set()
        release.wait(WAIT)
        return {"verdict": "ok", "checks": []}

    client = app.test_client()
    before = threading.active_count()
    with patch(RUNNER, side_effect=runner):
        job = start(client, {"config": {}})
        assert entered.wait(WAIT)
        res = client.get(f"/api/preflight/stream/{job}", buffered=False)
        next(iter(res.response))
        res.close()  # GeneratorExit inside the generator
        release.set()
        assert finished(job)
    job_of(job).thread.join(WAIT)
    job_of(job).timer.join(WAIT)  # cancelled with the terminal event, no thread left waiting out the grace
    _, events = stream(client, job)  # a new client can still read the whole history
    assert events[-1][1]["phase"] == "done"
    assert threading.active_count() <= before


def test_finished_job_with_from_past_the_end_ends_silently():
    client = app.test_client()
    with patch(RUNNER, return_value={"verdict": "ok", "checks": []}):
        job = start(client, {"config": {}})
        assert finished(job)
    for value in ("9999", "99999999999999999999"):
        res, events = stream(client, job, f"?from={value}")
        assert res.status_code == 200 and events == []


def test_runner_raising_systemexit_still_ends_the_stream():
    client = app.test_client()
    with patch(RUNNER, side_effect=SystemExit(3)):
        job = start(client, {"config": {}})
        _, events = stream(client, job)
        assert finished(job)
    assert events[-1][1]["phase"] == "error" and events[-1][1]["state"] == "done"


def test_cancel_after_terminal_event_says_finished_immediately():
    client = app.test_client()
    with patch(RUNNER, return_value={"verdict": "ok", "checks": []}):
        job = start(client, {"config": {}})
        _, events = stream(client, job)  # saw the terminal event
        assert events[-1][1]["phase"] == "done"
        assert client.post(f"/api/preflight/cancel/{job}").get_json() == {"status": "finished"}


def test_too_many_running_jobs_is_429_json():
    release = threading.Event()
    entered = threading.Semaphore(0)

    def blocker(config, **kw):
        entered.release()
        release.wait(WAIT)
        return {"verdict": "ok", "checks": []}

    client = app.test_client()
    with patch(RUNNER, side_effect=blocker):
        ids = [start(client, {"config": {}}) for _ in range(api.MAX_RUNNING_JOBS)]
        for _ in ids:
            assert entered.acquire(timeout=WAIT)
        res = client.post("/api/preflight/start", json={"config": {}})
        assert res.status_code == 429 and "too many readiness checks" in res.get_json()["error"]
        release.set()
        assert all(finished(i) for i in ids)
        assert client.post("/api/preflight/start", json={"config": {}}).status_code == 200


def test_stream_has_a_maximum_lifetime():
    release = threading.Event()
    entered = threading.Event()

    def blocker(config, **kw):
        entered.set()
        release.wait(WAIT)
        return {"verdict": "ok", "checks": []}

    client = app.test_client()
    with patch(RUNNER, side_effect=blocker), patch.object(api, "STREAM_MAX_SECONDS", 0.05):
        job = start(client, {"config": {}})
        assert entered.wait(WAIT)
        _, events = stream(client, job)
        release.set()
        assert finished(job)
    assert events[-1][1] == {"phase": "error", "state": "done", "message": "stream timed out"}


def test_thread_start_failure_leaves_no_job_behind():
    client = app.test_client()
    with patch.object(api.threading.Thread, "start", side_effect=RuntimeError("no threads")):
        res = client.post("/api/preflight/start", json={"config": {}})
    assert res.status_code == 500 and res.is_json and "no threads" in res.get_json()["error"]
    with api._JOBS_LOCK:
        assert not api._JOBS


def _blocking_runner(started):
    def runner(config, progress=None, cancelled=None, **kw):
        started.release()
        while not cancelled():
            threading.Event().wait(0.01)
        return {"verdict": "cancelled", "checks": []}
    return runner


def test_unattended_job_is_cancelled_after_the_grace_and_frees_its_slot():
    started = threading.Semaphore(0)
    client = app.test_client()
    with patch(RUNNER, side_effect=_blocking_runner(started)), patch.object(api, "STREAM_ATTACH_GRACE", 0.1):
        ids = [start(client, {"config": {}}) for _ in range(api.MAX_RUNNING_JOBS)]
        assert all(job_of(i).cancel_event.wait(WAIT) for i in ids)  # nobody ever attached
        assert all(finished(i) for i in ids)
        assert client.post("/api/preflight/start", json={"config": {}}).status_code == 200


def test_job_with_a_stream_attached_in_time_is_not_cancelled():
    started = threading.Event()
    release = threading.Event()

    def runner(config, progress=None, cancelled=None, **kw):
        started.set()
        release.wait(WAIT)
        return {"verdict": "ready", "checks": []}

    client = app.test_client()
    with patch(RUNNER, side_effect=runner), patch.object(api, "STREAM_ATTACH_GRACE", 0.3):
        job = start(client, {"config": {}})
        assert started.wait(WAIT)
        reader = threading.Thread(target=lambda: stream(client, job), daemon=True)
        reader.start()
        j = job_of(job)
        pause = threading.Event()
        for _ in range(WAIT * 100):  # condition wait: the stream attached
            if j.streamed or pause.wait(0.01):
                break
        assert j.streamed
        j.timer.join(WAIT)  # the grace has passed
        assert not j.cancel_event.is_set()
        release.set()
        reader.join(WAIT)
        assert finished(job)


def test_job_finished_before_the_grace_is_untouched():
    client = app.test_client()
    with patch(RUNNER, return_value={"verdict": "ready", "checks": []}), patch.object(api, "STREAM_ATTACH_GRACE", 0.1):
        job = start(client, {"config": {}})
        assert finished(job)
        j = job_of(job)
        j.timer.join(WAIT)
        assert not j.cancel_event.is_set()
        _, events = stream(client, job)  # late attach still replays the real result
    assert events[-1][1]["report"]["verdict"] == "ready"
