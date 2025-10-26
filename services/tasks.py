from datetime import datetime
import sqlite3, os, requests, hashlib, json, time
from services.indexer import re_enrich_all_metadata, DB_FILE
from services.utils import normalize_poster
from modules.connector import load_connectors  
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_SUBMITTED
from apscheduler.schedulers.background import BackgroundScheduler
from urllib.parse import urlparse

POSTERS_DIR = os.path.join("static", "posters")
os.makedirs(POSTERS_DIR, exist_ok=True)
# --- Config (adjust for your setup) ---
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
SONARR_URL = os.getenv("SONARR_URL", "http://192.168.1.48:8989")
SONARR_KEY = os.getenv("SONARR_KEY", "your_sonarr_api_key")
RADARR_URL = os.getenv("RADARR_URL", "http://192.168.1.48:7878")
RADARR_KEY = os.getenv("RADARR_KEY", "your_radarr_api_key")
FALLBACK_POSTER = "/static/posters/fallback.jpg"
import queue


def is_abs_url(url: str) -> bool:
    """Return True if url looks like an absolute http(s) URL."""
    if not url:
        return False
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https")
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


def download_and_cache_poster(source_url: str, filename: str) -> str:
    """
    If source_url is absolute (http/https), download to static/posters/<filename>.
    If not absolute (e.g. fallback local path), don't try to download—just return it.
    Returns a canonical web path (/static/posters/...) or the fallback path.
    """
    os.makedirs(POSTERS_DIR, exist_ok=True)

    # If it's not an absolute URL, it’s our local fallback (or already-local), just return it.
    if not is_abs_url(source_url):
        return FALLBACK_POSTER  # do NOT try to requests.get() a local /static path

    dst_path = os.path.join(POSTERS_DIR, filename)
    try:
        r = requests.get(source_url, timeout=15)
        r.raise_for_status()
        with open(dst_path, "wb") as f:
            f.write(r.content)
        return f"/static/posters/{filename}"
    except Exception as e:
        print(f"[{datetime.now()}] ⚠️ Download failed for {source_url} -> {e}")
        return FALLBACK_POSTER

# ---- TMDB helpers -----------------------------------------------------------

def tmdb_get(kind: str, tmdb_id: int):
    url = f"https://api.themoviedb.org/3/{kind}/{tmdb_id}"
    r = requests.get(url, params={"api_key": TMDB_API_KEY, "language": "en-US"}, timeout=10)
    r.raise_for_status()
    return r.json()

def tmdb_find_by_imdb(imdb_id: str):
    url = f"https://api.themoviedb.org/3/find/{imdb_id}"
    r = requests.get(url, params={"api_key": TMDB_API_KEY, "language": "en-US", "external_source": "imdb_id"}, timeout=10)
    r.raise_for_status()
    return r.json()

def build_tmdb_poster_url(poster_path: str | None) -> str | None:
    if poster_path:
        return f"https://image.tmdb.org/t/p/w500{poster_path}"
    return None

def fetch_tmdb_poster_any(tmdb_id: int, media_type: str | None) -> str | None:
    """
    Try the correct endpoint first. If unknown or wrong, try both movie and tv.
    Returns an absolute URL or None.
    """
    if not TMDB_API_KEY or not tmdb_id:
        return None

    kinds = []
    mt = (media_type or "").lower()
    if mt in ("movie", "film"):
        kinds = ["movie", "tv"]        # prefer movie, then tv just in case data is mislabeled
    elif mt in ("series", "show", "tv"):
        kinds = ["tv", "movie"]        # prefer tv, then movie
    else:
        kinds = ["movie", "tv"]        # unknown: try both

    for kind in kinds:
        try:
            data = tmdb_get(kind, tmdb_id)
            url = build_tmdb_poster_url(data.get("poster_path"))
            if url:
                return url
        except requests.HTTPError as e:
            # 404 etc. Just try the other kind
            print(f"[{datetime.now()}] ⚠️ TMDB {kind} fetch failed for {tmdb_id}: {e}")
        except Exception as e:
            print(f"[{datetime.now()}] ⚠️ TMDB {kind} error for {tmdb_id}: {e}")
    return None

