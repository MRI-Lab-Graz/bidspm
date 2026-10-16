import json
import subprocess
import sys
from pathlib import Path

from lib.preflight import run_preflight_from_config
from tests.preflight_support import make_trees

ROOT = Path(__file__).resolve().parent.parent


def settings(tmp_path, **over):
    bids, fmriprep = make_trees(tmp_path)
    cfg = {"BIDS_DIR": str(bids), "FMRIPREP_DIR": str(fmriprep), "SPACE": "MNI", "TASKS": ["x"], "MODELS_FILE": ""}
    cfg.update(over)
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(cfg))
    return cfg, path


def test_from_config_matches_run_preflight(tmp_path):
    cfg, _ = settings(tmp_path)
    assert run_preflight_from_config(cfg, validator="skip")["verdict"] == "warnings"


def cli(*args):
    return subprocess.run([sys.executable, "bidspm.py", *args], cwd=ROOT, capture_output=True, text=True)


def test_cli_preflight_prints_json_and_exits_0_when_not_blocked(tmp_path):
    _, path = settings(tmp_path)
    proc = cli("--preflight", "--skip-validator", "-s", str(path))
    assert proc.returncode == 0 and json.loads(proc.stdout)["verdict"] == "warnings"


def test_cli_preflight_exits_1_when_blocked(tmp_path):
    _, path = settings(tmp_path, SPACE="T1w")
    proc = cli("--preflight", "--skip-validator", "-s", str(path))
    assert proc.returncode == 1 and json.loads(proc.stdout)["verdict"] == "blocked"


def test_help_mentions_preflight_options():
    out = subprocess.run([sys.executable, str(ROOT / "bidspm.py"), "--help"], capture_output=True, text=True).stdout
    assert all(opt in out for opt in ("--preflight", "--validator", "--skip-validator"))


def test_cli_preflight_bad_config_is_a_clean_error(tmp_path):
    for content in (None, "not json", "[]"):
        path = tmp_path / "bad.json"
        if content is not None:
            path.write_text(content)
        proc = cli("--preflight", "-s", str(path))
        assert proc.returncode == 2 and "Traceback" not in proc.stderr and proc.stderr.strip()


def test_cli_preflight_model_flag_overrides_config(tmp_path):
    _, path = settings(tmp_path, MODELS_FILE=str(tmp_path / "cfg_model.json"))
    proc = cli("--preflight", "--skip-validator", "-s", str(path), "--model", str(tmp_path / "cli_model.json"))
    assert "cli_model.json" in proc.stdout and "cfg_model.json" not in proc.stdout


def test_cli_validator_skip_value(tmp_path):
    _, path = settings(tmp_path)
    proc = cli("--preflight", "--validator", "skip", "-s", str(path))
    assert "Dataset validator skipped" in proc.stdout


def test_cli_preflight_uses_action_values(tmp_path):
    bids, _ = make_trees(tmp_path)
    for f in bids.rglob("*_events.tsv"):
        f.unlink()
    cfg = {"BIDS_DIR": str(bids), "FMRIPREP_DIR": str(tmp_path / "fmriprep"), "SPACE": "MNI", "TASKS": ["x"]}
    path = tmp_path / "c.json"
    path.write_text(json.dumps(cfg))
    assert "events_missing" in cli("--preflight", "--skip-validator", "-s", str(path)).stdout
    assert "events_missing" not in cli("--preflight", "--skip-validator", "--action", "smooth", "-s", str(path)).stdout


def test_cli_validator_defaults_to_auto():
    import bidspm
    from unittest.mock import patch
    with patch("sys.argv", ["bidspm.py", "--preflight"]):
        assert bidspm.parse_arguments().validator == "auto"
