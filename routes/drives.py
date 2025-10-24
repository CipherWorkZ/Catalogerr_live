import sqlite3
from flask import Blueprint, jsonify, request
from services.indexer import DB_FILE

drives_bp = Blueprint("drives", __name__, url_prefix="/api/v3")

@drives_bp.get("/drives")
def get_drives():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    drives = conn.execute("SELECT * FROM drives").fetchall()
    conn.close()
    return jsonify([dict(d) for d in drives])

@drives_bp.post("/drives")
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

@drives_bp.put("/drives/<drive_id>")
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

@drives_bp.delete("/drives/<drive_id>")
def delete_drive(drive_id):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM drives WHERE id=?", (drive_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})

@drives_bp.get("/rootFolder")
@drives_bp.get("/rootfolder")
def root_folders():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, path, total_size FROM drives").fetchall()
    conn.close()
    return jsonify([{
        "id": r["id"], "path": r["path"],
        "freeSpace": r["total_size"], "accessible": True
    } for r in rows])

@drives_bp.get("/drives/json")
def get_drives_json():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    drives = conn.execute("SELECT * FROM drives").fetchall()
    conn.close()
    return jsonify([dict(d) for d in drives])