def fetch_tmdb_poster_by_imdb(imdb_id: str) -> str | None:
    """
    Use /find to resolve movie_results or tv_results, take first poster_path.
    """
    if not TMDB_API_KEY or not imdb_id:
        return None
    try:
        data = tmdb_find_by_imdb(imdb_id)
        for bucket in ("movie_results", "tv_results"):
            arr = data.get(bucket) or []
            if arr:
                url = build_tmdb_poster_url(arr[0].get("poster_path"))
                if url:
                    return url
    except Exception as e:
        print(f"[{datetime.now()}] ⚠️ TMDB find-by-IMDB failed for {imdb_id}: {e}")
    return None

# ---- Sonarr/Radarr fallback -------------------------------------------------

def fetch_connector_poster(conn, connector_id: str, remote_id: int, app_type: str) -> str | None:
    """
    Try Sonarr/Radarr to retrieve an image URL if TMDB fails.
    Returns absolute URL or None.
    """
    row = conn.execute("SELECT base_url, api_key, app_type FROM connectors WHERE id=?", (connector_id,)).fetchone()
    if not row:
        return None

    base_url = (row["base_url"] or "").rstrip("/")
    api_key = row["api_key"]
    app = (row["app_type"] or app_type or "").lower()
    headers = {"X-Api-Key": api_key}

    try:
        if app == "sonarr":
            # series detail has 'images' list; try 'poster'
            url = f"{base_url}/api/v3/series/{remote_id}"
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            images = data.get("images") or []
            for img in images:
                if (img.get("coverType") == "poster") and img.get("remoteUrl"):
                    return img["remoteUrl"]
        elif app == "radarr":
            url = f"{base_url}/api/v3/movie/{remote_id}"
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            images = data.get("images") or []
            for img in images:
                if (img.get("coverType") == "poster") and img.get("remoteUrl"):
                    return img["remoteUrl"]
    except Exception as e:
        print(f"[{datetime.now()}] ⚠️ {app.title()} image fetch failed ({remote_id}): {e}")

    return None

# ---- Main re-cache ----------------------------------------------------------

def is_abs_url(url: str) -> bool:
    if not url:
        return False
    p = urlparse(url)
    return p.scheme in ("http", "https")

def ensure_fallback_exists():
    """
    Make sure /static/posters/fallback.jpg exists.
    If you’ve generated it already, great. If not, create a 1x1 gray pixel.
    """
    dst = os.path.join(POSTERS_DIR, "fallback.jpg")
    if os.path.exists(dst):
        return
    # 1x1 gray JPEG (hardcoded bytes) – keeps it simple if pillow isn't available
    one_by_one_gray = (
        b'\xff\xd8\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07'
        b'\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14'
        b'\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' "(-0-(\x1c\x1c4@43'
        b'17=9:;:1<JI>=D;:;?\xff\xc0\x00\x11\x08\x00\x01\x00\x01\x03\x01'
        b'\x11\x00\x02\x11\x01\x03\x11\x01\xff\xc4\x00\x14\x00\x01\x01\x00'
        b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x08\xff\xc4'
        b'\x00\x14\x10\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        b'\x00\x00\x00\x00\x08\xff\xda\x00\x0c\x03\x01\x00\x02\x11\x03\x11'
        b'\x00?\x00\x8f\xff\xd9'
    )
    with open(dst, "wb") as f:
        f.write(one_by_one_gray)

def local_webpath(filename: str) -> str:
    return f"/static/posters/{filename}"

def download_and_cache_poster(source_url: str, filename: str) -> str:
    """
    If source_url is http(s), download to static/posters/<filename>.
    If it's a local /static/... path (fallback), just ensure it exists and return it.
    """
    os.makedirs(POSTERS_DIR, exist_ok=True)

    # Local/fallback
    if not is_abs_url(source_url):
        ensure_fallback_exists()
        # Normalize ANY local path to the canonical fallback path
        return FALLBACK_POSTER

    # Remote download
    dst_path = os.path.join(POSTERS_DIR, filename)
    try:
        r = requests.get(source_url, timeout=15)
        r.raise_for_status()
        with open(dst_path, "wb") as f:
            f.write(r.content)
        return local_webpath(filename)
    except Exception as e:
        print(f"[{datetime.now()}] ⚠️ Download failed for {source_url} -> {e}")
        ensure_fallback_exists()
        return FALLBACK_POSTER

