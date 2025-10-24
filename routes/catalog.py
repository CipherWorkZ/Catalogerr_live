import sqlite3
from flask import Blueprint, jsonify, render_template, request
from services.indexer import DB_FILE
from services.auth import require_api_key

catalog_bp = Blueprint("catalog", __name__, url_prefix="/")

# --- Frontend pages ---
@catalog_bp.route("/catalog")
def catalog_page():
    return render_template("catalog.html")

@catalog_bp.route("/catalog/<media_id>")
def catalog_detail_page(media_id):
    return render_template("catalog_detail.html", media_id=media_id)

@catalog_bp.route("/active-catalog")
def active_catalog():
    return render_template("active_catalog.html")

@catalog_bp.route("/active-catalog/<int:media_id>")
def active_catalog_detail(media_id):
    return render_template("active_catalog_detail.html", media_id=media_id)

# --- APIs ---
@catalog_bp.route("/api/v3/catalog")
@require_api_key
def catalog_json():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT m.id, m.type, m.title, m.season_count, m.episode_count,
               m.total_size, m.tmdb_id, m.folder_path, md.poster_url
        FROM media m
        LEFT JOIN metadata md ON m.id = md.media_id
        ORDER BY m.title COLLATE NOCASE
    """)
    rows = cur.fetchall()
    conn.close()
    return jsonify([{
        "id": r["id"], "type": r["type"], "title": r["title"],
        "seasonCount": r["season_count"], "episodeCount": r["episode_count"],
        "totalSize": r["total_size"], "tmdbId": r["tmdb_id"],
        "folderPath": r["folder_path"], "posterUrl": r["poster_url"]
    } for r in rows])

@catalog_bp.route("/api/v3/catalog/active")
@require_api_key
def api_active_catalog():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, connector_id, title, media_type, tmdb_id, imdb_id, poster_url, year
        FROM connector_media
        ORDER BY title COLLATE NOCASE
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@catalog_bp.route("/api/v3/catalog/active/<int:media_id>")
@require_api_key
def api_active_media_detail(media_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    row = conn.execute("""
        SELECT m.id, m.connector_id, m.title, m.media_type, m.tmdb_id, m.imdb_id,
               m.poster_url, m.year, m.remote_id, m.title_slug,
               c.base_url, c.app_type
        FROM connector_media m
        JOIN connectors c ON m.connector_id = c.id
        WHERE m.id=?
    """, (media_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Not found"}), 404
    data = dict(row)
    if data["app_type"].lower() == "sonarr":
        slug_or_id = data.get("title_slug") or data.get("remote_id")
        data["app_url"] = f"{data['base_url'].rstrip('/')}/series/{slug_or_id}" if slug_or_id else None
    elif data["app_type"].lower() == "radarr":
        data["app_url"] = f"{data['base_url'].rstrip('/')}/movie/{data['remote_id']}" if data.get("remote_id") else None
    else:
        data["app_url"] = None
    return jsonify(data)

@catalog_bp.route("/search", methods=["GET", "POST"])
def search_page():
    query = request.args.get("q") or request.form.get("q") or ""
    results = []

    if query:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT m.id, m.title, m.type, m.folder_path,
                   d.path AS drive_path, d.device, d.brand, d.model, d.serial
            FROM media m
            LEFT JOIN drives d ON m.folder_path LIKE d.path || '%'
            WHERE m.title LIKE ?
            ORDER BY m.title ASC
        """, (f"%{query}%",))
        results = [dict(r) for r in cur.fetchall()]
        conn.close()

    return render_template("search.html", query=query, results=results)

