"""Thin routes for the model wizard; the recipe engine lives in lib/model_wizard.py."""
import json
import os
import tempfile
from pathlib import Path

from flask import Flask, jsonify, request

from lib.core import discover_tasks
from lib.model_wizard import NUISANCE_PRESETS, WizardError, build_model, catalog, scan_events
from lib.preflight import _verdict, run_preflight_from_config
from webapp.web_discovery_model_api import _discover_confound_info


def _scan(bids_dir, fmriprep_dir, task, with_confounds=True):
    tasks = discover_tasks(Path(bids_dir))
    task = task if task in tasks else (tasks[0] if tasks else "")
    events = scan_events(bids_dir, task) if task else {"columns": {}, "numeric": [], "files": 0, "truncated": [], "files_truncated": False}
    confounds = (_discover_confound_info(Path(fmriprep_dir), [task] if task else None)
                 if with_confounds and fmriprep_dir else {"columns": []})
    return {"tasks": tasks, "task": task, "columns": events["columns"],
            "numeric": events["numeric"], "confound_columns": confounds["columns"],
            "truncated": events["truncated"], "events_files": events["files"],
            "files_truncated": events.get("files_truncated", False)}


def _preflight(model, bids_dir, fmriprep_dir, space, task):
    """Preflight of the proposed model against the real data (the dataset validator is not model-related: dropped)."""
    fd, name = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(model, fh)
        report = run_preflight_from_config(
            {"BIDS_DIR": bids_dir, "FMRIPREP_DIR": fmriprep_dir, "SPACE": space or "", "TASKS": [task]},
            model=name, validator="skip", actions=["stats"])
    finally:
        os.unlink(name)
    checks = [c for c in report["checks"] if c["id"] != "validator"]
    return {"verdict": _verdict(checks), "checks": checks}


def register_wizard_routes(app: Flask, resolve_fs_path) -> None:
    def _body():
        data = request.get_json(silent=True)
        return data if isinstance(data, dict) else None

    def _dirs(data):
        return (resolve_fs_path(str(data.get("bids_dir") or "")), resolve_fs_path(str(data.get("fmriprep_dir") or "")))

    @app.route("/api/wizard/scan", methods=["POST"])
    def wizard_scan():
        data = _body()
        if data is None:
            return jsonify({"error": "expected a JSON object"}), 400
        bids_dir, fmriprep_dir = _dirs(data)
        if not os.path.isdir(bids_dir):
            return jsonify({"error": f"BIDS folder not found: {bids_dir}"}), 404
        return jsonify({**_scan(bids_dir, fmriprep_dir, data.get("task")), "catalog": catalog(),
                        "nuisance_presets": NUISANCE_PRESETS})

    @app.route("/api/wizard/build", methods=["POST"])
    def wizard_build():
        data = _body()
        if data is None or not isinstance(data.get("choices"), dict):
            return jsonify({"error": "expected a JSON object with 'choices'"}), 400
        choices = {k: v for k, v in data["choices"].items() if v is not None}  # JSON null means omitted
        bids_dir, fmriprep_dir = _dirs(data)
        if not os.path.isdir(bids_dir):
            return jsonify({"error": f"BIDS folder not found: {bids_dir}"}), 404
        save_path = str(data.get("save_path") or "").strip()
        if save_path:
            save_path = os.path.abspath(resolve_fs_path(save_path))
            if not save_path.endswith(".json"):
                return jsonify({"error": "save_path must end with .json"}), 400
            if os.path.exists(save_path) and not data.get("overwrite"):
                return jsonify({"error": "File already exists. Set overwrite=true to replace it."}), 409
        try:
            # build_model never reads confound columns, so skip reading every confounds TSV
            scan = _scan(bids_dir, fmriprep_dir, choices.get("task"), with_confounds=False)
            result = build_model(choices, scan)
        except WizardError as exc:
            return jsonify({"error": str(exc)}), 400
        if "trial_type" in scan["truncated"]:
            n = len(scan["columns"]["trial_type"])
            result["preview"]["warnings"].append(f"trial_type has more than {n} values; only the first {n} are offered")
        if scan.get("files_truncated"):
            result["preview"]["warnings"].append(f"the task has more events files than were scanned (only the first {scan['events_files']} were read); later subjects are not considered")
        if data.get("preflight", True) or save_path:  # the live preview skips the slow readiness check; saving never does
            try:
                result["preflight"] = _preflight(result["model"], bids_dir, fmriprep_dir, data.get("space"), choices["task"])
            except Exception as exc:  # JSON instead of an HTML 500
                return jsonify({"error": f"preflight failed: {exc}"}), 500
        if save_path:
            try:
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, "w", encoding="utf-8") as fh:
                    json.dump(result["model"], fh, indent=2)
                    fh.write("\n")
            except OSError as exc:
                return jsonify({"error": f"could not save: {exc}"}), 400
            result["saved"] = save_path
        return jsonify(result)
