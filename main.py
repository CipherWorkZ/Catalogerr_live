import os
import atexit
import sqlite3
import queue
import logging
from flask import Flask
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_SUBMITTED
from dotenv import load_dotenv

from services.indexer import create_schema, DB_FILE
from services.tasks import TASK_DEFINITIONS, register_task, TASKS, TASK_EVENTS, push_task_event
from services.jobs import job_submitted, job_executed, job_error
from routes.tasks import init_tasks

# --- Load environment ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, ".env")
load_dotenv(env_path)

# Debug: log important env vars
for key in ["RADARR_URL", "RADARR_API_KEY", "SONARR_URL", "SONARR_API_KEY", "TMDB_API_KEY"]:
    val = os.getenv(key)
    if not val:
        logging.warning(f"⚠️  Missing env var: {key}")
    else:
        logging.info(f"✅ Loaded env var: {key}={val[:6]}...")

push_task_event("start", {"task": "Scan"})

# --- Flask app ---
app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET", "changeme")

@app.context_processor
def inject_now():
    return {'now': datetime.now()}

# --- Database init ---
with sqlite3.connect(DB_FILE) as conn:
    create_schema(conn)

# --- Scheduler ---
scheduler = BackgroundScheduler()
scheduler.start()
atexit.register(lambda: scheduler.shutdown(wait=False))

for task in TASK_DEFINITIONS:
    register_task(task, scheduler, TASKS)

scheduler.add_listener(job_submitted, EVENT_JOB_SUBMITTED)
scheduler.add_listener(job_executed, EVENT_JOB_EXECUTED)
scheduler.add_listener(job_error, EVENT_JOB_ERROR)

# --- Register routes ---
from routes.auth import auth_bp
from routes.catalog import catalog_bp
from routes.drives import drives_bp
from routes.system import system_bp
from routes.scan import scan_bp
from routes.tasks import tasks_bp
from routes.connectors import connectors_bp
from routes.backup import backup_bp
from routes.list import list_bp
from routes.stats import stats_bp

# init tasks with shared queue + scheduler
TASK_EVENTS = queue.Queue()
init_tasks(scheduler)

# blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(catalog_bp)
app.register_blueprint(drives_bp)
app.register_blueprint(system_bp)
app.register_blueprint(scan_bp)
app.register_blueprint(stats_bp)
app.register_blueprint(tasks_bp)
app.register_blueprint(connectors_bp)
app.register_blueprint(backup_bp)
app.register_blueprint(list_bp)

# --- Entry point ---
if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_ENV", "development") == "development"
    app.run(debug=debug_mode, host="0.0.0.0", port=int(os.getenv("PORT", 8008)))
