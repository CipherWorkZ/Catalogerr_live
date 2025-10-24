from flask import Blueprint, jsonify, request, render_template
from modules.connector import load_connectors, save_connectors, fetch_connector_stats
from services.auth import require_api_key

connectors_bp = Blueprint("connectors", __name__, url_prefix="/api/v3")


# Page render
@connectors_bp.route("/connector")
def connector_page():
    return render_template("app.html")


# List all connectors (with live status)
@connectors_bp.get("/connectors")
@require_api_key
def list_connectors():
    cfg = load_connectors()
    result = {}

    for app, data in cfg.items():
        stats = fetch_connector_stats(
            data.get("base_url"),
            data.get("api_key"),
            app_type=app,
            connector_id=data.get("id", app),
        )
        result[app] = {
            "base_url": data.get("base_url"),
            "api_key": data.get("api_key"),
            "status": stats["status"] == "success",
            "version": stats.get("version"),
            "error": stats.get("error"),
        }
    return jsonify(result)


# Add or update a connector (validates before saving)
@connectors_bp.post("/connectors")
@require_api_key
def add_connector():
    data = request.get_json(force=True)
    app_type = data.get("app_type")
    base_url = data.get("base_url")
    api_key = data.get("api_key")

    if not (app_type and base_url and api_key):
        return jsonify({"error": "Missing fields"}), 400

    stats = fetch_connector_stats(base_url, api_key, app_type)
    if stats["status"] != "success":
        return jsonify({"error": stats.get("error", "Connection failed")}), 400

    cfg = load_connectors()
    cfg[app_type] = {"base_url": base_url, "api_key": api_key}
    save_connectors(cfg)

    return jsonify({"status": "saved", "connector": cfg[app_type]})


# Test a single connector (without saving)
@connectors_bp.post("/connectors/test")
@require_api_key
def test_connector():
    data = request.get_json(force=True)
    base_url = data.get("base_url")
    api_key = data.get("api_key")
    app_type = data.get("app_type", "radarr")

    if not (base_url and api_key):
        return jsonify({"error": "Missing base_url or api_key"}), 400

    stats = fetch_connector_stats(base_url, api_key, app_type)
    return jsonify(stats)
