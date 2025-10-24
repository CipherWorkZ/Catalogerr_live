from flask import Blueprint, request, session, redirect, url_for, render_template, jsonify
import sqlite3, bcrypt
from services.indexer import DB_FILE
from services.auth import get_or_create_api_key, require_api_key

auth_bp = Blueprint("auth", __name__, url_prefix="/")

@auth_bp.route("/login", methods=["GET", "POST"])
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
            api_key = get_or_create_api_key(row[0])
            # Redirect to dashboard (or wherever) with apikey in query
            return redirect(url_for("system.dashboard", apikey=api_key))

        return render_template("login.html", error="Invalid username or password")
    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login_page"))

# API version
@auth_bp.route("/api/v3/login", methods=["POST"])
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

    api_key = get_or_create_api_key(row[0])
    return jsonify({"apiKey": api_key})
