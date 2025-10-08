from datetime import datetime
import sqlite3, os, requests, hashlib, json, time
from indexer import re_enrich_all_metadata, DB_FILE
from utils import normalize_poster
from modules.connector import load_connectors  # 👈 reuse connector.yaml
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_SUBMITTED
from apscheduler.schedulers.background import BackgroundScheduler

POSTER_DIR = os.path.join("static", "poster")
os.makedirs(POSTER_DIR, exist_ok=True)
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")

FALLBACK_POSTER = "/static/poster/fallback.jpg"  # local default
import queue

# --- Global Task State ---
TASKS = {}
TASK_EVENTS = queue.Queue()

def push_task_event(event_type, data):
    TASK_EVENTS.put({
        "event": event_type,
        "data": data
    })

# Example: your existing task definitions
TASK_DEFINITIONS = [
    # define tasks here
]
# -------------------
# DB Helpers
# -------------------

def get_db_connection():
    # 30s timeout, autocommit
    return sqlite3.connect(DB_FILE, timeout=30, isolation_level=None)

def safe_execute(cur, sql, params=(), retries=5, delay=2):
    for attempt in range(retries):
        try:
            cur.execute(sql, params)
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < retries - 1:
                print(f"[{datetime.now()}] ⚠️ DB locked, retrying in {delay}s...")
                time.sleep(delay)
            else:
                raise

# -------------------
# Metadata / Posters
# -------------------

def push_task_event(event_type, data):
    TASK_EVENTS.put({
        "event": event_type,
        "data": data
    })

def cleanup_tmp_files():
    print(f"[{datetime.now()}] 🧹 Cleaning temporary files...")

def refresh_metadata():
    print(f"[{datetime.now()}] 🔄 Refreshing metadata...")

def daily_metadata():
    print(f"[{datetime.now()}] 🎬 Re-enriching metadata…")
    re_enrich_all_metadata()

def recache_posters():
    print(f"[{datetime.now()}] ♻️ Re-caching posters…")
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT media_id, poster_url, tmdb_id FROM metadata").fetchall()
        for row in rows:
            media_id = row["media_id"]
            poster_url = row["poster_url"]
            tmdb_id = row["tmdb_id"]
            cur2 = conn.execute("SELECT type FROM media WHERE id=?", (media_id,))
            media = cur2.fetchone()
            media_type = media["type"] if media else "movie"
            normalize_poster(media_id, poster_url, tmdb_id, media_type, conn)
    print(f"[{datetime.now()}] ✅ Poster re-cache complete.")

def register_task(task, scheduler, TASKS):
    # generate a stable id from the task name
    task_id = hashlib.sha1(task["name"].encode()).hexdigest()[:8]

    job = scheduler.add_job(
        task["func"],
        task["trigger"],
        id=task_id,
        **task["kwargs"]
    )

    TASKS[task_id] = {
        "id": task_id,
        "name": task["name"],
        "trigger": str(job.trigger),
        "func": task["func"].__name__,
        "status": "idle",
        "last_run": None,
        "next_run": str(job.next_run_time) if job.next_run_time else None
    }
    return job



# -------------------
# Connector Stats
# -------------------

