"""Shared fixtures for the headless-Chromium page tests (not a test module)."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # optional dependency
    sync_playwright = None

REPO_ROOT = Path(__file__).resolve().parent.parent

MODEL = {
    "Name": "browser test model", "BIDSModelVersion": "1.0.0", "Description": "",
    "Input": {"task": ["motor"]},
    "Nodes": [{
        "Level": "Run", "Name": "run", "GroupBy": ["run", "subject"],
        "Model": {"X": ["trial_type.a", "trial_type.b", 1], "Type": "glm",
                  "HRF": {"Variables": ["trial_type.a", "trial_type.b"], "Model": "spm"}},
        "DummyContrasts": {"Test": "t"},
    }],
}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def chromium_available() -> bool:
    if sync_playwright is None:
        return False
    try:
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


def make_dataset(tmp: Path) -> None:
    """tmp/bids (two subjects, one with a nested empty folder), tmp/derivs, tmp/model.json."""
    func = tmp / "bids" / "sub-01" / "func"
    func.mkdir(parents=True)
    (tmp / "bids" / "sub-02" / "empty").mkdir(parents=True)
    (tmp / "derivs").mkdir()
    (tmp / "model.json").write_text(json.dumps(MODEL))
    (tmp / "bids" / "dataset_description.json").write_text(json.dumps({"Name": "t", "BIDSVersion": "1.9.0"}))
    (func / "sub-01_task-motor_events.tsv").write_text("onset\tduration\ttrial_type\n1\t1\ta\n5\t1\tb\n")


def start_server(tmp: Path):
    """Start bidspm_gui.py with an isolated HOME; returns (process, base_url, project_id)."""
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [sys.executable, "bidspm_gui.py", "--no-browser", "-p", str(port)], cwd=str(REPO_ROOT),
        env=dict(os.environ, HOME=str(tmp / "home")), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/", timeout=1)
            break
        except Exception:
            time.sleep(0.3)
    project_id = post_json(base + "/api/projects", {"name": "browser", "config": {
        "bids_folder": str(tmp / "bids"), "derivatives_folder": str(tmp / "derivs"),
        "models_file": str(tmp / "model.json"), "tasks": ["motor"]}})["project"]["id"]
    return proc, base, project_id
