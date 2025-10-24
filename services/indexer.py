import os
import re
import sqlite3
import hashlib
import yaml
import sys
import requests
from datetime import datetime
from dotenv import load_dotenv
import bcrypt

# ---------------- Config ---------------- #
DB_FILE = "index.db"

# load .env from same folder as this script
dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path)

with open("config.yaml", "r") as f:
    CONFIG = yaml.safe_load(f)

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v"}

# API keys from .env
SONARR_URL = os.getenv("SONARR_URL")
SONARR_API_KEY = os.getenv("SONARR_API_KEY")
RADARR_URL = os.getenv("RADARR_URL")
RADARR_API_KEY = os.getenv("RADARR_API_KEY")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

# ---------------- Logger ---------------- #
class Logger:
    def __init__(self, stream=sys.stdout):
        self.stream = stream

    def log(self, msg):
        ts = datetime.now().strftime("[%H:%M:%S]")
        line = f"{ts} {msg}"
        print(line, file=self.stream, flush=True)

logger = Logger()

# ---------------- Helpers ---------------- #
def sha1_str(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

tv_pattern = re.compile(
    r"^(?P<title>.+?)[ ._-]+S(?P<season>\d{1,2})E(?P<episode>\d{1,2})(?:[ ._-]+(?P<ep_title>.*?))?(?:\.\w+)?$",
    re.IGNORECASE
)

movie_pattern = re.compile(
    r"^(?P<title>.+?) \((?P<year>\d{4})\)(?: (?P<quality>.+))?$",
    re.IGNORECASE
)
tv_pattern_alt = re.compile(
    r"^(?P<title>.+?)\.S(?P<season>\d{2})E(?P<episode>\d{2})(?:\.(?P<ep_title>.+?))?\.",
    re.IGNORECASE
)

def parse_filename(filename: str, fullpath: str):
    full_lower = fullpath.lower()
    name, _ = os.path.splitext(filename)

    # --- Folder-based overrides ---
    if "/tvshows/" in full_lower or re.search(r"/season\s*\d+", full_lower):
        m = tv_pattern.match(filename) or tv_pattern_alt.match(filename)
        if m:
            return {
                "type": "tv",
                "title": m.group("title").replace('.', ' ').strip(),
                "season": int(m.group("season")),
                "episode": int(m.group("episode")),
                "ep_title": (m.group("ep_title") or "").replace('.', ' ').strip()
            }
        return {"type": "tv", "title": name}

    if "/movies/" in full_lower:
        mm = movie_pattern.match(name)
        if mm:
            return {
                "type": "movie",
                "title": mm.group("title").strip(),
                "year": int(mm.group("year")),
                "quality": mm.group("quality") or None
            }
        return {"type": "movie", "title": name}

    # --- Regex fallback ---
    m = tv_pattern.match(filename) or tv_pattern_alt.match(filename)
    if m:
        return {
            "type": "tv",
            "title": m.group("title").replace('.', ' ').strip(),
            "season": int(m.group("season")),
            "episode": int(m.group("episode")),
            "ep_title": (m.group("ep_title") or "").replace('.', ' ').strip()
        }

    mm = movie_pattern.match(name)
    if mm:
        return {
            "type": "movie",
            "title": mm.group("title").strip(),
            "year": int(mm.group("year")),
            "quality": mm.group("quality") or None
        }

    return {"type": "movie", "title": name}

def ensure_admin_user(conn):
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", ("admin",))
    row = cur.fetchone()
    if row:
        logger.log("👤 Admin user already exists.")
        return

    admin_password = os.getenv("ADMIN_PASSWORD")
    if not admin_password:
        logger.log("⚠️ No ADMIN_PASSWORD in .env, skipping admin creation.")
        return

    # Hash password with bcrypt
    hashed = bcrypt.hashpw(admin_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", ("admin", hashed))
    conn.commit()
    logger.log("✅ Admin user created from .env")

# ---------------- Metadata fetchers ---------------- #
def fetch_sonarr(title):
    if not SONARR_URL or not SONARR_API_KEY:
        return None
    try:
        r = requests.get(f"{SONARR_URL}/api/v3/series/lookup",
                         params={"term": title},
                         headers={"X-Api-Key": SONARR_API_KEY}, timeout=10)
        r.raise_for_status()
        return r.json()[0] if r.json() else None
    except Exception as e:
        logger.log(f"Sonarr lookup failed: {e}")
        return None

def fetch_radarr(title):
    if not RADARR_URL or not RADARR_API_KEY:
        return None
    try:
        r = requests.get(f"{RADARR_URL}/api/v3/movie/lookup",
                         params={"term": title},
                         headers={"X-Api-Key": RADARR_API_KEY}, timeout=10)
        r.raise_for_status()
        return r.json()[0] if r.json() else None
    except Exception as e:
        logger.log(f"Radarr lookup failed: {e}")
        return None

def fetch_tmdb(title, mtype="movie"):
    if not TMDB_API_KEY:
        return None
    try:
        base = "https://api.themoviedb.org/3/search"
        r = requests.get(f"{base}/{mtype}",
                         params={"query": title, "api_key": TMDB_API_KEY}, timeout=10)
        r.raise_for_status()
        return r.json()["results"][0] if r.json().get("results") else None
    except Exception as e:
        logger.log(f"TMDB lookup failed: {e}")
        return None

def re_enrich_all_metadata():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("SELECT id, type, title FROM media")
    all_media = cur.fetchall()

    logger.log(f"🔄 Re-enriching metadata for {len(all_media)} media items...")

    for media_id, mtype, title in all_media:
        try:
            enrich_metadata(conn, media_id, title, mtype)
        except Exception as e:
            logger.log(f"⚠️ Failed to enrich {title}: {e}")

    conn.close()
    logger.log("✅ Re-enrichment phase complete.")

# ---------------- Schema ---------------- #
def create_schema(conn):
    cur = conn.cursor()

    # --- Existing tables --- #
    cur.execute("""
    CREATE TABLE IF NOT EXISTS drives (
        id TEXT PRIMARY KEY,
        path TEXT,
        device TEXT,
        brand TEXT,
        model TEXT,
        serial TEXT,
        total_size INTEGER
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS media (
        id TEXT PRIMARY KEY,
        type TEXT,
        title TEXT,
        folder_path TEXT,
        drive_id TEXT,
        release_year INTEGER,
        quality TEXT,
        tmdb_id INTEGER,
        sonarr_id INTEGER,
        radarr_id INTEGER,
        season_count INTEGER DEFAULT 0,
        episode_count INTEGER DEFAULT 0,
        total_size INTEGER DEFAULT 0
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS seasons (
        id TEXT PRIMARY KEY,
        media_id TEXT,
        season_number INTEGER,
        folder_path TEXT,
        episode_count INTEGER DEFAULT 0,
        total_size INTEGER DEFAULT 0
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS episodes (
        id TEXT PRIMARY KEY,
        season_id TEXT,
        episode_number INTEGER,
        title TEXT,
        size INTEGER DEFAULT 0
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id TEXT PRIMARY KEY,
        media_id TEXT,
        season_id TEXT,
        episode_id TEXT,
        filename TEXT,
        fullpath TEXT,
        drive_id TEXT,
        size INTEGER DEFAULT 0,
        mtime INTEGER DEFAULT 0
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS metadata (
        media_id TEXT PRIMARY KEY,
        type TEXT,
        title TEXT,
        year INTEGER,
        overview TEXT,
        genres TEXT,
        rating REAL,
        poster_url TEXT,
        backdrop_url TEXT,
        tmdb_id INTEGER,
        imdb_id TEXT,
        sonarr_id INTEGER,
        radarr_id INTEGER
    )""")

    # --- New tables --- #
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS api_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        key TEXT UNIQUE NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")

    conn.commit()
    logger.log("💾 Database schema ensured (with users + api_keys).")


# ---------------- Drive Insert ---------------- #
# ---------------- Drive Insert ---------------- #
def insert_drive(conn, path, device=None, brand=None, model=None, serial=None, total_size=None):
    if not path:
        raise ValueError("Drive path cannot be empty")

    path = str(path)

    cur = conn.execute("""
        INSERT INTO drives (path, device, brand, model, serial, total_size)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            device=excluded.device,
            brand=excluded.brand,
            model=excluded.model,
            serial=excluded.serial,
            total_size=excluded.total_size
    """, (path, device, brand, model, serial, total_size))

    conn.commit()
    return cur.lastrowid



# ---------------- Insert Helpers ---------------- #
def enrich_metadata(conn, media_id, title, mtype="movie"):
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM metadata WHERE media_id=?", (media_id,))
    if cur.fetchone():
        return

    data, provider = None, None
    if mtype == "tv":
        data = fetch_sonarr(title) or fetch_tmdb(title, "tv")
        provider = "Sonarr" if data else "TMDB"
    else:
        data = fetch_radarr(title) or fetch_tmdb(title, "movie")
        provider = "Radarr" if data else "TMDB"

    if data:
        tmdb_id = data.get("id") if provider == "TMDB" else data.get("tmdbId")
        sonarr_id = data.get("id") if provider == "Sonarr" else None
        radarr_id = data.get("id") if provider == "Radarr" else None

        # Map common fields
        title_val = data.get("title") or data.get("name")
        overview = data.get("overview") or data.get("plot")
        year = None
        if "year" in data:
            year = data.get("year")
        elif "releaseDate" in data:
            year = data.get("releaseDate", "")[:4]

        poster = data.get("remotePoster") or data.get("poster_path")
        backdrop = data.get("backdrop_path")

        genres = None
        if isinstance(data.get("genres"), list):
            genres = ", ".join([g if isinstance(g, str) else g.get("name") for g in data["genres"]])

        rating = data.get("ratings", {}).get("value") if "ratings" in data else data.get("vote_average")

        conn.execute("""
        INSERT OR REPLACE INTO metadata
        (media_id, type, title, year, overview, genres, rating, poster_url, backdrop_url, tmdb_id, imdb_id, sonarr_id, radarr_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (media_id, mtype, title_val, year, overview, genres, rating, poster, backdrop,
              tmdb_id, data.get("imdbId"), sonarr_id, radarr_id))

        conn.execute("UPDATE media SET tmdb_id=?, sonarr_id=?, radarr_id=? WHERE id=?",
                     (tmdb_id, sonarr_id, radarr_id, media_id))

        conn.commit()
        logger.log(f"📑 Enriched {mtype}: {title} from {provider}")

def insert_file(conn, drive_id, fullpath):
    filename = os.path.basename(fullpath)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        logger.log(f"🚫 Ignored non-video file: {filename}")
        return

    parsed = parse_filename(filename, fullpath)
    file_id = sha1_str(os.path.abspath(fullpath))
    size = os.path.getsize(fullpath)
    mtime = int(os.path.getmtime(fullpath))

    # check existing
    cur = conn.cursor()
    row = cur.execute("SELECT size, mtime FROM files WHERE id=?", (file_id,)).fetchone()
    if row and row[0] == size and row[1] == mtime:
        return  # unchanged

    if parsed["type"] == "tv":
        media_id = sha1_str(parsed["title"].lower())
        season_id = sha1_str(f"{media_id}-S{parsed['season']}")
        episode_id = sha1_str(f"{season_id}-E{parsed['episode']}")
        series_folder = os.path.dirname(os.path.dirname(fullpath))
        season_folder = os.path.dirname(fullpath)

        conn.execute("INSERT OR IGNORE INTO media (id,type,title,folder_path,drive_id) VALUES (?,?,?,?,?)",
                     (media_id, "tv", parsed["title"], series_folder, drive_id))
        conn.execute("INSERT OR IGNORE INTO seasons (id,media_id,season_number,folder_path) VALUES (?,?,?,?)",
                     (season_id, media_id, parsed["season"], season_folder))
        conn.execute("INSERT OR IGNORE INTO episodes (id,season_id,episode_number,title,size) VALUES (?,?,?,?,?)",
                     (episode_id, season_id, parsed["episode"], parsed["ep_title"], size))
        conn.execute("""
            INSERT OR REPLACE INTO files (id,media_id,season_id,episode_id,filename,fullpath,drive_id,size,mtime)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (file_id, media_id, season_id, episode_id, filename, fullpath, drive_id, size, mtime))
        conn.commit()
        logger.log(f"🎬 Indexed TV: {parsed['title']} S{parsed['season']:02}E{parsed['episode']:02}")

        enrich_metadata(conn, media_id, parsed["title"], "tv")

    else:
        media_id = sha1_str(parsed["title"].lower() + str(parsed.get("year", "")))
        conn.execute("""
            INSERT OR IGNORE INTO media (id,type,title,folder_path,drive_id,release_year,quality)
            VALUES (?,?,?,?,?,?,?)
        """, (media_id, "movie", parsed["title"], os.path.dirname(fullpath),
              drive_id, parsed.get("year"), parsed.get("quality")))
        conn.execute("""
            INSERT OR REPLACE INTO files (id,media_id,filename,fullpath,drive_id,size,mtime)
            VALUES (?,?,?,?,?,?,?)
        """, (file_id, media_id, filename, fullpath, drive_id, size, mtime))
        conn.commit()
        logger.log(f"🎥 Indexed Movie: {parsed['title']} ({parsed.get('year')}) [{parsed.get('quality')}]")

        enrich_metadata(conn, media_id, parsed["title"], "movie")

# ---------------- Aggregation Updates ---------------- #
def update_counts(conn):
    logger.log("🔄 Updating season and media counts...")

    # Update TV seasons
    conn.execute("""
    UPDATE seasons
    SET episode_count = (SELECT COUNT(*) FROM episodes e WHERE e.season_id = seasons.id),
        total_size = (SELECT COALESCE(SUM(size),0) FROM episodes e WHERE e.season_id = seasons.id)
    """)

    # Update TV media
    conn.execute("""
    UPDATE media
    SET season_count = (SELECT COUNT(*) FROM seasons s WHERE s.media_id = media.id),
        episode_count = (SELECT COALESCE(SUM(episode_count),0) FROM seasons s WHERE s.media_id = media.id),
        total_size = (SELECT COALESCE(SUM(total_size),0) FROM seasons s WHERE s.media_id = media.id)
    WHERE type = 'tv'
    """)

    # Update Movies directly from files
    conn.execute("""
    UPDATE media
    SET total_size = (
        SELECT COALESCE(SUM(size),0)
        FROM files f
        WHERE f.media_id = media.id
    )
    WHERE type = 'movie'
    """)

    conn.commit()
    logger.log("✅ Counts updated.")


# ---------------- Main ---------------- #
def run_all(scan_state=None):
    conn = sqlite3.connect(DB_FILE)
    create_schema(conn)

    if scan_state is not None:
        scan_state["workers"].clear()

    for entry in CONFIG.get("parent_paths", []):
        scan_path = entry["path"]
        drive_id = insert_drive(conn, entry["name"], scan_path)
        logger.log(f"🚀 Scanning {scan_path}")

        if scan_state is not None:
            scan_state["workers"][scan_path] = "scanning"

        for root, dirs, files in os.walk(scan_path):
            for fname in files:
                fullpath = os.path.join(root, fname)
                try:
                    if scan_state is not None:
                        scan_state["workers"][fname] = "indexing"

                    insert_file(conn, drive_id, fullpath)

                    if scan_state is not None:
                        scan_state["workers"][fname] = "done"
                except Exception as e:
                    logger.log(f"⚠️ Failed {fullpath}: {e}")
                    if scan_state is not None:
                        scan_state["workers"][fname] = f"error: {e}"

        if scan_state is not None:
            scan_state["workers"][scan_path] = "done"

    update_counts(conn)
    conn.close()
    logger.log("🎉 Scan complete.")

if __name__ == "__main__":
    run_all()
