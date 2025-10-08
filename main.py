import atexit
import hashlib
import json
import os
import platform
import queue
import zipfile
import secrets
import shutil
import sqlite3
import threading
import time
import yaml
from datetime import datetime, timezone
from functools import wraps
import bcrypt
import psutil
import requests
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_SUBMITTED
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv, dotenv_values, set_key
from flask import (
    Flask, render_template, jsonify, stream_with_context, Response,
    request, Blueprint, abort, url_for, session, redirect, send_file
)
from indexer import create_schema, DB_FILE, run_all
from modules.connector import load_connectors, save_connectors, test_connection
from tasks import TASK_DEFINITIONS, register_task, TASKS, push_task_event
from services.auth import require_api_key, check_api_key, get_or_create_api_key
from modules.poster import normalize_poster
from services.jobs import job_submitted, job_executed, job_error
from services.settings import get_config, save_config

load_dotenv()
ENV_PATH = os.path.join(os.getcwd(), ".env")
SYSTEM_STATUS = {
    "appName": os.getenv("APP_NAME", "Unknown"),
    "version": os.getenv("APP_VERSION", "0.0.0"),
    "instanceName": os.getenv("INSTANCE_NAME", "Default"),
    "runtimeVersion": os.getenv("RUNTIME_VERSION", "Unknown"),
    "osName": os.getenv("OS_NAME", "Unknown"),
    "osVersion": os.getenv("OS_VERSION", "Unknown"),
}
POSTER_DIR = os.path.join(os.path.dirname(__file__), "static", "poster")
os.makedirs(POSTER_DIR, exist_ok=True)
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
app = Flask(__name__)
TASKS = {}
TASK_EVENTS = queue.Queue()
CONFIG_FILE = "config.yaml"
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
scan_state = {"phase": "idle", "workers": {}}
api = Blueprint("api", __name__, url_prefix="/api/v3")
app.secret_key = os.getenv("APP_SECRET", "changeme")
START_TIME = datetime.now(timezone.utc)
scheduler = BackgroundScheduler()
scheduler.start()
atexit.register(lambda: scheduler.shutdown(wait=False))
BACKUP_DIR = os.path.join(os.getcwd(), "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

@api.before_request
def enforce_api_key():
    from services.auth import check_api_key
    return check_api_key()

@api.get("/config")
@app.template_filter("format_size")
@app.context_processor
@api.put("/drives/<drive_id>")

def inject_now():
    return {'now': datetime.now()}

def format_size(num):
    if num is None:
        return "-"
    try:
        num = float(num)
    except (ValueError, TypeError):
        return "-"
    for unit in ["B","KB","MB","GB","TB","PB"]:
        if num < 1024.0:
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} PB"

with sqlite3.connect(DB_FILE) as conn:
    create_schema(conn)

for task in TASK_DEFINITIONS:
    register_task(task, scheduler, TASKS)

scheduler.add_listener(job_submitted, EVENT_JOB_SUBMITTED)
scheduler.add_listener(job_executed, EVENT_JOB_EXECUTED)
scheduler.add_listener(job_error, EVENT_JOB_ERROR)
app.jinja_env.filters['format_size'] = format_size

@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("SELECT id, password_hash FROM users WHERE username=?", (username,))
        row = cur.fetchone()
        conn.close()

        if row and bcrypt.checkpw(password.encode("utf-8"), row[1].encode("utf-8")):
            session["user_id"] = row[0]

            # 🔑 Reuse or create API key
            api_key = get_or_create_api_key(row[0])
            session["api_key"] = api_key

            return redirect(url_for("stats_page"))

        return render_template("login.html", error="Invalid username or password")

    return render_template("login.html")



@api.post("/login")
def api_login():
    data = request.get_json(force=True)
    username = data.get("username")
    password = data.get("password")

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id, password_hash FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()

    if not row or not bcrypt.checkpw(password.encode("utf-8"), row[1].encode("utf-8")):
        return jsonify({"error": "Invalid username or password"}), 401

    # 🔑 Reuse or create API key
    api_key = get_or_create_api_key(row[0])

    return jsonify({"apiKey": api_key})

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))

