"""Recent-result reuse: lib.preflight.signature/remember/recent, the job worker, and the /run gate."""
import json
import os
import threading
from unittest.mock import MagicMock, patch

import pytest

from bidspm_gui import app
from lib import preflight
from tests.preflight_support import make_trees
from webapp import web_preflight_api as api

READY = {"verdict": "ready", "checks": []}
BLOCKED = {"verdict": "blocked", "checks": [{"id": "x", "severity": "error", "subject": None, "message": "m", "fix": "f"}]}
RUN_PF = "webapp.web_execution_api.run_preflight_from_config"


@pytest.fixture(autouse=True)
def clean_cache():
    preflight._RECENT.clear()
    yield
    preflight._RECENT.clear()


def sig(cfg=None, model="", validator="auto", actions=None, skip=False):
    return preflight.signature(cfg if cfg is not None else {"A": 1}, model, validator, actions, skip)


def test_signature_is_stable_and_key_order_independent():
    assert sig({"a": 1, "b": [1, 2]}) == sig({"b": [1, 2], "a": 1})


@pytest.mark.parametrize("other", [
    dict(cfg={"A": 2}), dict(validator="skip"), dict(actions=["stats"]), dict(skip=True),
])
def test_signature_changes_with_each_input(other):
    assert sig() != sig(**other)


def test_signature_actions_order_irrelevant_and_none_equals_empty():
    assert sig(actions=["stats", "smooth"]) == sig(actions=["smooth", "stats"])
    assert sig(actions=None) == sig(actions=[])


def test_signature_changes_with_model_edit(tmp_path):
    model = tmp_path / "m.json"
    model.write_text("{}")
    before = sig(model=str(model))
    model.write_text('{"x": 1}')
    assert sig(model=str(model)) != before


def test_signature_changes_with_model_mtime_only(tmp_path):
    model = tmp_path / "m.json"
    model.write_text("{}")
    before = sig(model=str(model))
    os.utime(model, ns=(1, 1))
    assert sig(model=str(model)) != before


def test_signature_missing_model_does_not_raise(tmp_path):
    assert sig(model=str(tmp_path / "nope.json"))


