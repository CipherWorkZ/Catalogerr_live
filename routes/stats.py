from flask import Blueprint, jsonify, render_template
from services.stats import get_stats
from services.auth import require_api_key
stats_bp = Blueprint("stats", __name__, url_prefix="")

# Page
@stats_bp.route("/stats")
def stats_page():
    return render_template("stats.html")

# API
@stats_bp.route("/api/v3/stats")
@require_api_key
def api_stats():
    return jsonify(get_stats())