def ensure_connector_schema(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS connectors (
            id TEXT PRIMARY KEY,
            app_type TEXT NOT NULL,
            base_url TEXT NOT NULL,
            api_key TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS connector_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            connector_id TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            status TEXT,
            version TEXT,
            error TEXT,
            queue TEXT,
            diskspace TEXT,
            FOREIGN KEY (connector_id) REFERENCES connectors(id)
        )
    """)
    conn.commit()

def ensure_media_schema(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS connector_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            connector_id TEXT NOT NULL,
            media_type TEXT NOT NULL,
            external_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            year INTEGER,
            tmdb_id INTEGER,
            imdb_id TEXT,
            tvdb_id INTEGER,
            monitored INTEGER,
            added TEXT,
            raw_json TEXT,
            remote_id TEXT,
            title_slug TEXT,
            poster_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (connector_id) REFERENCES connectors(id),
            UNIQUE(connector_id, external_id) ON CONFLICT REPLACE
        )
    """)

    cur.execute("PRAGMA table_info(connector_media)")
    existing_cols = [c[1] for c in cur.fetchall()]

    new_cols = {
        "remote_id": "TEXT",
        "title_slug": "TEXT",
        "poster_url": "TEXT",
        "created_at": "TEXT DEFAULT CURRENT_TIMESTAMP"
    }

    for col, coldef in new_cols.items():
        if col not in existing_cols:
            try:
                print(f"[{datetime.now()}] ➕ Adding column {col} to connector_media")
                cur.execute(f"ALTER TABLE connector_media ADD COLUMN {col} {coldef}")
            except sqlite3.OperationalError as e:
                print(f"[{datetime.now()}] ⚠️ Column {col} already exists or cannot add: {e}")

    conn.commit()

def fetch_media(app_type, base_url, api_key):
    headers = {"X-Api-Key": api_key}
    url = None
    if app_type.lower() == "radarr":
        url = f"{base_url.rstrip('/')}/api/v3/movie"
    elif app_type.lower() == "sonarr":
        url = f"{base_url.rstrip('/')}/api/v3/series"
    else:
        print(f"[{datetime.now()}] ⚠️ Unknown app type {app_type}, skipping media fetch")
        return []

    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        print(f"[{datetime.now()}] 📥 {app_type} returned {len(data)} media items")
        return data
    except Exception as e:
        print(f"[{datetime.now()}] ❌ Failed fetching media from {url}: {e}")
        return []

def run_connector_media_sync():
    connectors = load_connectors()
    with get_db_connection() as conn:
        ensure_connector_schema(conn)
        ensure_media_schema(conn)
        cur = conn.cursor()

        for app_type, cfg in connectors.items():
            base_url = cfg.get("base_url")
            api_key = cfg.get("api_key")
            cid = uid_for(app_type, base_url)

            media_items = fetch_media(app_type, base_url, api_key)
            seen_ids = set()

            for m in media_items:
                external_id = m.get("id")
                title = m.get("title") or m.get("titleSlug")
                year = m.get("year") or None
                tmdb_id = m.get("tmdbId") or None
                imdb_id = m.get("imdbId") or None
                tvdb_id = m.get("tvdbId") or None
                monitored = int(m.get("monitored", False))
                added = m.get("added")
                remote_id = m.get("id")
                title_slug = m.get("titleSlug")

                seen_ids.add(external_id)

                safe_execute(cur, """
                    INSERT INTO connector_media
                    (connector_id, media_type, external_id, title, year, tmdb_id, imdb_id, tvdb_id,
                     monitored, added, raw_json, remote_id, title_slug)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(connector_id, external_id) DO UPDATE SET
                      title=excluded.title,
                      year=excluded.year,
                      tmdb_id=excluded.tmdb_id,
                      imdb_id=excluded.imdb_id,
                      tvdb_id=excluded.tvdb_id,
                      monitored=excluded.monitored,
                      added=excluded.added,
                      raw_json=excluded.raw_json,
                      remote_id=excluded.remote_id,
                      title_slug=excluded.title_slug
                """, (
                    cid,
                    "movie" if app_type.lower() == "radarr" else "series",
                    external_id,
                    title,
                    year,
                    tmdb_id,
                    imdb_id,
                    tvdb_id,
                    monitored,
                    added,
                    json.dumps(m),
                    remote_id,
                    title_slug
                ))

            if seen_ids:
                safe_execute(cur, f"""
                    DELETE FROM connector_media
                    WHERE connector_id=? AND external_id NOT IN ({",".join("?" * len(seen_ids))})
                """, (cid, *seen_ids))
            else:
                safe_execute(cur, "DELETE FROM connector_media WHERE connector_id=?", (cid,))

        print(f"[{datetime.now()}] 🔍 Checking for duplicate entries...")
        cur.execute("""
            SELECT connector_id, external_id, COUNT(*) as cnt
            FROM connector_media
            GROUP BY connector_id, external_id
            HAVING cnt > 1
        """)
        duplicates = cur.fetchall()

        for row in duplicates:
            connector_id, external_id, count = row
            print(f"   ⚠️ Found {count} duplicates for {connector_id}:{external_id}")
            safe_execute(cur, """
                DELETE FROM connector_media
                WHERE id NOT IN (
                    SELECT MAX(id) FROM connector_media
                    WHERE connector_id=? AND external_id=?
                ) AND connector_id=? AND external_id=?
            """, (connector_id, external_id, connector_id, external_id))

    print(f"[{datetime.now()}] ✅ Connector media sync complete (with cleanup)")