def test_signature_uses_effective_model_path(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text("{}")
    b.write_text("{}")
    os.utime(b, ns=(os.stat(a).st_atime_ns, os.stat(a).st_mtime_ns))
    # explicit model wins over MODELS_FILE: configs differing only in an overridden MODELS_FILE ...
    assert sig({"MODELS_FILE": str(a)}, model=str(b)) != sig({"MODELS_FILE": str(a)}, model=str(a))
    # ... and with no model argument the MODELS_FILE file is what is stat'ed
    os.utime(a, ns=(1, 1))
    s1 = sig({"MODELS_FILE": str(a)})
    os.utime(a, ns=(2, 2))
    assert sig({"MODELS_FILE": str(a)}) != s1


def test_remember_then_recent_returns_report():
    preflight.remember("k", {"verdict": "warnings", "checks": []})
    assert preflight.recent("k")["verdict"] == "warnings"


def test_remember_ignores_blocked_and_cancelled():
    preflight.remember("b", BLOCKED)
    preflight.remember("c", {"verdict": "cancelled", "checks": []})
    assert preflight.recent("b") is None and preflight.recent("c") is None


def test_remember_stores_a_copy():
    report = {"verdict": "ready", "checks": [{"id": "a"}]}
    preflight.remember("k", report)
    report["verdict"] = "blocked"
    report["checks"].append({"id": "b"})
    assert preflight.recent("k") == {"verdict": "ready", "checks": [{"id": "a"}]}


def test_recent_expires_after_ttl():
    with patch("lib.preflight.time.monotonic", return_value=1000.0):
        preflight.remember("k", READY)
    with patch("lib.preflight.time.monotonic", return_value=1599.0):
        assert preflight.recent("k") is not None
    with patch("lib.preflight.time.monotonic", return_value=1601.0):
        assert preflight.recent("k") is None


def test_cache_is_capped_oldest_evicted():
    for i in range(25):
        preflight.remember(f"k{i}", READY)
    assert preflight.recent("k0") is None and preflight.recent("k4") is None
    assert preflight.recent("k5") is not None and preflight.recent("k24") is not None


def test_concurrent_remember_is_safe():
    def work(n):
        for i in range(200):
            preflight.remember(f"{n}-{i}", READY)
            preflight.recent(f"{n}-{i}")
    threads = [threading.Thread(target=work, args=(n,)) for n in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(preflight._RECENT) <= 20


# --- job worker ---


def _run_work(report, config, kwargs, cancelled=False):
    job = MagicMock()
    job.final = None
    job.cancel_event.is_set.return_value = cancelled
    with patch.object(api, "run_preflight_from_config", return_value=report):
        api._work(job, config, kwargs, None)


KW = {"model": "", "validator": "skip", "actions": None, "skip_model_validation": False}


def test_worker_remembers_a_passing_report_under_its_own_arguments():
    _run_work(READY, {"A": 1}, KW)
    assert preflight.recent(preflight.signature({"A": 1}, "", "skip", None, False)) == READY
    assert preflight.recent(preflight.signature({"A": 1}, "", "auto", None, False)) is None


@pytest.mark.parametrize("report", [BLOCKED, {"verdict": "cancelled", "checks": []}])
def test_worker_does_not_remember_blocked_or_cancelled(report):
    _run_work(report, {"A": 1}, KW)
    assert not preflight._RECENT


def test_worker_does_not_remember_after_an_error():
    job = MagicMock()
    job.final = None
    with patch.object(api, "run_preflight_from_config", side_effect=RuntimeError("boom")):
        api._work(job, {"A": 1}, KW, None)
    assert not preflight._RECENT


def test_sync_route_does_not_remember(tmp_path):
    bids, fmriprep = make_trees(tmp_path)
    cfg = {"BIDS_DIR": str(bids), "FMRIPREP_DIR": str(fmriprep), "SPACE": "MNI", "TASKS": ["x"]}
    app.test_client().post("/api/preflight", json={"config": cfg, "validator": "skip"})
    assert not preflight._RECENT


# --- /run gate ---

def _settings(tmp_path, **over):
    path = tmp_path / "s.json"
    cfg = {"BIDS_DIR": "/b", "FMRIPREP_DIR": "/f", **over}
    path.write_text(json.dumps(cfg))
    return path, cfg


def _post(settings, **extra):
    with patch("webapp.web_execution_api.subprocess.Popen", return_value=MagicMock(pid=4242)), \
         patch("webapp.web_execution_api.threading.Thread"):
        return app.test_client().post("/run", json={"actions": ["stats"], "settings": str(settings), **extra})


def test_run_skips_the_check_on_a_remembered_signature(tmp_path):
    settings, cfg = _settings(tmp_path)
    preflight.remember(preflight.signature(cfg, "", "auto", ["stats"], False), READY)
    with patch(RUN_PF) as pf:
        res = _post(settings)
    assert res.status_code == 200
    pf.assert_not_called()


def test_run_checks_when_signature_differs(tmp_path):
    settings, cfg = _settings(tmp_path)
    preflight.remember(preflight.signature({**cfg, "SPACE": "other"}, "", "auto", ["stats"], False), READY)
    with patch(RUN_PF, return_value=READY) as pf:
        _post(settings)
    pf.assert_called_once()


def test_run_does_not_reuse_a_result_for_another_validator_or_actions(tmp_path):
    settings, cfg = _settings(tmp_path)
    preflight.remember(preflight.signature(cfg, "", "skip", ["stats"], False), READY)
    preflight.remember(preflight.signature(cfg, "", "auto", ["smooth"], False), READY)
    with patch(RUN_PF, return_value=READY) as pf:
        _post(settings)
    pf.assert_called_once()


def test_run_respects_validator_and_skip_flag_in_signature(tmp_path):
    settings, cfg = _settings(tmp_path)
    preflight.remember(preflight.signature(cfg, "", "skip", ["stats"], True), READY)
    with patch(RUN_PF) as pf:
        res = _post(settings, validator="skip", skip_validation=True)
    assert res.status_code == 200
    pf.assert_not_called()


def test_blocked_run_still_blocks_and_is_not_remembered(tmp_path):
    settings, _ = _settings(tmp_path)
    with patch(RUN_PF, return_value=BLOCKED):
        res = _post(settings)
    assert res.status_code == 400
    assert not preflight._RECENT


def test_passing_run_check_is_not_remembered_by_the_run_gate(tmp_path):
    # only the readiness job remembers; /run stays as it was
    settings, _ = _settings(tmp_path)
    with patch(RUN_PF, return_value=READY):
        _post(settings)
    assert not preflight._RECENT
