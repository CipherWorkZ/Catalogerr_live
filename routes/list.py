import sqlite3
from flask import Blueprint, jsonify
from services.indexer import DB_FILE

list_bp = Blueprint("list", __name__, url_prefix="/api/v3/list")

@list_bp.get("/movies")
def list_movies():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT title, release_year, tmdb_id FROM media WHERE type='movie' AND tmdb_id IS NOT NULL").fetchall()
    conn.close()
    return jsonify([{"title":r["title"],"year":r["release_year"],"tmdbId":r["tmdb_id"]} for r in rows])

@list_bp.get("/series")
def list_series():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT title, release_year, tmdb_id FROM media WHERE type='tv' AND tmdb_id IS NOT NULL").fetchall()
    conn.close()
    return jsonify([{"title":r["title"],"year":r["release_year"],"tmdbId":r["tmdb_id"],"tvdbId":None} for r in rows])
