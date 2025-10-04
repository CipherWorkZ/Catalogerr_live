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

if __name__ == "__main__":
    update_posters()