@api.post("/config")
def save_config_api():
    """Save config.yaml settings via API"""
    data = request.get_json(force=True)

    try:
        with open(CONFIG_FILE, "w") as f:
            yaml.safe_dump(data, f)
        return jsonify({"status": "ok", "saved": data})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/system")
def dashboard():
    if "user_id" not in session or "api_key" not in session:
        return redirect(url_for("login_page"))

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    drives = conn.execute("SELECT * FROM drives").fetchall()
    conn.close()
    return render_template("dashboard.html", drives=drives, api_key=session.get("api_key"))

@app.route("/scan/stream")
def scan_stream():
    def events():
        last_snapshot = None
        while True:
            snapshot = json.dumps(scan_state)
            if snapshot != last_snapshot:
                yield f"data: {snapshot}\n\n"
                last_snapshot = snapshot
            time.sleep(1)
    return Response(stream_with_context(events()), mimetype="text/event-stream")

@api.post("/scan")
def start_scan():
    def background_scan():
        try:
            scan_state["phase"] = "scanning"
            run_all(scan_state)
        finally:
            scan_state["phase"] = "done"
    threading.Thread(target=background_scan, daemon=True).start()
    scan_state["phase"] = "starting"
    return jsonify({"status": "scan started"})

@app.route("/settings")
def settings_page():
    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    drives = conn.execute("SELECT * FROM drives").fetchall()
    conn.close()

    return render_template("settings.html", config=cfg, drives=drives)

@app.route("/api/v3/enrich", methods=["POST"])
def enrich_now():
    from tasks import re_enrich_all_metadata
    updated = re_enrich_all_metadata()
    return jsonify({"status": "ok", "updated": updated})

@api.get("/drives")
def get_drives():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    drives = conn.execute("SELECT * FROM drives").fetchall()
    conn.close()
    return jsonify([dict(d) for d in drives])

@api.post("/drives")
def create_drive():
    data = request.get_json(force=True)
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO drives (id, path, device, brand, model, serial, total_size)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("id"), data.get("path"), data.get("device"),
        data.get("brand"), data.get("model"), data.get("serial"),
        data.get("total_size", 0)
    ))
    conn.commit()
    conn.close()
    return jsonify({"status": "created"})

@api.put("/drives/<drive_id>")
def update_drive(drive_id):
    data = request.get_json(force=True)
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        UPDATE drives SET path=?, device=?, brand=?, model=?, serial=?, total_size=?
        WHERE id=?
    """, (
        data.get("path"), data.get("device"), data.get("brand"),
        data.get("model"), data.get("serial"), data.get("total_size", 0),
        drive_id
    ))
    conn.commit()
    conn.close()
    return jsonify({"status": "updated"})

@api.delete("/drives/<drive_id>")
def delete_drive(drive_id):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM drives WHERE id=?", (drive_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})

@app.route("/search", methods=["GET", "POST"])
def search_page():
    results = []
    query = None

    if request.method == "POST":
        query = request.form.get("title", "").strip()
        if query:
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT m.title, d.path as drive_path, d.device, d.brand, d.model, d.serial
                FROM media m
                LEFT JOIN drives d ON m.drive_id = d.id
                WHERE lower(m.title) LIKE lower(?)
            """, (f"%{query}%",))
            results = cur.fetchall()
            conn.close()

    return render_template("search.html", query=query, results=results)


@api.get("/scan/status")
def scan_status():
    return jsonify(scan_state)


@api.get("/drives/json")
def drives_json():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    drives = conn.execute("SELECT * FROM drives").fetchall()
    conn.close()
    return jsonify([dict(d) for d in drives])


@app.route("/media")
def list_media():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM media").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/media/<media_id>")
def get_media(media_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    meta = conn.execute(
        "SELECT * FROM metadata WHERE media_id=?", (media_id,)
    ).fetchall()
    conn.close()
    return jsonify([dict(m) for m in meta] if meta else {"error": "not found"})



@api.get("/catalog")
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
        "id": r["id"],
        "type": r["type"],
        "title": r["title"],
        "seasonCount": r["season_count"],
        "episodeCount": r["episode_count"],
        "totalSize": r["total_size"],
        "tmdbId": r["tmdb_id"],
        "folderPath": r["folder_path"],
        "posterUrl": r["poster_url"]
    } for r in rows])



