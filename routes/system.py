import os, json, shutil, psutil, sqlite3, time
from datetime import datetime, timezone
from flask import Blueprint, jsonify, Response, stream_with_context, render_template, request
from services.indexer import DB_FILE
from services import settings   # <-- central service logic
from services.auth import require_api_key
system_bp = Blueprint("system", __name__, url_prefix="")

START_TIME = datetime.now(timezone.utc)

# --- Pages ---
@system_bp.route("/")
def stats_page():
    return render_template("stats.html")

@system_bp.route("/system")
def dashboard():
    return render_template("dashboard.html")

@system_bp.route("/settings")
def settings_page():
    cfg = settings.get_config()
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    drives = conn.execute("SELECT * FROM drives").fetchall()
    conn.close()
    return render_template("settings.html", config=cfg, drives=drives)

@system_bp.route("/about-us")
def aboutus():
    return render_template("about-us.html")

@system_bp.route("/channel_log")
def channel_log():
    return render_template("channel-log.html")

# --- System status SSE ---
@system_bp.route("/api/v3/system/status/stream")
@require_api_key
def system_status_stream():
    def event_stream():
        while True:
            boot_time = datetime.fromtimestamp(psutil.boot_time())
            uptime_seconds = int((datetime.utcnow() - boot_time).total_seconds())
            mem = psutil.virtual_memory()
            cpu_load = psutil.getloadavg()
            disk = psutil.disk_usage(os.getcwd())
            status = {
                "uptimeSeconds": uptime_seconds,
                "cpuLoad": f"{cpu_load[0]:.2f},{cpu_load[1]:.2f},{cpu_load[2]:.2f}",
                "memory": f"{round(mem.used/1024/1024)}MB/{round(mem.total/1024/1024)}MB",
                "disk": f"{round(disk.used/1024**3,2)}GB/{round(disk.total/1024**3,2)}GB"
            }
            yield f"data: {json.dumps(status)}\n\n"
            time.sleep(5)
    return Response(stream_with_context(event_stream()), mimetype="text/event-stream")

# --- System health ---
@system_bp.route("/api/v3/system/health")
@require_api_key
def system_health():
    issues = []
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            drives = conn.execute("SELECT path FROM drives").fetchall()
        for d in drives:
            try:
                usage = shutil.disk_usage(d["path"])
                if (usage.free/usage.total)*100 < 10:
                    issues.append({
                        "source": "Disk",
                        "type": "warning",
                        "message": f"Low space on {d['path']}"
                    })
            except Exception as e:
                issues.append({"source":"Disk","type":"error","message":str(e)})
    except Exception as e:
        issues.append({"source":"DB","type":"error","message":str(e)})
    return jsonify(issues)

# --- API: Config.yaml ---
@system_bp.route("/api/v3/config", methods=["GET"])
@require_api_key
def api_get_config():
    return jsonify(settings.get_config())

@system_bp.route("/api/v3/config", methods=["POST"])
@require_api_key
def api_save_config():
    data = request.get_json(force=True)
    return jsonify(settings.save_config(data))

# --- API: .env ---
@system_bp.route("/api/v3/env", methods=["GET"])
@require_api_key
def api_get_env():
    return jsonify(settings.get_env())

@system_bp.route("/api/v3/env", methods=["POST"])
@require_api_key
def api_save_env():
    data = request.get_json(force=True)
    return jsonify(settings.save_env(data))

# --- API Keys ---
@system_bp.route("/api/v3/apikeys", methods=["GET"])
@require_api_key
def api_list_apikeys():
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, user_id, key, created_at FROM api_keys ORDER BY id DESC").fetchall()
        return jsonify([dict(r) for r in rows])


@system_bp.route("/api/v3/apikeys", methods=["POST"])
@require_api_key
def api_create_apikey():
    new_key = secrets.token_hex(32)  # 64-char random hex
    user_id = 1  # TODO: tie this to logged-in user later
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO api_keys (user_id, key) VALUES (?, ?)", (user_id, new_key))
        conn.commit()
        row_id = cur.lastrowid
        row = conn.execute("SELECT id, user_id, key, created_at FROM api_keys WHERE id=?", (row_id,)).fetchone()
    return jsonify(dict(row))


@system_bp.route("/api/v3/apikeys/<int:key_id>", methods=["DELETE"])
@require_api_key
def api_delete_apikey(key_id):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT id, user_id, key, created_at FROM api_keys WHERE id=?", (key_id,)).fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404
        conn.execute("DELETE FROM api_keys WHERE id=?", (key_id,))
        conn.commit()
    return jsonify({"status": "deleted", "id": key_id})