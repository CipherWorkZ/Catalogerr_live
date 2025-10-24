import json, queue, sqlite3
from flask import Blueprint, jsonify, Response, stream_with_context, render_template, request
from services.tasks import TASK_EVENTS, TASKS, push_task_event
from apscheduler.schedulers.background import BackgroundScheduler
from services.auth import require_api_key
from services.indexer import DB_FILE

tasks_bp = Blueprint("tasks", __name__, url_prefix="/api/v3")

scheduler = None


def init_tasks(sched):
    global scheduler
    scheduler = sched

# ---------------- Frontend page ----------------
@tasks_bp.route("/tasks/ui")
def tasks_page():
    """Render UI page for tasks"""
    return render_template("tasks.html")


# ---------------- API ----------------
@tasks_bp.get("/tasks")
@require_api_key
def get_tasks():
    """Return list of registered tasks"""
    return jsonify(list(TASKS.values()))


@tasks_bp.get("/tasks/stream")
def tasks_stream():
    """Server-Sent Events stream of task events with API key via query string"""
    token = request.args.get("api_key") or request.args.get("apikey")
    if not token:
        return jsonify({"error": "API key required"}), 401

    # Inline API key validation (same logic as check_api_key)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM api_keys WHERE key=?", (token,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Invalid API key"}), 401

    # If valid -> start streaming events
    def event_stream():
        while True:
            try:
                event = TASK_EVENTS.get(timeout=5)  # wait max 5s
                yield f"event: {event['event']}\n"
                yield f"data: {json.dumps(event['data'])}\n\n"
            except queue.Empty:
                yield ": keep-alive\n\n"

    return Response(stream_with_context(event_stream()), mimetype="text/event-stream")


@tasks_bp.post("/tasks/run/<task_id>")
@require_api_key
def run_task(task_id):
    """Manually trigger a scheduled job"""
    job = scheduler.get_job(task_id)
    if not job:
        return jsonify({"error": "Task not found"}), 404
    try:
        push_task_event("start", {"id": task_id, "name": job.name})
        job.func()
        push_task_event("complete", {"id": task_id, "name": job.name, "status": "ok"})
        return jsonify({"status": "ok", "message": f"Task {job.name} executed"})
    except Exception as e:
        push_task_event("error", {"id": task_id, "name": job.name, "error": str(e)})
        return jsonify({"error": str(e)}), 500
