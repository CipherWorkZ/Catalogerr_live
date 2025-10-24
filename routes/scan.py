import threading, time, json
from flask import Blueprint, jsonify, Response, stream_with_context
from services.indexer import run_all

scan_bp = Blueprint("scan", __name__, url_prefix="/api/v3")
scan_state = {"phase":"idle","workers":{}}

@scan_bp.post("/scan")
def start_scan():
    def background_scan():
        try:
            scan_state["phase"] = "scanning"
            run_all(scan_state)
        finally:
            scan_state["phase"] = "done"
    threading.Thread(target=background_scan, daemon=True).start()
    scan_state["phase"] = "starting"
    return jsonify({"status":"scan started"})

@scan_bp.get("/scan/status")
def scan_status():
    return jsonify(scan_state)

@scan_bp.route("/scan/stream")
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