# --- Optional: borrow from connector_media when metadata has nothing ---------

def borrow_connector_poster(cur, tmdb_id=None, imdb_id=None, title=None, year=None) -> str | None:
    """
    Return a *local web path* to a poster that already exists for the same title
    in connector_media, preferring same tmdb_id/imdb_id.
    If the connector poster is a remote URL, we download it once locally.
    """
    # 1) try tmdb_id
    if tmdb_id:
        row = cur.execute("""
            SELECT poster_url FROM connector_media
            WHERE tmdb_id=? AND poster_url IS NOT NULL AND poster_url <> ''
            ORDER BY id DESC LIMIT 1
        """, (tmdb_id,)).fetchone()
        if row and row["poster_url"]:
            return row["poster_url"]

    # 2) try imdb_id
    if imdb_id:
        row = cur.execute("""
            SELECT poster_url FROM connector_media
            WHERE imdb_id=? AND poster_url IS NOT NULL AND poster_url <> ''
            ORDER BY id DESC LIMIT 1
        """, (imdb_id,)).fetchone()
        if row and row["poster_url"]:
            return row["poster_url"]

    # 3) fuzzy: same title (optional year)
    if title:
        if year:
            row = cur.execute("""
                SELECT poster_url FROM connector_media
                WHERE title=? AND year=? AND poster_url IS NOT NULL AND poster_url <> ''
                ORDER BY id DESC LIMIT 1
            """, (title, year)).fetchone()
            if row and row["poster_url"]:
                return row["poster_url"]
        row = cur.execute("""
            SELECT poster_url FROM connector_media
            WHERE title=? AND poster_url IS NOT NULL AND poster_url <> ''
            ORDER BY id DESC LIMIT 1
        """, (title,)).fetchone()
        if row and row["poster_url"]:
            return row["poster_url"]

    return None

def fetch_imdb_guess(title: str, year: int | None = None) -> str | None:
    """
    Try to guess a poster from IMDb search results using title/year.
    Uses the public IMDb suggest API, then resolves to TMDB poster.
    """
    if not title:
        return None
    try:
        # IMDb suggest endpoint uses the first letter of the title in the path
        from urllib.parse import quote
        key = title.lower().replace(" ", "_")
        url = f"https://v2.sg.media-imdb.com/suggestion/{key[0]}/{quote(key)}.json"

        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        # Look for the closest match (exact title/year if possible)
        results = data.get("d", [])
        for item in results:
            if "id" in item and item["id"].startswith("tt"):  # imdb ttXXXX
                imdb_id = item["id"]
                # year filter if provided
                if year and "y" in item and abs(int(item["y"]) - year) > 2:
                    continue
                # Resolve via TMDB
                return fetch_tmdb_poster_by_imdb(imdb_id)

    except Exception as e:
        print(f"[{datetime.now()}] ⚠️ IMDb guess failed for '{title}': {e}")
    return None

def fetch_imdb_guess(title: str, year: int | None = None) -> str | None:
    """
    Try to guess a poster from IMDb search results using title/year.
    Uses IMDb suggest API, then resolves to TMDB poster by imdb_id.
    """
    if not title:
        return None
    try:
        from urllib.parse import quote
        key = title.lower().replace(" ", "_")
        url = f"https://v2.sg.media-imdb.com/suggestion/{key[0]}/{quote(key)}.json"

        print(f"      🌐 IMDb guess lookup: {url}")
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        results = data.get("d", [])
        for item in results:
            if "id" in item and item["id"].startswith("tt"):
                imdb_id = item["id"]
                # check year if provided
                if year and "y" in item:
                    try:
                        if abs(int(item["y"]) - int(year)) > 2:
                            continue
                    except Exception:
                        pass
                print(f"      🎯 IMDb guess found match: {item.get('l')} ({imdb_id})")
                return fetch_tmdb_poster_by_imdb(imdb_id)

    except Exception as e:
        print(f"      ⚠️ IMDb guess failed for '{title}': {e}")
    return None


