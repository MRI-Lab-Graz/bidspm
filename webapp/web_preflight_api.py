"""Thin routes for the GUI's readiness panel; the logic lives in lib/preflight.py.

Jobs API (progress over SSE). Event contract, one `id: <seq>\\ndata: <json>\\n\\n` per event:
  * every runner progress event (see lib/preflight.py) plus `seq` (position in the stream);
  * terminal success: the runner's final `{"phase":"done","state":"done",...}` event plus `report`
    (the full `{"verdict","checks"}`; verdict may be "cancelled");
  * terminal failure (the check itself raised): `{"phase":"error","state":"done","message":<text>}`;
  * unknown job id: a single `{"phase":"error","message":"job not found"}` without id.
The stream ends after the terminal event.
"""
import json
import os
import tempfile
import threading
import uuid

from flask import Flask, Response, jsonify, request, stream_with_context

from lib.preflight import run_preflight_from_config

MAX_FINISHED_JOBS = 20
_JOBS = {}  # insertion-ordered: oldest first
_JOBS_LOCK = threading.Lock()  # guards _JOBS only; never held while running a check or yielding


class _Job:
    def __init__(self):
        self.events = []
        self.cond = threading.Condition()  # guards events; notified on every append
        self.cancel_event = threading.Event()
        self.done_event = threading.Event()
        self.thread = None
        self.final = None  # runner's own `done` event, merged into the terminal one

    def add_event(self, event):
        with self.cond:
            self.events.append({**event, "seq": len(self.events)})
            self.cond.notify_all()


def _evict_finished():
    """Caller holds _JOBS_LOCK. Drop the oldest finished jobs beyond the cap; running jobs stay."""
    finished = [i for i, j in _JOBS.items() if j.done_event.is_set()]
    for job_id in finished[:max(0, len(finished) - MAX_FINISHED_JOBS)]:
        del _JOBS[job_id]


def _work(job, config, kwargs, model_path):
    def progress(event):
        if event.get("phase") == "done":
            job.final = event  # held back: the terminal event also carries the report
        else:
            job.add_event(event)

    try:
        report = run_preflight_from_config(config, progress=progress, cancelled=job.cancel_event.is_set, **kwargs)
        job.add_event({"phase": "done", "state": "done", **(job.final or {}), "report": report})
    except Exception as exc:  # noqa: BLE001 - a stream must always get a terminal event
        job.add_event({"phase": "error", "state": "done", "message": f"{type(exc).__name__}: {exc}"})
    finally:
        if model_path:
            try:
                os.remove(model_path)
            except OSError:
                pass
        job.done_event.set()
        with _JOBS_LOCK:
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
        model_path = None
        try:
            if model_json is not None:
                handle, model_path = tempfile.mkstemp(suffix='.json', prefix='bidspm_model_')
                with os.fdopen(handle, 'w', encoding='utf-8') as out:
                    json.dump(model_json, out)
                kwargs["model"] = model_path
            job, job_id = _Job(), uuid.uuid4().hex
            job.thread = threading.Thread(target=_work, args=(job, config, kwargs, model_path), daemon=True)
            with _JOBS_LOCK:
                _evict_finished()
                _JOBS[job_id] = job
            job.thread.start()
        except Exception:
            if model_path and os.path.exists(model_path):
                os.remove(model_path)
            raise
        return jsonify({"id": job_id})

    @app.route('/api/preflight/stream/<job_id>')
    def api_preflight_stream(job_id: str):
        with _JOBS_LOCK:
            job = _JOBS.get(job_id)
        start = _from_index()

        def generate():
            if job is None:
                yield 'data: {"phase": "error", "message": "job not found"}\n\n'
                return
            sent = start
            while True:
                with job.cond:
                    if sent >= len(job.events):
                        job.cond.wait(timeout=1)
                    batch = job.events[sent:]
                if not batch:
                    yield ': keepalive\n\n'
                    continue
                for event in batch:
                    yield f"id: {event['seq']}\ndata: {json.dumps(event)}\n\n"
                    sent = event['seq'] + 1
                    if event.get('state') == 'done' and event.get('phase') in ('done', 'error'):
                        return

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