def uid_for(app_type, base_url):
    return hashlib.sha1(f"{app_type}:{base_url}".encode()).hexdigest()[:12]

def fetch_stats(app_type, base_url, api_key):
    headers = {"X-Api-Key": api_key}
    stats = {"status": "success", "version": None, "error": None, "queue": None, "diskspace": None}

    def safe_get(path, timeout=5, retries=2):
        url = f"{base_url.rstrip('/')}{path}"
        for attempt in range(retries):
            try:
                r = requests.get(url, headers=headers, timeout=timeout)
                print(f"[{datetime.now()}] 🌐 GET {url} -> {r.status_code}")
                body_preview = r.text[:200].replace("\n", " ")
                print(f"   ↪ Response preview: {body_preview}")
                r.raise_for_status()
                return r.json()
            except Exception as e:
                if attempt < retries - 1:
                    print(f"   ⚠️ Retry {attempt+1} for {url} after error: {e}")
                    time.sleep(2)
                else:
                    print(f"   ❌ Failed fetching {url}: {e}")
                    return None

    try:
        # System status
        sysdata = safe_get("/api/v3/system/status")
        if sysdata:
            stats["version"] = sysdata.get("version")

        # Queue
        stats["queue"] = safe_get("/api/v3/queue")

        # Diskspace (more generous timeout)
        stats["diskspace"] = safe_get("/api/v3/diskspace", timeout=15)

    except Exception as e:
        stats["status"] = "error"
        stats["error"] = str(e)

    return stats
    
