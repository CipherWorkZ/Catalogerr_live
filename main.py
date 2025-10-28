import os
import atexit
import sqlite3
import queue
import logging
import json
import platform
import subprocess
from flask import Flask
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_SUBMITTED
from dotenv import load_dotenv
from logging.handlers import TimedRotatingFileHandler

from services.indexer import create_schema, DB_FILE
from services.tasks import TASK_DEFINITIONS, register_task, TASKS, TASK_EVENTS, push_task_event
from services.jobs import job_submitted, job_executed, job_error
from routes.tasks import init_tasks

# --- Load environment ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(BASE_DIR, ".env")
load_dotenv(env_path)

# --- Logging setup ---
log_dir = os.path.join(BASE_DIR, "logs")
os.makedirs(log_dir, exist_ok=True)

file_handler = TimedRotatingFileHandler(
    filename=os.path.join(log_dir, "log"),  # base name
    when="midnight",
    interval=1,
    backupCount=30,
    encoding="utf-8"
)
file_handler.suffix = "%Y-%m-%d.log"  # rotated files will be named YYYY-MM-DD.log

formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[stream_handler, file_handler]
)
logger = logging.getLogger(__name__)

# --- Collect runtime info ---
def get_runtime_info():
    try:
        os_name = subprocess.check_output(["lsb_release", "-si"]).decode().strip()
        os_version = subprocess.check_output(["lsb_release", "-sr"]).decode().strip()
    except Exception:
        os_name = platform.system()
        os_version = platform.release()
    return {
        "RUNTIME_VERSION": f"Python {platform.python_version()}",
        "OS_NAME": os_name,
        "OS_VERSION": os_version,
    }

# --- Update env.json and .env ---
def update_env_files():
    static_dir = os.path.join(BASE_DIR, "static")
    os.makedirs(static_dir, exist_ok=True)
    env_json_path = os.path.join(static_dir, "env.json")

    info = get_runtime_info()
    data = {
        "APP_NAME": os.getenv("APP_NAME", "Catalogerr"),
        "APP_VERSION": os.getenv("APP_VERSION", "dev"),
        "INSTANCE_NAME": os.getenv("INSTANCE_NAME", os.uname().nodename),
        **info
    }

    with open(env_json_path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info(f"✅ env.json generated at {env_json_path}")

    # Update only runtime keys in .env
    env_lines = []
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            env_lines = f.readlines()

    keys_to_update = ["RUNTIME_VERSION", "OS_NAME", "OS_VERSION"]
    new_lines, updated = [], set()

    for line in env_lines:
        key = line.split("=")[0].strip()
        if key in keys_to_update:
            new_lines.append(f"{key}={info[key]}\n")
            updated.add(key)
        else:
            new_lines.append(line)

    for k in keys_to_update:
        if k not in updated:
            new_lines.append(f"{k}={info[k]}\n")

    with open(env_path, "w") as f:
        f.writelines(new_lines)
    logger.info(f"✅ Updated runtime info in .env")

# Generate env.json and update .env on startup
update_env_files()

# Debug: log important env vars
for key in ["RADARR_URL", "RADARR_API_KEY", "SONARR_URL", "SONARR_API_KEY", "TMDB_API_KEY"]:
    val = os.getenv(key)
    if not val:
        logger.warning(f"⚠️  Missing env var: {key}")
    else:
        logger.info(f"✅ Loaded env var: {key}={val[:6]}...")

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

TASK_EVENTS = queue.Queue()
init_tasks(scheduler)

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
    logger.info("🚀 Starting Flask app...")
    app.run(debug=debug_mode, host="0.0.0.0", port=int(os.getenv("PORT", 8007)))
