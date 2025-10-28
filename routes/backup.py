import os, zipfile
from datetime import datetime
from flask import Blueprint, jsonify, send_file, request
from services.auth import require_api_key

backup_bp = Blueprint("backup", __name__, url_prefix="/api/v3")
BACKUP_DIR = os.path.join(os.getcwd(), "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)

@backup_bp.get("/backup")
@require_api_key
def create_backup():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"catalogerr_backup_{timestamp}.zip")

    with zipfile.ZipFile(backup_file, "w", zipfile.ZIP_DEFLATED) as zf:
        # Always include these
        for f in ["index.db", "config.yaml", "connector.yaml", ".env"]:
            if os.path.exists(f):
                zf.write(f, arcname=f)

        # Add static/posters/ recursively
        posters_dir = os.path.join(os.getcwd(), "static", "posters")
        if os.path.exists(posters_dir):
            for root, _, files in os.walk(posters_dir):
                for file in files:
                    full_path = os.path.join(root, file)
                    # arcname makes sure the folder structure inside the zip is preserved
                    rel_path = os.path.relpath(full_path, os.getcwd())
                    zf.write(full_path, arcname=rel_path)

    return send_file(backup_file, as_attachment=True)


@backup_bp.post("/backup/restore")
@require_api_key
def restore_backup():
    if "file" not in request.files:
        return jsonify({"error": True, "message": "No file"}), 400

    file = request.files["file"]
    backup_path = os.path.join(BACKUP_DIR, "restore_upload.zip")
    file.save(backup_path)

    with zipfile.ZipFile(backup_path, "r") as zf:
        # Explicitly make sure static/posters exists
        posters_dir = os.path.join(os.getcwd(), "static", "posters")
        os.makedirs(posters_dir, exist_ok=True)

        # Extract all files preserving folder structure
        for member in zf.namelist():
            target_path = os.path.join(os.getcwd(), member)
            target_dir = os.path.dirname(target_path)
            os.makedirs(target_dir, exist_ok=True)
            zf.extract(member, os.getcwd())

    return jsonify({"status": "ok", "message": "Restored"})