def run_connector_stats():
    print(f"\n[{datetime.now()}] 🚀 Starting connector stats run...")
    connectors = load_connectors()
    if not connectors:
        print(f"[{datetime.now()}] ⚠️ No connectors found in connector.yaml")
        return

    with get_db_connection() as conn:
        ensure_connector_schema(conn)
        cur = conn.cursor()

        for app_type, cfg in connectors.items():
            base_url = cfg.get("base_url")
            api_key = cfg.get("api_key")
            cid = uid_for(app_type, base_url)

            print(f"\n[{datetime.now()}] 🔗 Processing connector: {app_type.upper()} ({base_url})")
            print(f"   → Generated UID: {cid}")
            print(f"   → Using API key: {api_key[:6]}...{api_key[-4:]}")

            safe_execute(cur, """
                INSERT INTO connectors (id, app_type, base_url, api_key)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  base_url=excluded.base_url,
                  api_key=excluded.api_key
            """, (cid, app_type, base_url, api_key))
            print(f"   ✔ Connector record ensured in DB.")

            stats = fetch_stats(app_type, base_url, api_key)
            print(f"   → Stats fetched: {json.dumps(stats, indent=2)[:500]}...")

            snapshot = (
                cid,
                datetime.utcnow().isoformat(),
                stats["status"],
                stats["version"],
                stats["error"],
                json.dumps(stats["queue"]) if stats["queue"] else "[]",
                json.dumps(stats["diskspace"]) if stats["diskspace"] else "[]"
            )

            safe_execute(cur, """
                INSERT INTO connector_stats (connector_id, checked_at, status, version, error, queue, diskspace)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, snapshot)

            print(f"   ✔ Inserted snapshot into DB for {app_type.upper()} ({cid})")

    print(f"[{datetime.now()}] ✅ Connector stats run complete\n")

def ensure_media_poster_schema(conn):
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(connector_media)")
    cols = [c[1] for c in cur.fetchall()]
    if "poster_url" not in cols:
        cur.execute("ALTER TABLE connector_media ADD COLUMN poster_url TEXT")
        conn.commit()

def fetch_tmdb_poster(tmdb_id, media_type="movie"):
    if not TMDB_API_KEY or not tmdb_id:
        return None
    try:
        url = f"https://api.themoviedb.org/3/{'tv' if media_type == 'series' else 'movie'}/{tmdb_id}"
        r = requests.get(url, params={"api_key": TMDB_API_KEY, "language": "en-US"}, timeout=10)
        r.raise_for_status()
        data = r.json()
        if data.get("poster_path"):
            return f"https://image.tmdb.org/t/p/w500{data['poster_path']}"
    except Exception as e:
        print(f"[{datetime.now()}] ⚠️ TMDB poster fetch failed for {tmdb_id}: {e}")
    return None

def run_media_poster_backfill():
    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        ensure_media_poster_schema(conn)
        cur = conn.cursor()

        rows = cur.execute("SELECT id, tmdb_id, imdb_id, media_type, title FROM connector_media WHERE poster_url IS NULL OR poster_url=''").fetchall()

        print(f"[{datetime.now()}] 🎨 Backfilling posters for {len(rows)} items...")

        for row in rows:
            poster_url = None
            if row["tmdb_id"]:
                poster_url = fetch_tmdb_poster(row["tmdb_id"], row["media_type"])
            if not poster_url:
                poster_url = FALLBACK_POSTER
                print(f"   ⚠️ No TMDB poster for {row['title']} (ID {row['id']}), using fallback")

            safe_execute(cur, "UPDATE connector_media SET poster_url=? WHERE id=?", (poster_url, row["id"]))
            print(f"   ✔ Poster set for {row['title']} -> {poster_url}")

    print(f"[{datetime.now()}] ✅ Media poster backfill complete")

# -------------------
# Task Registry
# -------------------

TASK_DEFINITIONS = [
    {
        "id": "daily_metadata",
        "name": "Metadata Enrichment (30 days)",
        "func": daily_metadata,
        "trigger": "interval",
        "kwargs": {"days": 30}
    },
    {
        "id": "cleanup_tmp",
        "name": "Cleanup Temp Files",
        "func": cleanup_tmp_files,
        "trigger": "cron",
        "kwargs": {"hour": 3, "minute": 0}
    },
    {
        "id": "refresh_metadata",
        "name": "Refresh Metadata",
        "func": refresh_metadata,
        "trigger": "interval",
        "kwargs": {"hours": 6}
    },
    {
        "id": "poster_recache",
        "name": "Poster Re-Cache",
        "func": recache_posters,
        "trigger": "cron",
        "kwargs": {"hour": 4, "minute": 0}
    },
    {
        "id": "connector_stats",
        "name": "Connector Stats Collection",
        "func": run_connector_stats,
        "trigger": "interval",
        "kwargs": {"minutes": 5}
    },
    {
        "id": "connector_media_sync",
        "name": "Connector Media Sync",
        "func": run_connector_media_sync,
        "trigger": "interval",
        "kwargs": {"hours": 1}
    },
    {
        "id": "media_poster_backfill",
        "name": "Media Poster Backfill",
        "func": run_media_poster_backfill,
        "trigger": "interval",
        "kwargs": {"days": 30}
    }
]
