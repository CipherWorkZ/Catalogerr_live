import os
import sqlite3
import requests
from dotenv import load_dotenv

DB_FILE = "index.db"
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "posters")

# Load .env for TMDB key
dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path)
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

# Ensure root poster directory exists
os.makedirs(STATIC_DIR, exist_ok=True)

def fetch_tmdb_poster(tmdb_id, mtype="movie"):
    """Query TMDB for poster path using TMDB ID."""
    url = f"https://api.themoviedb.org/3/{mtype}/{tmdb_id}"
    try:
        r = requests.get(url, params={"api_key": TMDB_API_KEY}, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("poster_path")
    except Exception as e:
        print(f"⚠️ TMDB fetch failed for {tmdb_id}: {e}")
        return None

def download_and_store(media_id, poster_path):
    """Download poster and save to media-specific folder."""
    if not poster_path or not poster_path.startswith("/"):
        return None

    tmdb_url = f"https://image.tmdb.org/t/p/original{poster_path}"

    # Create per-media folder
    folder = os.path.join(STATIC_DIR, media_id)
    os.makedirs(folder, exist_ok=True)

    local_file = os.path.join(folder, "poster.jpg")
    try:
        if not os.path.exists(local_file):
            r = requests.get(tmdb_url, timeout=20)
            r.raise_for_status()
            with open(local_file, "wb") as f:
                f.write(r.content)
            print(f"📥 Downloaded poster for {media_id}")
        else:
            print(f"✔️ Poster already exists for {media_id}")

        return f"/static/posters/{media_id}/poster.jpg"
    except Exception as e:
        print(f"⚠️ Failed to download {tmdb_url}: {e}")
        return None

def update_posters():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT media_id, type, tmdb_id, poster_url FROM metadata")
    rows = cur.fetchall()

    for row in rows:
        media_id = row["media_id"]
        mtype = row["type"] or "movie"
        tmdb_id = row["tmdb_id"]
        poster_url = row["poster_url"]

        # If already local, skip
        if poster_url and poster_url.startswith("/static/"):
            continue

        # If we have a TMDB id, fetch poster path
        poster_path = None
        if tmdb_id:
            poster_path = fetch_tmdb_poster(tmdb_id, mtype)

        # Otherwise, reuse whatever is in poster_url (if relative)
        if not poster_path and poster_url and poster_url.startswith("/"):
            poster_path = poster_url

        if not poster_path:
            print(f"❌ No poster found for {media_id}")
            continue

        new_url = download_and_store(media_id, poster_path)
        if new_url:
            cur.execute(
                "UPDATE metadata SET poster_url=? WHERE media_id=?",
                (new_url, media_id)
            )
            conn.commit()

    conn.close()
    print("✅ Poster update complete.")

def normalize_poster(media_id, poster_url, tmdb_id=None, media_type="movie", conn=None):
    """
    Ensure poster_url is usable:
    - If local exists -> return it
    - If not but TMDB available -> download, save, update DB
    """
    # Local poster path
    local_rel = f"/static/poster/{media_id}.jpg"
    local_abs = os.path.join(POSTER_DIR, f"{media_id}.jpg")

    # ✅ Already local and file exists
    if poster_url and poster_url.startswith("/static/") and os.path.exists(local_abs):
        return local_rel

    # ❌ Local missing but DB says it should be local -> fallback
    if poster_url and poster_url.startswith("/static/") and not os.path.exists(local_abs):
        print(f"⚠️ Poster missing on disk for {media_id}, refetching from TMDB...")

    # Fetch from TMDB if we have an id
    if tmdb_id:
        try:
            url = f"https://api.themoviedb.org/3/{'tv' if media_type=='tv' else 'movie'}/{tmdb_id}"
            r = requests.get(url, params={"api_key": TMDB_API_KEY}, timeout=10)
            r.raise_for_status()
            data = r.json()
            if data.get("poster_path"):
                tmdb_poster_url = f"https://image.tmdb.org/t/p/w500{data['poster_path']}"

                # Download and save locally
                img = requests.get(tmdb_poster_url, timeout=10)
                if img.status_code == 200:
                    with open(local_abs, "wb") as f:
                        f.write(img.content)
                    print(f"📥 Cached poster for {media_id}")

                    # Update DB to use local path
                    if conn:
                        cur = conn.cursor()
                        cur.execute("UPDATE metadata SET poster_url=? WHERE media_id=?", (local_rel, media_id))
                        conn.commit()

                    return local_rel
        except Exception as e:
            print(f"⚠️ Failed fetching poster for {media_id}: {e}")

    # Fallback: return remote URL if we had one in DB
    if poster_url and poster_url.startswith("http"):
        return poster_url

    return None

if __name__ == "__main__":
    update_posters()
