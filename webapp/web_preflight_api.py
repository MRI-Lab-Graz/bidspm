"""Thin route for the GUI's readiness panel; the logic lives in lib/preflight.py."""
from flask import Flask, jsonify, request

from lib.preflight import run_preflight_from_config


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
