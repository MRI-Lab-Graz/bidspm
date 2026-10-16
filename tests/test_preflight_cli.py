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
