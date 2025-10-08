import sqlite3
from flask import request, jsonify
from functools import wraps
from indexer import DB_FILE  # make sure DB_FILE points to your sqlite db

def check_api_key():
    # Public endpoints
    public_endpoints = {
        "api.list_movies",
        "api.list_series",
        "api.tasks_stream",
        "api.api_login"
    }
    if request.endpoint in public_endpoints:
        return  # allow through

    # Accept token from header OR query param (Sonarr/Radarr style)
    token = (
        request.headers.get("X-Api-Token")
        or request.headers.get("X-Api-Key")
        or request.args.get("apikey")
    )
    if not token:
        return jsonify({"error": True, "message": "Missing API key"}), 401

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM api_keys WHERE key=?", (token,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": True, "message": "Invalid API key"}), 403

    # Save for downstream handlers
    request.user_id = row[0]

def require_api_key(fn):
    """
    Decorator for routes that must enforce API key validation.
    Uses check_api_key() internally.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        resp = check_api_key()
        if resp is not None:  # check_api_key returned a Response -> error
            return resp
        return fn(*args, **kwargs)
    return wrapper

def get_or_create_api_key(user_id: int) -> str:
    """Return the most recent API key for a user, or create one if none exists."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # fetch latest key
    cur.execute("""
        SELECT key FROM api_keys
        WHERE user_id=?
        ORDER BY created_at DESC LIMIT 1
    """, (user_id,))
    row = cur.fetchone()

    if row:
        api_key = row["key"]
    else:
        api_key = secrets.token_hex(32)
        cur.execute("INSERT INTO api_keys (user_id, key) VALUES (?, ?)", (user_id, api_key))
        conn.commit()

    conn.close()
    return api_key