@catalog_bp.route("/api/v3/media")
@require_api_key
def list_media():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM media").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@catalog_bp.route("/api/v3/media/<media_id>")
@require_api_key
def get_media(media_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    meta = conn.execute("SELECT * FROM metadata WHERE media_id=?", (media_id,)).fetchall()
    conn.close()
    return jsonify([dict(m) for m in meta] if meta else {"error": "not found"})

@catalog_bp.route("/api/v3/catalog/<media_id>")
@require_api_key
def api_catalog_detail(media_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    # --- Base media info ---
    row = conn.execute("""
        SELECT m.id, m.type, m.title, m.season_count, m.episode_count,
               m.total_size, m.tmdb_id, m.folder_path, 
               md.poster_url, md.backdrop_url, md.overview, md.genres, md.rating, md.year,
               d.id AS drive_id, d.path AS drive_path, d.device, d.brand,
               d.model, d.serial, d.total_size AS drive_size
        FROM media m
        LEFT JOIN metadata md ON m.id = md.media_id
        LEFT JOIN drives d ON m.folder_path LIKE d.path || '%'
        WHERE m.id=?
        ORDER BY LENGTH(d.path) DESC
        LIMIT 1
    """, (media_id,)).fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "Not found"}), 404

    # --- Seasons ---
    seasons = conn.execute("""
        SELECT id, season_number, episode_count, total_size
        FROM seasons
        WHERE media_id=?
        ORDER BY season_number ASC
    """, (media_id,)).fetchall()

    # --- Episodes (include season number) ---
    episodes = conn.execute("""
        SELECT e.id, e.season_id, s.season_number, e.episode_number, e.title, e.size
        FROM episodes e
        JOIN seasons s ON e.season_id = s.id
        WHERE s.media_id=?
        ORDER BY s.season_number ASC, e.episode_number ASC
    """, (media_id,)).fetchall()


    # --- Files ---
    files = conn.execute("""
        SELECT id, media_id, season_id, episode_id, filename, fullpath, size
        FROM files
        WHERE media_id=?
        ORDER BY filename ASC
    """, (media_id,)).fetchall()

    conn.close()

    # --- Response JSON ---
    return jsonify({
        "id": row["id"],
        "type": row["type"],
        "title": row["title"],
        "seasonCount": row["season_count"] or 0,
        "episodeCount": row["episode_count"] or 0,
        "totalSize": row["total_size"] or 0,
        "tmdbId": row["tmdb_id"],
        "folderPath": row["folder_path"],
        "posterUrl": row["poster_url"] or "",
        "backdropUrl": row["backdrop_url"] or "",
        "overview": row["overview"],
        "genres": row["genres"].split(",") if row["genres"] else [],
        "rating": row["rating"],
        "releaseYear": row["year"],
        "drive": {
            "id": row["drive_id"],
            "path": row["drive_path"],
            "device": row["device"],
            "brand": row["brand"],
            "model": row["model"],
            "serial": row["serial"],
            "size": row["drive_size"]
        } if row["drive_id"] else None,
        "seasons": [dict(s) for s in seasons],
        "episodes": [dict(e) for e in episodes],
        "files": [dict(f) for f in files]
    })


@catalog_bp.route("/api/v3/catalog/active/<int:media_id>/detail")
@require_api_key
def api_active_catalog_detail(media_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    # --- Base info from connector_media ---
    row = conn.execute("""
        SELECT m.id, m.connector_id, m.title, m.media_type, m.tmdb_id, m.imdb_id,
               m.poster_url, m.year, m.remote_id, m.title_slug,
               c.base_url, c.app_type
        FROM connector_media m
        JOIN connectors c ON m.connector_id = c.id
        WHERE m.id=?
    """, (media_id,)).fetchone()

    if not row:
        conn.close()
        return jsonify({"error": "Not found"}), 404

    # --- Seasons (if Sonarr series) ---
    seasons = []
    if row["app_type"].lower() == "sonarr":
        seasons = conn.execute("""
            SELECT id, season_number, episode_count, total_size
            FROM connector_seasons
            WHERE media_id=?
            ORDER BY season_number ASC
        """, (media_id,)).fetchall()

    # --- Episodes ---
    episodes = []
    if row["app_type"].lower() == "sonarr":
        episodes = conn.execute("""
            SELECT e.id, e.season_id, s.season_number, e.episode_number, e.title, e.size
            FROM connector_episodes e
            JOIN connector_seasons s ON e.season_id = s.id
            WHERE s.media_id=?
            ORDER BY s.season_number ASC, e.episode_number ASC
        """, (media_id,)).fetchall()

    # --- Files (if tracked) ---
    files = conn.execute("""
        SELECT id, media_id, season_id, episode_id, filename, fullpath, size
        FROM connector_files
        WHERE media_id=?
        ORDER BY filename ASC
    """, (media_id,)).fetchall()

    conn.close()

    # --- App-specific link ---
    data = dict(row)
    if data["app_type"].lower() == "sonarr":
        slug_or_id = data.get("title_slug") or data.get("remote_id")
        data["app_url"] = f"{data['base_url'].rstrip('/')}/series/{slug_or_id}" if slug_or_id else None
    elif data["app_type"].lower() == "radarr":
        data["app_url"] = f"{data['base_url'].rstrip('/')}/movie/{data['remote_id']}" if data.get("remote_id") else None
    else:
        data["app_url"] = None

    # --- Response ---
    return jsonify({
        "id": data["id"],
        "title": data["title"],
        "type": data["media_type"],
        "year": data["year"],
        "posterUrl": data["poster_url"] or "",
        "tmdbId": data["tmdb_id"],
        "imdbId": data["imdb_id"],
        "connectorId": data["connector_id"],
        "appType": data["app_type"],
        "appUrl": data["app_url"],
        "seasons": [dict(s) for s in seasons],
        "episodes": [dict(e) for e in episodes],
        "files": [dict(f) for f in files]
    })



# --- Drive APIs ---
@catalog_bp.route("/api/v3/drives")
@require_api_key
def list_drives():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM drives ORDER BY path").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@catalog_bp.route("/api/v3/drives/<int:drive_id>")
@require_api_key
def get_drive(drive_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM drives WHERE id=?", (drive_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Drive not found"}), 404
    return jsonify(dict(row))