def is_cached_poster(url: str) -> bool:
    """Check if poster_url points to /static/posters and file exists physically."""
    if not url or not url.startswith("/static/posters/"):
        return False
    fname = url.replace("/static/posters/", "")
    fpath = os.path.join(POSTERS_DIR, fname)
    return os.path.exists(fpath)

from datetime import datetime

def run_poster_cache(force=True):
    """
    Re-cache posters/backdrops for metadata into /static/posters.
    For connector_media also re-cache posters straight from the DB URLs.
    """
    os.makedirs(POSTERS_DIR, exist_ok=True)
    ensure_fallback_exists()

    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # ---- METADATA (poster + backdrop) ------------------------------
        meta_rows = cur.execute("""
            SELECT media_id, poster_url, backdrop_url, title
            FROM metadata
        """).fetchall()

        print(f"[{datetime.now()}] 🎨 Re-caching posters for metadata: {len(meta_rows)} items")

        for r in meta_rows:
            media_id   = r["media_id"]
            poster_url = r["poster_url"]
            backdrop   = r["backdrop_url"]
            title      = r["title"] or ""

            print(f"[{datetime.now()}] ▶ Processing metadata: {title} ({media_id})")

            # Poster
            final_poster = FALLBACK_POSTER
            if is_abs_url(poster_url):
                fname = f"poster_{media_id}.jpg"
                print(f"[{datetime.now()}]   🌐 Downloading poster from {poster_url}")
                final_poster = download_and_cache_poster(poster_url, fname)
            elif is_cached_poster(poster_url):
                print(f"[{datetime.now()}]   ⏭ Poster already cached at {poster_url}")
                final_poster = poster_url
            else:
                print(f"[{datetime.now()}]   ⚠️ No valid poster, using fallback")

            # Backdrop
            final_backdrop = None
            if is_abs_url(backdrop):
                fname = f"backdrop_{media_id}.jpg"
                print(f"[{datetime.now()}]   🌐 Downloading backdrop from {backdrop}")
                final_backdrop = download_and_cache_poster(backdrop, fname)
            elif backdrop and is_cached_poster(backdrop):
                print(f"[{datetime.now()}]   ⏭ Backdrop already cached at {backdrop}")
                final_backdrop = backdrop
            else:
                print(f"[{datetime.now()}]   ⚠️ No valid backdrop, leaving NULL")

            safe_execute(
                cur,
                "UPDATE metadata SET poster_url=?, backdrop_url=? WHERE media_id=?",
                (final_poster, final_backdrop, media_id)
            )
            print(f"[{datetime.now()}]   ✔ Updated metadata row {media_id}")

        # ---- CONNECTOR_MEDIA (poster only) --------------------
        cm_rows = cur.execute("""
            SELECT id, poster_url, title
            FROM connector_media
        """).fetchall()

        print(f"[{datetime.now()}] 🎨 Re-caching posters for connector_media: {len(cm_rows)} items")

        for r in cm_rows:
            cmid       = r["id"]
            poster_url = r["poster_url"]
            title      = r["title"] or ""

            print(f"[{datetime.now()}] ▶ Processing connector_media: {title} (id={cmid})")

            final_poster = FALLBACK_POSTER
            if is_abs_url(poster_url):
                fname = f"poster_cm_{cmid}.jpg"
                print(f"[{datetime.now()}]   🌐 Downloading poster from {poster_url}")
                final_poster = download_and_cache_poster(poster_url, fname)
            elif is_cached_poster(poster_url):
                print(f"[{datetime.now()}]   ⏭ Poster already cached at {poster_url}")
                final_poster = poster_url
            else:
                print(f"[{datetime.now()}]   ⚠️ No valid poster, using fallback")

            safe_execute(
                cur,
                "UPDATE connector_media SET poster_url=? WHERE id=?",
                (final_poster, cmid)
            )
            print(f"[{datetime.now()}]   ✔ Updated connector_media row {cmid}")

        conn.commit()

    print(f"[{datetime.now()}] ✅ Poster cache refresh complete")

    
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

            print(f"\n[{datetime.now()}] 🔗 Syncing {app_type.upper()} ({base_url})")

            # Fetch from Radarr/Sonarr
            media_items = fetch_media(app_type, base_url, api_key)
            seen_ids = set()
            print(f"[{datetime.now()}] 📥 {app_type} returned {len(media_items)} items:")
            for m in media_items:
                print(f"   • {m.get('title')} ({m.get('id')})")

            # Fetch current DB rows (tuple unpack)
            cur.execute("SELECT external_id, title FROM connector_media WHERE connector_id=?", (cid,))
            db_rows = cur.fetchall()
            db_ids = {row[0]: row[1] for row in db_rows}  # external_id → title
            print(f"[{datetime.now()}] 💾 DB currently has {len(db_rows)} items for {app_type}:")
            for ext_id, title in db_ids.items():
                print(f"   • {title} ({ext_id})")

            # Insert/update new media
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

                if external_id not in db_ids:
                    print(f"   ➕ Adding new: {title} ({external_id})")

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

            # Remove media missing from Radarr/Sonarr
            removed_ids = [ext_id for ext_id in db_ids if ext_id not in seen_ids]
            if removed_ids:
                print(f"[{datetime.now()}] ❌ Removing {len(removed_ids)} items no longer in {app_type}:")
                for ext_id in removed_ids:
                    print(f"   • {db_ids[ext_id]} ({ext_id})")

                placeholders = ",".join("?" * len(removed_ids))
                cur.execute(
                    f"DELETE FROM connector_media WHERE connector_id=? AND external_id IN ({placeholders})",
                    (cid, *removed_ids)
                )

            # Deduplicate
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

        conn.commit()

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


