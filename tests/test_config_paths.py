"""load_config normalises `~` and blanks exactly like the readiness check, so a passing gate means a usable run."""
import json
from pathlib import Path
from unittest.mock import patch

import bidspm
from lib.config import load_config
from lib.preflight import resolve_tasks, run_preflight_from_config
from tests.preflight_support import make_trees, write_model


def write_cfg(home, **over):
    cfg = {"WD": " ~/wd ", "BIDS_DIR": "~/proj/bids", "FMRIPREP_DIR": " ~/proj/fmriprep ", "SPACE": "MNI",
           "FWHM": 6, "TASKS": ["x"], "DERIVATIVES_DIR": " ~/deriv ", "MODELS_FILE": " ~/proj/model.json ", **over}
    path = home / "cfg.json"
    path.write_text(json.dumps(cfg))
    return cfg, path


def test_load_config_expands_tilde_and_strips_blanks(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _, path = write_cfg(tmp_path)
    c = load_config(str(path))
    assert (c.WD, c.BIDS_DIR, c.FMRIPREP_DIR, c.DERIVATIVES_DIR) == (
        tmp_path / "wd", tmp_path / "proj/bids", tmp_path / "proj/fmriprep", tmp_path / "deriv")
    assert c.MODELS_FILE == str(tmp_path / "proj/model.json")


def test_empty_derivatives_still_defaults_to_wd(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    _, path = write_cfg(tmp_path, DERIVATIVES_DIR="  ")
    assert load_config(str(path)).DERIVATIVES_DIR == tmp_path / "wd"


def test_gate_ready_implies_the_run_sees_existing_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    make_trees(tmp_path / "proj")
    write_model(tmp_path / "proj")
    cfg, path = write_cfg(tmp_path)
    assert run_preflight_from_config(cfg, validator="skip")["verdict"] != "blocked"
    c = load_config(str(path))
    assert c.BIDS_DIR.is_dir() and c.FMRIPREP_DIR.is_dir() and Path(c.MODELS_FILE).is_file()


def test_resolve_tasks_treats_a_string_as_one_task(tmp_path):
    assert resolve_tasks("motor", "", tmp_path) == ["motor"]


def _empty_tasks_cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    make_trees(tmp_path / "proj", task="found")
    write_model(tmp_path / "proj")  # Input.task = ["x"]
    return write_cfg(tmp_path, TASKS=[], SUBJECTS=["01"])[1]


def test_estimate_time_uses_the_resolved_tasks(tmp_path, monkeypatch):
    path = _empty_tasks_cfg(tmp_path, monkeypatch)
    with patch.object(bidspm, "estimate_processing_time", side_effect=RuntimeError("stop")) as est:
        try:
            bidspm.handle_estimate_time(str(path), ["stats"])
        except RuntimeError:
            pass
    assert est.call_args.args[2] == ["x"]


def test_reports_use_the_resolved_tasks(tmp_path, monkeypatch):
    path = _empty_tasks_cfg(tmp_path, monkeypatch)
    with patch("lib.report_generator.generate_reports", return_value=None) as gen:
        try:
            bidspm._handle_report(str(path), type("A", (), {"model": None})())
        except Exception:
            pass
    assert gen.call_args.kwargs["tasks"] == ["x"]
