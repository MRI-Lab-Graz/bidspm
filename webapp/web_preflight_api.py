"""Thin routes for the GUI's readiness panel; the logic lives in lib/preflight.py.

Jobs API (progress over SSE). Event contract, one `id: <seq>\\ndata: <json>\\n\\n` per event:
  * every runner progress event (see lib/preflight.py) plus `seq` (position in the stream);
  * terminal success: the runner's final `{"phase":"done","state":"done",...}` event plus `report`
    (the full `{"verdict","checks"}`; verdict may be "cancelled");
  * terminal failure (the check itself raised): `{"phase":"error","state":"done","message":<text>}`;
  * unknown job id: a single `{"phase":"error","message":"job not found"}` without id;
  * stream lifetime exceeded (STREAM_MAX_SECONDS; the job itself may still be running): a single
    `{"phase":"error","state":"done","message":"stream timed out"}` without seq and id. The client tells it from a job failure
    (which has a seq) and offers a retry that resumes with `?from=<last seq + 1>`.
The stream ends after the terminal event.
"""
import json
import os
import tempfile
import threading
import time
import uuid

from flask import Flask, Response, jsonify, request, stream_with_context

from lib.preflight import remember, run_preflight_from_config, signature, validator_error

MAX_FINISHED_JOBS = 20
MAX_RUNNING_JOBS = 3
STREAM_ATTACH_GRACE = 30  # a job nobody streams within this many seconds (page unloaded before start answered) is cancelled
STREAM_MAX_SECONDS = 1900  # just above the validator's 1800 s timeout
_JOBS = {}  # insertion-ordered: oldest first
_JOBS_LOCK = threading.Lock()  # guards _JOBS only; never held while running a check or yielding


class _Job:
    def __init__(self):
        self.events = []
        self.cond = threading.Condition()  # guards events; notified on every append
        self.cancel_event = threading.Event()
        self.done_event = threading.Event()
        self.thread = None
        self.timer = None  # attach-grace timer
        self.streamed = False  # a stream attached at least once; permanent
        self.final = None  # runner's own `done` event, merged into the terminal one

    def add_event(self, event, terminal=False):
        with self.cond:
            self.events.append({**event, "seq": len(self.events)})
            if terminal:  # same critical section: "finished" is visible exactly with the terminal event
                self.done_event.set()
            self.cond.notify_all()


def _evict_finished():
    """Caller holds _JOBS_LOCK. Drop the oldest finished jobs beyond the cap; running jobs stay."""
    finished = [i for i, j in _JOBS.items() if j.done_event.is_set()]
    for job_id in finished[:max(0, len(finished) - MAX_FINISHED_JOBS)]:
        del _JOBS[job_id]


def _cancel_unattended(job):
    if not job.streamed and not job.done_event.is_set():
        job.cancel_event.set()


def _work(job, config, kwargs, model_path):
    # ponytail: the model temp file is removed right after the runner returns/raises (BaseException caught below)
    def progress(event):
        if event.get("phase") == "done":
            job.final = event  # held back: the terminal event also carries the report
        else:
            job.add_event(event)

    sig = None
    try:
        # before the run: the temp model file is deleted below, and the signature hashes its content
        sig = signature(config, kwargs.get("model", ""), kwargs.get("validator", "auto"), kwargs.get("actions"),
                        kwargs.get("skip_model_validation", False))
    except Exception:  # noqa: BLE001 - reuse is an optimisation, never a failure
        pass
    try:
        report = run_preflight_from_config(config, progress=progress, cancelled=job.cancel_event.is_set, **kwargs)
        terminal = {"phase": "done", "state": "done", **(job.final or {}), "report": report}
        if sig is not None:
            try:
                remember(sig, report)  # only ready/warnings are kept
            except Exception:  # noqa: BLE001
                pass
    except BaseException as exc:  # noqa: BLE001 - a stream must always get a terminal event (incl. SystemExit)
        terminal = {"phase": "error", "state": "done", "message": f"{type(exc).__name__}: {exc}"}
    if model_path:  # before the terminal event: a client seeing it may rely on the file being gone
        try:
            os.remove(model_path)
        except OSError:
            pass
    with _JOBS_LOCK:
        job.add_event(terminal, terminal=True)
        if job.timer is not None:
            job.timer.cancel()
        _evict_finished()


def _bad(message):
    return jsonify({"error": message}), 400


