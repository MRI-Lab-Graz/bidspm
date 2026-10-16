"""Thin routes for the model wizard; the recipe engine lives in lib/model_wizard.py."""
import json
import os
import tempfile
from pathlib import Path

from flask import Flask, jsonify, request

from lib.core import discover_tasks
from lib.model_wizard import NUISANCE_PRESETS, WizardError, build_model, catalog
from lib.preflight import _verdict, run_preflight_from_config
from webapp.web_discovery_model_api import _discover_confound_info, _discover_event_info


def _scan(bids_dir, fmriprep_dir, task):
    tasks = discover_tasks(Path(bids_dir))
    task = task if task in tasks else (tasks[0] if tasks else "")
    events = _discover_event_info(Path(bids_dir), [task] if task else None)
    confounds = _discover_confound_info(Path(fmriprep_dir), [task] if task else None) if fmriprep_dir else {"columns": []}
    return {"tasks": tasks, "task": task, "columns": events["sample_values"],
            "numeric": events["numeric_columns"], "confound_columns": confounds["columns"]}


def _preflight(model, bids_dir, fmriprep_dir, space, task):
    """Preflight of the proposed model against the real data (the dataset validator is not model-related: dropped)."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(model, fh)
    try:
        report = run_preflight_from_config(
            {"BIDS_DIR": bids_dir, "FMRIPREP_DIR": fmriprep_dir, "SPACE": space or "", "TASKS": [task]},
            model=fh.name, validator="skip", actions=["stats"])
    finally:
        os.unlink(fh.name)
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
            result = build_model(choices, _scan(bids_dir, fmriprep_dir, choices.get("task")))
        except WizardError as exc:
            return jsonify({"error": str(exc)}), 400
        result["preflight"] = _preflight(result["model"], bids_dir, fmriprep_dir, data.get("space"), choices["task"])
        if save_path:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "w", encoding="utf-8") as fh:
                json.dump(result["model"], fh, indent=2)
                fh.write("\n")
            result["saved"] = save_path
        return jsonify(result)