# -------------------
# Drive Deduplication
# -------------------

def deduplicate_drives():
    print("=" * 60)
    print(f"[{datetime.now()}] 🔍 Starting drive deduplication task...")

    with get_db_connection() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Normalize paths (lowercase + remove trailing slash)
        cur.execute("""
            SELECT LOWER(RTRIM(path, '/')) as norm_path, COUNT(*) as cnt
            FROM drives
            WHERE path IS NOT NULL AND path <> ''
            GROUP BY norm_path
            HAVING cnt > 1
        """)
        duplicates = cur.fetchall()

        if not duplicates:
            print(f"[{datetime.now()}] ✅ No duplicate drives found.")
        else:
            print(f"[{datetime.now()}] ⚠️ Found {len(duplicates)} duplicate path groups.")

        for dup in duplicates:
            norm_path = dup["norm_path"]

            # Show all variants
            cur.execute("""
                SELECT * FROM drives
                WHERE LOWER(RTRIM(path, '/')) = ?
                ORDER BY id ASC
            """, (norm_path,))
            rows = cur.fetchall()

            ids = [row["id"] for row in rows]
            keep_id = ids[0]
            delete_ids = ids[1:]

            print(f"\n[{datetime.now()}] Path group: {norm_path}")
            for row in rows:
                print(f"   → ID {row['id']} | Path={row['path']} | Device={row['device']} | Serial={row['serial']}")

            if delete_ids:
                print(f"   ⚠️ Keeping ID {keep_id}, deleting {delete_ids}")
                cur.execute(
                    f"DELETE FROM drives WHERE id IN ({','.join(['?']*len(delete_ids))})",
                    delete_ids
                )
            else:
                print("   ✔ Only one entry kept, nothing deleted.")

        conn.commit()

    print(f"[{datetime.now()}] ✅ Drive deduplication complete")
    print("=" * 60)
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
        "id": "refresh_metadata",
        "name": "Refresh Metadata",
        "func": refresh_metadata,
        "trigger": "interval",
        "kwargs": {"hours": 6}
    },
    {
        "id": "poster_cache",
        "name": "Poster Cache (All Media)",
        "func": run_poster_cache,
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
        "id": "drive_dedup",
        "name": "Drive Deduplication",
        "func": deduplicate_drives,
        "trigger": "interval",
        "kwargs": {"minutes": 2}
    }
]