@api.get("/catalog/<media_id>")
def catalog_detail_json(media_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # --- Media ---
    cur.execute("""
        SELECT m.*, md.poster_url
        FROM media m
        LEFT JOIN metadata md ON m.id = md.media_id
        WHERE m.id=?
    """, (media_id,))
    media = cur.fetchone()
    if not media:
        conn.close()
        return jsonify({"error": "Not found"}), 404

    # --- Metadata ---
    cur.execute("SELECT * FROM metadata WHERE media_id=?", (media_id,))
    metadata = cur.fetchall()

    # --- Seasons & Episodes ---
    seasons, episodes = [], []
    if media["type"] == "tv":
        cur.execute("SELECT * FROM seasons WHERE media_id=? ORDER BY season_number", (media_id,))
        seasons = cur.fetchall()
        cur.execute("""
            SELECT e.*, s.season_number
            FROM episodes e
            JOIN seasons s ON e.season_id = s.id
            WHERE s.media_id=?
            ORDER BY s.season_number, e.episode_number
        """, (media_id,))
        episodes = cur.fetchall()

    # --- Files ---
    cur.execute("SELECT * FROM files WHERE media_id=?", (media_id,))
    files = cur.fetchall()
    conn.close()

    # --- Transform helpers ---
    def to_camel_media(m):
        return {
            "id": m["id"],
            "title": m["title"],
            "type": m["type"],
            "seasonCount": m["season_count"],
            "episodeCount": m["episode_count"],
            "totalSize": m["total_size"],
            "driveId": m["drive_id"],
            "folderPath": m["folder_path"],
            "tmdbId": m["tmdb_id"],
            "posterUrl": m["poster_url"]
        }
    def to_camel_metadata(md):
        md = dict(md)
        return {
            "mediaId": md.get("media_id"),
            "provider": md.get("provider"),
            "overview": md.get("overview"),
            "posterUrl": md.get("poster_url")
        }

    def to_camel_season(s):
        s = dict(s)
        return {
            "id": s.get("id"),
            "mediaId": s.get("media_id"),
            "seasonNumber": s.get("season_number"),
            "episodeCount": s.get("episode_count"),
            "totalSize": s.get("total_size")
        }

    def to_camel_episode(e):
        e = dict(e)
        return {
            "id": e.get("id"),
            "seasonId": e.get("season_id"),
            "seasonNumber": e.get("season_number"),
            "episodeNumber": e.get("episode_number"),
            "title": e.get("title"),
            "size": e.get("size")
        }

    def to_camel_file(f):
        f = dict(f)
        return {
            "id": f.get("id"),
            "mediaId": f.get("media_id"),
            "filename": f.get("filename"),
            "fullpath": f.get("fullpath"),
            "size": f.get("size")
        }


    return jsonify({
        "media": to_camel_media(media),
        "metadata": [to_camel_metadata(m) for m in metadata],
        "seasons": [to_camel_season(s) for s in seasons],
        "episodes": [to_camel_episode(e) for e in episodes],
        "files": [to_camel_file(f) for f in files]
    })


# --- FRONTEND SHELLS --- #
@app.route("/catalog")
def catalog_page():
    # Just serves the template shell; data comes from API
    return render_template("catalog.html")


@app.route("/catalog/<media_id>")
def catalog_detail_page(media_id):
    # Just serves the detail shell; JS will call /api/v3/catalog/<id>
    return render_template("catalog_detail.html", media_id=media_id)


# --- Import List APIs (for Radarr/Sonarr) --- #

# --- Radarr Import List (fully public) ---
@api.get("/list/movies")
def list_movies():
    """Radarr Import List (public, no auth)"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT m.title, m.release_year, m.tmdb_id
        FROM media m
        WHERE m.type = 'movie' AND m.tmdb_id IS NOT NULL
    """).fetchall()
    conn.close()

    return jsonify([
        {
            "title": r["title"],
            "year": r["release_year"],
            "tmdbId": r["tmdb_id"]
        }
        for r in rows
    ])