def _parse_start(data):
    """Return ((config, kwargs), model_json, None) or (None, None, error message)."""
    if not isinstance(data, dict):
        return None, None, "body must be a JSON object"
    config = data.get("config")
    if config is None:
        config = {}
    model_json = data.get("model_json")
    actions = data.get("actions")
    model = data.get("model") or ""
    validator = data.get("validator") or "auto"
    for ok, message in (
        (isinstance(config, dict), "config must be an object"),
        (model_json is None or isinstance(model_json, dict), "model_json must be an object"),
        (actions is None or isinstance(actions, list), "actions must be a list"),
        (isinstance(model, str), "model must be a string"),
        (isinstance(validator, str), "validator must be a string"),
        (validator_error(validator, internal=True) is None, validator_error(validator, internal=True)),
    ):
        if not ok:
            return None, None, message
    kwargs = {"model": model, "validator": validator, "actions": actions,
              "skip_model_validation": bool(data.get("skip_model_validation"))}
    return (config, kwargs), model_json, None


def _from_index():
    try:
        return max(0, int(request.args.get("from", "0")))
    except ValueError:
        return 0


def register_preflight_routes(app: Flask) -> None:
    @app.route('/api/preflight', methods=['POST'])
    def api_preflight():
        data = request.get_json(silent=True)
        data = data if isinstance(data, dict) else {}
        config = data.get('config')
        actions = data.get('actions')
        problem = validator_error(data.get('validator'), internal=True)
        if problem:
            return _bad(problem)
        return jsonify(run_preflight_from_config(
            config if isinstance(config, dict) else {},
            model=data.get('model') or '', validator=data.get('validator') or 'auto',
            actions=actions if isinstance(actions, list) else None))

    @app.route('/api/preflight/start', methods=['POST'])
    def api_preflight_start():
        parsed, model_json, error = _parse_start(request.get_json(silent=True))
        if error:
            return _bad(error)
        config, kwargs = parsed
        job, job_id = _Job(), uuid.uuid4().hex
        with _JOBS_LOCK:
            if sum(not j.done_event.is_set() for j in _JOBS.values()) >= MAX_RUNNING_JOBS:
                return jsonify({"error": "too many readiness checks are running; "
                                         "wait for one to finish or cancel it"}), 429
            _JOBS[job_id] = job
        model_path = None
        try:
            if model_json is not None:  # overrides `model`
                handle, model_path = tempfile.mkstemp(suffix='.json', prefix='bidspm_model_')
                with os.fdopen(handle, 'w', encoding='utf-8') as out:
                    json.dump(model_json, out)
                kwargs["model"] = model_path
            job.thread = threading.Thread(target=_work, args=(job, config, kwargs, model_path), daemon=True)
            job.thread.start()
            job.timer = threading.Timer(STREAM_ATTACH_GRACE, _cancel_unattended, (job,))
            job.timer.daemon = True
            job.timer.start()
        except Exception as exc:  # noqa: BLE001 - never leave a job that will not run, never an HTML 500
            with _JOBS_LOCK:
                _JOBS.pop(job_id, None)
            if model_path and os.path.exists(model_path):
                os.remove(model_path)
            return jsonify({"error": f"could not start the check: {exc}"}), 500
        return jsonify({"id": job_id})

    @app.route('/api/preflight/stream/<job_id>')
    def api_preflight_stream(job_id: str):
        with _JOBS_LOCK:
            job = _JOBS.get(job_id)
        if job is not None:
            job.streamed = True
        start = _from_index()

        def generate():
            if job is None:
                yield 'data: {"phase": "error", "message": "job not found"}\n\n'
                return
            sent = start
            deadline = time.monotonic() + STREAM_MAX_SECONDS
            while True:
                with job.cond:
                    remaining = deadline - time.monotonic()
                    if sent >= len(job.events) and remaining > 0 and not job.done_event.is_set():
                        job.cond.wait(timeout=min(1, remaining))
                    batch = job.events[sent:]
                    finished = job.done_event.is_set()
                for event in batch:
                    yield f"id: {event['seq']}\ndata: {json.dumps(event)}\n\n"
                    sent = event['seq'] + 1
                if finished and not batch:
                    return  # e.g. reconnect after the terminal event, or `from` past the end
                if not batch:
                    if time.monotonic() >= deadline:
                        yield 'data: {"phase": "error", "state": "done", "message": "stream timed out"}\n\n'
                        return
                    yield ': keepalive\n\n'

        response = Response(stream_with_context(generate()), mimetype='text/event-stream')
        response.headers['Cache-Control'] = 'no-cache'
        response.headers['X-Accel-Buffering'] = 'no'
        return response

    @app.route('/api/preflight/cancel/<job_id>', methods=['POST'])
    def api_preflight_cancel(job_id: str):
        with _JOBS_LOCK:
            job = _JOBS.get(job_id)
        if job is None:
            return jsonify({"status": "unknown"})
        if job.done_event.is_set():
            return jsonify({"status": "finished"})
        job.cancel_event.set()
        return jsonify({"status": "cancelling"})
