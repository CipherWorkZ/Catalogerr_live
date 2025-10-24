import sqlite3, secrets
from flask import request, jsonify, g, current_app, redirect, url_for
from functools import wraps
from services.indexer import DB_FILE  # path to your sqlite DB


def check_api_key():
    public_endpoints = {
        "api.list_movies",
        "api.list_series",
        "api.tasks_stream",
        "auth.api_login",
        "auth.login_page",
        "auth.invalid_api_page",
    }

    if request.endpoint in public_endpoints:
        return None

    token = (
        request.headers.get("X-Api-Key")
        or request.args.get("apikey")
        or request.args.get("api_key")
    )

    if not token:
        current_app.logger.warning(f"❌ API key missing for {request.endpoint}")
        return jsonify({"error": True, "message": "API key missing"}), 401

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM api_keys WHERE key=?", (token,))
    row = cur.fetchone()
    conn.close()

    if not row:
        current_app.logger.warning(
            f"❌ Invalid API key used from {request.remote_addr} ({request.endpoint})"
        )
        return jsonify({"error": True, "message": "Invalid API key"}), 401

    g.user_id = row["user_id"]
    g.api_key = token
    current_app.logger.info(f"✅ API key valid for user {g.user_id} ({request.endpoint})")
    return None


def require_api_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        resp = check_api_key()
        if resp is not None:  # validation failed
            return resp
        return fn(*args, **kwargs)
    return wrapper


def get_or_create_api_key(user_id: int) -> str:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        "SELECT key FROM api_keys WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    )
    row = cur.fetchone()

    if row:
        api_key = row["key"]
    else:
        api_key = secrets.token_hex(32)
        cur.execute("INSERT INTO api_keys (user_id, key) VALUES (?, ?)", (user_id, api_key))
        conn.commit()

    conn.close()
    return api_key