# --- Sonarr Import List (fully public) ---
@api.get("/list/series")
def list_series():
    """Sonarr Import List (public, no auth)"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT m.title, m.release_year, m.tmdb_id
        FROM media m
        WHERE m.type = 'tv' AND m.tmdb_id IS NOT NULL
    """).fetchall()
    conn.close()

    return jsonify([
        {
            "title": r["title"],
            "year": r["release_year"],
            "tvdbId": None,     # future: if you add tvdbId to schema, replace here
            "tmdbId": r["tmdb_id"]
        }
        for r in rows
    ])

@api.post("/apikeys")

def create_api_key():
    """
    Create a new API key for the logged-in user.
    Requires a valid X-Api-Token or session auth.
    """
    # Make sure request.user_id exists (set by check_api_key)
    user_id = getattr(request, "user_id", None)
    if not user_id:
        return jsonify({"error": True, "message": "Unauthorized"}), 401

    new_key = secrets.token_hex(32)

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("INSERT INTO api_keys (user_id, key) VALUES (?, ?)", (user_id, new_key))
    conn.commit()
    conn.close()

    return jsonify({
        "apiKey": new_key,
        "message": "API key created successfully"
    })


@api.get("/apikeys")
@require_api_key
def list_api_keys():
    """
    List all API keys for the logged-in user.
    """
    user_id = getattr(request, "user_id", None)
    if not user_id:
        return jsonify({"error": True, "message": "Unauthorized"}), 401

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, key, created_at FROM api_keys WHERE user_id=?", (user_id,))
    rows = cur.fetchall()
    conn.close()

    return jsonify([dict(r) for r in rows])


@api.delete("/apikeys/<int:key_id>")
def delete_api_key(key_id):
    """
    Delete an API key by ID (only if it belongs to the user).
    """
    user_id = getattr(request, "user_id", None)
    if not user_id:
        return jsonify({"error": True, "message": "Unauthorized"}), 401

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM api_keys WHERE id=? AND user_id=?", (key_id, user_id))
    deleted = cur.rowcount
    conn.commit()
    conn.close()

    if deleted:
        return jsonify({"status": "deleted", "id": key_id})
    else:
        return jsonify({"error": True, "message": "Key not found or not owned by you"}), 404




@api.get("/qualityprofile")
def quality_profiles():
    return jsonify([
        {
            "id": 1,
            "name": "HD-1080p",
            "upgradeAllowed": True
        },
        {
            "id": 2,
            "name": "4K",
            "upgradeAllowed": True
        }
    ])

@api.get("/tag")
def tags():
    return jsonify([
        {
            "id": 1,
            "label": "catalogerr",
        },
        {
            "id": 2,
            "label": "archived",
        }
    ])

# --- Dummy /command endpoint (Radarr/Sonarr expect this) ---
@api.post("/command")
def api_command():
    """
    Stub implementation to satisfy Radarr/Sonarr/Jellyseerr.
    They use /command to trigger rescans, refresh, or searches.
    We'll just log the request and return a fake success.
    """
    try:
        data = request.get_json(force=True)
    except Exception:
        data = {}

    print(f"📡 Received /command request: {data}")

    # Example Radarr/Sonarr commands you might see:
    # { "name": "RescanMovie", "movieIds": [123] }
    # { "name": "RefreshSeries", "seriesId": 456 }
    # { "name": "MissingMoviesSearch" }

    # For now, always pretend success
    return jsonify({
        "result": "success",
        "state": "completed",
        "name": data.get("name", "UnknownCommand"),
        "started": datetime.utcnow().isoformat() + "Z"
    }), 200

# --- Dummy /queue endpoint (Radarr/Sonarr expect this) ---
@api.get("/queue")
def api_queue():
    """
    Stub implementation for /queue.
    Radarr/Sonarr call this to check ongoing downloads.
    We'll return an empty list so they think nothing is downloading.
    """
    print(f"📡 Received /queue request with args: {dict(request.args)}")

    return jsonify({
        "page": 1,
        "pageSize": 0,
        "sortKey": "timeleft",
        "sortDirection": "ascending",
        "totalRecords": 0,
        "records": []   # nothing in queue
    }), 200

