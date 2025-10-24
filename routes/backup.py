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
    timestamp=datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file=os.path.join(BACKUP_DIR,f"catalogerr_backup_{timestamp}.zip")
    with zipfile.ZipFile(backup_file,"w",zipfile.ZIP_DEFLATED) as zf:
        for f in ["index.db","config.yaml","connector.yaml",".env"]:
            if os.path.exists(f): zf.write(f,arcname=f)
    return send_file(backup_file,as_attachment=True)

@backup_bp.post("/backup/restore")
@require_api_key
def restore_backup():
    if "file" not in request.files:
        return jsonify({"error":True,"message":"No file"}),400
    file=request.files["file"]
    backup_path=os.path.join(BACKUP_DIR,"restore_upload.zip")
    file.save(backup_path)
    with zipfile.ZipFile(backup_path,"r") as zf:
        zf.extractall(os.getcwd())
    return jsonify({"status":"ok","message":"Restored"})
