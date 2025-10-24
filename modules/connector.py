import yaml
import os
import requests
import sqlite3
from datetime import datetime
from services.indexer import DB_FILE  # your DB file path

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_FILE = os.path.join(ROOT_DIR, "connector.yaml")


def load_connectors():
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f) or {}


def save_connectors(cfg):
    with open(CONFIG_FILE, "w") as f:
        yaml.safe_dump(cfg, f)


def fetch_connector_stats(base_url, api_key, app_type="radarr", connector_id=None):
    """
    Fetch connector stats: system status, queue, diskspace, media count.
    Also syncs local DB by removing media no longer present in Radarr/Sonarr.
    """
    base_url = base_url.rstrip("/")
    headers = {"X-Api-Key": api_key}

    stats = {
        "id": connector_id or app_type,
        "app_type": app_type,
        "status": "error",
        "version": None,
        "queue": {"records": []},
        "queue_count": 0,
        "diskspace": [],
        "disk_summary": "-",
        "media_count": 0,
        "last_check": datetime.utcnow().isoformat(),
        "error": None
    }

    def safe_get(endpoint, timeout=10):
        try:
            resp = requests.get(f"{base_url}{endpoint}", headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    # --- System status
    sysdata = safe_get("/api/v3/system/status")
    if isinstance(sysdata, dict) and "version" in sysdata:
        stats["status"] = "success"
        stats["version"] = sysdata.get("version")
    elif isinstance(sysdata, dict) and "error" in sysdata:
        stats["error"] = sysdata["error"]

    # --- Queue
    queue = safe_get("/api/v3/queue")
    if isinstance(queue, dict) and "records" in queue:
        stats["queue"] = queue
        stats["queue_count"] = len(queue.get("records", []))

    # --- Diskspace
    diskspace = safe_get("/api/v3/diskspace")
    if isinstance(diskspace, list):
        stats["diskspace"] = diskspace
        total = sum(d.get("totalSpace", 0) for d in diskspace)
        free = sum(d.get("freeSpace", 0) for d in diskspace)
        stats["disk_summary"] = (
            f"{len(diskspace)} volumes, "
            f"{round(total/1e12, 2)}TB total, "
            f"{round(free/1e12, 2)}TB free"
        )

    # --- Media sync with connector_media ---
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if connector_id:
        if app_type.lower() == "radarr":
            movies = safe_get("/api/v3/movie")
            if isinstance(movies, list):
                stats["media_count"] = len(movies)
                remote_ids = {str(m["id"]) for m in movies}

                cur.execute("SELECT id, external_id FROM connector_media WHERE connector_id=?", (connector_id,))
                local = cur.fetchall()
                for row in local:
                    if str(row["external_id"]) not in remote_ids:
                        print(f"🗑 Removing missing Radarr media: {row['external_id']}")
                        cur.execute("DELETE FROM connector_media WHERE id=?", (row["id"],))
                conn.commit()

        elif app_type.lower() == "sonarr":
            series = safe_get("/api/v3/series")
            if isinstance(series, list):
                stats["media_count"] = len(series)
                remote_ids = {str(s["id"]) for s in series}

                cur.execute("SELECT id, external_id FROM connector_media WHERE connector_id=?", (connector_id,))
                local = cur.fetchall()
                for row in local:
                    if str(row["external_id"]) not in remote_ids:
                        print(f"🗑 Removing missing Sonarr series: {row['external_id']}")
                        cur.execute("DELETE FROM connector_media WHERE id=?", (row["id"],))
                conn.commit()

    conn.close()
    return stats