@api.get("/movie/lookup")
def movie_lookup():
    """
    Mimic Radarr's /movie/lookup
    Example: /api/v3/movie/lookup?term=tmdb:11017
    """
    term = request.args.get("term", "").lower()

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    def format_movie(row):
        return {
            "id": row["id"],
            "title": row["title"],
            "year": row["release_year"],
            "tmdbId": row["tmdb_id"],
            "monitored": True,
            "hasFile": True,
            "path": row["folder_path"] or f"/ARCHIVE/movies/{row['id']}",
            "sizeOnDisk": row["total_size"] or 0,
            "qualityProfileId": 1,
            "minimumAvailability": "released"
        }

    # --- Handle tmdb:ID lookups ---
    if term.startswith("tmdb:"):
        tmdb_id = term.split("tmdb:")[1]
        cur.execute("SELECT * FROM media WHERE tmdb_id=? AND type='movie'", (tmdb_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return jsonify([])
        return jsonify([format_movie(row)])

    # --- Fallback: search by title ---
    cur.execute("SELECT * FROM media WHERE lower(title) LIKE ?", (f"%{term}%",))
    rows = cur.fetchall()
    conn.close()

    return jsonify([format_movie(r) for r in rows])


@app.route("/api/v3/env", methods=["GET"])
def get_env():
    """Return all .env variables as JSON"""
    if not os.path.exists(ENV_PATH):
        return jsonify({}), 200
    return jsonify(dotenv_values(ENV_PATH))


@app.route("/api/v3/env", methods=["POST"])
def save_env():
    """Save posted variables back to .env file"""
    data = request.json or {}
    try:
        with open(ENV_PATH, "w") as f:
            for key, value in data.items():
                f.write(f"{key}={value}\n")
        return jsonify({"status": "ok", "updated": data}), 200
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@api.get("/rootFolder")
@api.get("/rootfolder")
def root_folders():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, path, total_size FROM drives").fetchall()
    conn.close()

    return jsonify([
        {
            "id": r["id"],
            "path": r["path"],
            "freeSpace": r["total_size"],
            "accessible": True
        }
        for r in rows
    ])


@api.get("/movie")
def mimic_movies():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, title, release_year, tmdb_id, folder_path, total_size
        FROM media
        WHERE type='movie' AND tmdb_id IS NOT NULL
    """).fetchall()
    conn.close()

    return jsonify([{
        "id": r["id"],
        "title": r["title"],
        "year": r["release_year"],
        "tmdbId": r["tmdb_id"],
        "monitored": True,
        "hasFile": True,
        "path": r["folder_path"] or f"/ARCHIVE/movies/{r['id']}",
        "sizeOnDisk": r["total_size"] or 0,
        "qualityProfileId": 1,
        "minimumAvailability": "released"
    } for r in rows])




@api.get("/series")
def mimic_series():
    """Return series like Sonarr would"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, title, release_year, tmdb_id
        FROM media
        WHERE type='tv' AND tmdb_id IS NOT NULL
    """).fetchall()
    conn.close()
    return jsonify([{
        "id": r["id"],
        "title": r["title"],
        "year": r["release_year"],
        "tvdbId": None,   # optional, add to schema later if needed
        "tmdbId": r["tmdb_id"],
        "monitored": False,
        "path": f"/ARCHIVE/tv/{r['id']}"
    } for r in rows])


@app.route("/api/v3/system/status/stream")
def system_status_stream():
    """
    Stream system status as Server-Sent Events (SSE).
    The frontend connects once and gets updates in real-time.
    """
    def event_stream():
        while True:
            try:
                # uptime
                boot_time = datetime.fromtimestamp(psutil.boot_time())
                uptime_seconds = int((datetime.utcnow() - boot_time).total_seconds())
                uptime_human = str(datetime.utcnow() - boot_time).split('.')[0]

                # system metrics
                mem = psutil.virtual_memory()
                cpu_load = psutil.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
                disk = psutil.disk_usage(os.getcwd())

                status = {
                    "appName": os.getenv("APP_NAME", "Catalogerr"),
                    "version": os.getenv("APP_VERSION", "0.0.1"),
                    "buildTime": datetime.utcnow().isoformat() + "Z",
                    "instanceName": os.getenv("INSTANCE_NAME", "Catalogerr Instance"),

                    # runtime
                    "runtimeName": "Python",
                    "runtimeVersion": "Python-" + ".".join(map(str, os.sys.version_info[:3])),

                    # system info
                    "osName": platform.system(),
                    "osVersion": platform.release(),
                    "arch": platform.machine(),
                    "hostname": platform.node(),
                    "uptimeSeconds": uptime_seconds,
                    "uptimeHuman": uptime_human,

                    # cpu
                    "cpuCores": os.cpu_count(),
                    "cpuLoad": f"{cpu_load[0]:.2f} (1m), {cpu_load[1]:.2f} (5m), {cpu_load[2]:.2f} (15m)",

                    # memory
                    "memory": f"{round(mem.used / (1024*1024))} MB / {round(mem.total / (1024*1024))} MB ({mem.percent:.1f}%)",

                    # disk
                    "disk": f"{round(disk.used / (1024**3), 2)} GB / {round(disk.total / (1024**3), 2)} GB ({disk.percent}%) at {os.getcwd()}"
                }

                yield f"data: {json.dumps(status)}\n\n"
                time.sleep(5)  # adjust update interval here
            except GeneratorExit:
                break

    return Response(stream_with_context(event_stream()), mimetype="text/event-stream")



@app.route("/active-catalog")
def active_catalog():
    return render_template("active_catalog.html")


@app.route("/api/v3/catalog/active", methods=["GET"])
def api_active_catalog():
    """
    Return all active media from connector_media table
    """
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT id, connector_id, title, media_type, tmdb_id, imdb_id, poster_url, year
        FROM connector_media
        ORDER BY title COLLATE NOCASE
    """).fetchall()

    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/v3/catalog/active/<int:media_id>", methods=["GET"])
def api_active_media_detail(media_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    row = cur.execute("""
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

    # Build a "native app link"
    if data["app_type"].lower() == "sonarr":
        # Prefer titleSlug if present, fallback to remote_id
        slug_or_id = data.get("title_slug") or data.get("remote_id")
        if slug_or_id:
            data["app_url"] = f"{data['base_url'].rstrip('/')}/series/{slug_or_id}"
        else:
            data["app_url"] = None
    elif data["app_type"].lower() == "radarr":
        # Radarr always uses numeric ID
        if data.get("remote_id"):
            data["app_url"] = f"{data['base_url'].rstrip('/')}/movie/{data['remote_id']}"
        else:
            data["app_url"] = None
    else:
        data["app_url"] = None

    return jsonify(data)



@app.route("/active-catalog/<int:media_id>")
def active_catalog_detail(media_id):
    return render_template("active_catalog_detail.html", media_id=media_id)

@app.route("/connector")
def connector():
    return render_template("app.html")


@api.get("/connectors")
def list_connectors():
    """
    Return all connectors with live status (tests on-demand).
    """
    cfg = load_connectors()
    result = {}

    for app, data in cfg.items():
        status = test_connection(
            data.get("base_url"),
            data.get("api_key"),
            app
        )
        # merge saved config with live test result
        result[app] = {
            "base_url": data.get("base_url"),
            "api_key": data.get("api_key"),
            "status": status.get("success"),
            "version": status.get("version"),
            "error": status.get("error")
        }

    return jsonify(result)


@api.post("/connectors")
def add_connector():
    """Add a new connector after testing the connection."""
    data = request.get_json(force=True)
    app_type = data.get("app_type")
    base_url = data.get("base_url")
    api_key = data.get("api_key")

    if not (app_type and base_url and api_key):
        return jsonify({"error": "Missing required fields"}), 400

    # test the handshake first
    result = test_connection(base_url, api_key, app_type)

    if not result["success"]:
        return jsonify(result), 400  # don't save if handshake failed

    # save connector if test passed
    cfg = load_connectors()
    cfg[app_type] = {"base_url": base_url, "api_key": api_key}
    save_connectors(cfg)

    return jsonify({
        "status": "saved",
        "message": result["message"],
        "connectors": cfg
    })


@api.get("/connectors/test/<app_type>")
def test_connector(app_type):
    """Explicitly test an existing connector."""
    cfg = load_connectors().get(app_type)
    if not cfg:
        return jsonify({"error": "Connector not found"}), 404
    return jsonify(test_connection(cfg["base_url"], cfg["api_key"], app_type))

@api.get("/system/health")
def system_health():
    """
    Mimic Sonarr/Radarr /system/health endpoint.
    Returns warnings/errors for disk space, database, etc.
    """
    issues = []

    # Example: Check for low disk space on each drive path in DB
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            drives = conn.execute("SELECT path FROM drives").fetchall()

        for d in drives:
            path = d["path"]
            try:
                usage = shutil.disk_usage(path)
                percent_free = (usage.free / usage.total) * 100
                if percent_free < 10:  # <10% free = warning
                    issues.append({
                        "source": "Disk",
                        "type": "warning",
                        "message": f"Low disk space on {path} ({percent_free:.1f}% free)"
                    })
            except Exception as e:
                issues.append({
                    "source": "Disk",
                    "type": "error",
                    "message": f"Failed to check disk {path}: {str(e)}"
                })
    except Exception as e:
        issues.append({
            "source": "Database",
            "type": "error",
            "message": f"DB access failed: {str(e)}"
        })

    # Example: Add uptime info
    uptime_seconds = (datetime.now(timezone.utc) - START_TIME).total_seconds()
    if uptime_seconds < 60:
        issues.append({
            "source": "System",
            "type": "info",
            "message": "Catalogerr just started, background tasks may still be warming up."
        })

    return jsonify(issues)

@app.route("/tasks")
def tasks_page():
    return render_template("tasks.html")

@app.route("/about-us")
def aboutus():
    return render_template("about-us.html")
@app.route("/channel_log")
def channel_log():
    return render_template("channel-log.html")

@api.get("/tasks")
def get_tasks():
    return jsonify(list(TASKS.values()))


@api.get("/tasks/stream")
def tasks_stream():
    def event_stream():
        while True:
            event = TASK_EVENTS.get()
            yield f"event: {event['event']}\n"
            yield f"data: {json.dumps(event['data'])}\n\n"

    return Response(stream_with_context(event_stream()), mimetype="text/event-stream")


@api.post("/tasks/run/<task_id>")
def run_task(task_id):
    job = scheduler.get_job(task_id)
    if not job:
        return jsonify({"error": "Task not found"}), 404

    try:
        func = job.func

        push_task_event("start", {"id": task_id, "name": job.name})
        func()  # run synchronously
        push_task_event("complete", {"id": task_id, "name": job.name, "status": "ok"})

        return jsonify({"status": "ok", "message": f"Task {job.name} executed successfully"})
    except Exception as e:
        push_task_event("error", {"id": task_id, "name": job.name, "error": str(e)})
        return jsonify({"error": str(e)}), 500

@app.route("/")
def stats_page():
    if "user_id" not in session or "api_key" not in session:
        return redirect(url_for("login_page"))

    return render_template("stats.html", api_key=session.get("api_key"))


import json

@api.get("/stats")
def get_stats():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print("📊 Building archive stats...")

    # --- Archive (media + drives) ---
    cur.execute("SELECT COUNT(*) as c FROM media WHERE type='movie'")
    movies = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM media WHERE type='tv'")
    series = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) as c FROM episodes")
    episodes = cur.fetchone()["c"]

    cur.execute("SELECT SUM(total_size) as s FROM media WHERE type='movie'")
    movie_size = cur.fetchone()["s"] or 0
    cur.execute("SELECT SUM(total_size) as s FROM media WHERE type='tv'")
    series_size = cur.fetchone()["s"] or 0

    cur.execute("SELECT COUNT(*) as c FROM drives")
    drive_count = cur.fetchone()["c"]
    cur.execute("SELECT SUM(total_size) as s FROM drives")
    drive_total_size = cur.fetchone()["s"] or 0

    archive = {
        "counts": {"movies": movies, "series": series, "episodes": episodes},
        "sizes": {
            "movies": movie_size,
            "series": series_size,
            "total": movie_size + series_size,
        },
        "drives": {"count": drive_count, "capacity": drive_total_size},
    }
    print("✅ Archive stats:", archive)

    # --- Connectors ---
    print("🔌 Building connector stats...")
    cur.execute("SELECT * FROM connectors")
    connectors = []
    for row in cur.fetchall():
        conn_id = row["id"]
        print(f"  • Connector {conn_id} ({row['app_type']})")

        # latest snapshot
        cur.execute(
            "SELECT * FROM connector_stats WHERE connector_id=? ORDER BY checked_at DESC LIMIT 1",
            (conn_id,),
        )
        stat = cur.fetchone()
        if not stat:
            print("    ⚠️ No snapshot found")
            continue
        stat = dict(stat)

        # media count
        cur.execute(
            "SELECT COUNT(*) as c FROM connector_media WHERE connector_id=?",
            (conn_id,),
        )
        media_count = cur.fetchone()["c"]

        # try to parse queue
        queue_raw = stat.get("queue")
        parsed_queue = None
        if queue_raw:
            try:
                parsed_queue = json.loads(queue_raw)
                print(f"    ↪ Queue has {parsed_queue.get('totalRecords', 0)} records")
            except Exception as e:
                print("    ❌ Failed to parse queue JSON:", e)

        connectors.append({
            "id": conn_id,
            "app_type": row["app_type"],
            "status": stat.get("status"),
            "version": stat.get("version"),
            "queue": parsed_queue,            # now returns as dict, not raw string
            "diskspace": stat.get("diskspace"),
            "last_check": stat.get("checked_at"),
            "error": stat.get("error"),
            "media_count": media_count,
        })

    conn.close()
    result = {"archive": archive, "connectors": connectors}
    print("✅ Final stats result:", result)
    return jsonify(result)

@api.get("/backup")
@require_api_key
def create_backup():
    """Create a backup zip containing DB, config.yaml, connector.yaml, .env, and static/poster folder."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"catalogerr_backup_{timestamp}.zip")

    with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add database
        if os.path.exists(DB_FILE):
            zf.write(DB_FILE, arcname="index.db")

        # Add config.yaml
        if os.path.exists(CONFIG_FILE):
            zf.write(CONFIG_FILE, arcname="config.yaml")

        # Add connector.yaml
        connector_file = "connector.yaml"
        if os.path.exists(connector_file):
            zf.write(connector_file, arcname="connector.yaml")

        # Add .env
        if os.path.exists(ENV_PATH):
            zf.write(ENV_PATH, arcname=".env")

        # Add poster folder
        poster_dir = os.path.join(os.getcwd(), "static", "poster")
        if os.path.isdir(poster_dir):
            for root, _, files in os.walk(poster_dir):
                for f in files:
                    abs_path = os.path.join(root, f)
                    rel_path = os.path.relpath(abs_path, os.getcwd())
                    zf.write(abs_path, arcname=rel_path)

    return send_file(backup_file, as_attachment=True)



@api.post("/backup/restore/file")
@require_api_key
def restore_backup_from_file():
    path = request.json.get("path")
    if not path or not os.path.exists(path):
        return jsonify({"error": True, "message": "File not found"}), 400

    try:
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(os.getcwd())
        return jsonify({"status": "ok", "message": f"Restored from {path}"})
    except Exception as e:
        return jsonify({"error": True, "message": str(e)}), 500

@api.post("/backup/restore")
@require_api_key
def restore_backup():
    """Restore a backup zip (DB, config, env, connectors, posters)."""
    try:
        if "file" not in request.files:
            return jsonify({"error": True, "message": "No file uploaded"}), 400

        file = request.files["file"]
        backup_path = os.path.join(BACKUP_DIR, "restore_upload.zip")
        file.save(backup_path)

        with zipfile.ZipFile(backup_path, "r") as zf:
            zf.extractall(os.getcwd())

        return jsonify({"status": "ok", "message": "Backup restored. Please restart Catalogerr."})

    except Exception as e:
        return jsonify({"error": True, "message": str(e)}), 500


app.register_blueprint(api)
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8008)
