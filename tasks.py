from datetime import datetime
import sqlite3, os, requests, hashlib
from indexer import re_enrich_all_metadata, DB_FILE
from utils import normalize_poster
import os, requests, hashlib, sqlite3
from indexer import DB_FILE


POSTER_DIR = os.path.join("static", "poster")
os.makedirs(POSTER_DIR, exist_ok=True)
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
def cleanup_tmp_files():
    print(f"[{datetime.now()}] 🧹 Cleaning temporary files...")

def refresh_metadata():
    print(f"[{datetime.now()}] 🔄 Refreshing metadata...")

def daily_metadata():
    print(f"[{datetime.now()}] 🎬 Re-enriching metadata…")
    re_enrich_all_metadata()

TASK_DEFINITIONS = [
    {"name": "Daily Metadata Enrichment", "func": daily_metadata, "trigger": "cron", "kwargs": {"hour": 2, "minute": 0}}
]

def recache_posters():
    print(f"[{datetime.now()}] ♻️ Re-caching posters…")
    conn = sqlite3.connect(DB_FILE)
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
    conn.close()
    print(f"[{datetime.now()}] ✅ Poster re-cache complete.")

TASK_DEFINITIONS = [
    {
        "id": "daily_metadata",
        "name": "Daily Metadata Enrichment",
        "func": daily_metadata,
        "trigger": "cron",
        "kwargs": {"hour": 2, "minute": 0}
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
    }
]
FALLBACK_POSTER = "/static/poster/fallback.jpg"  # local default
def re_enrich_all_metadata():
    """
    Force re-cache metadata posters:
    1. Always fetch from TMDB by ID
    2. If no poster, fallback to TMDB search by title
    3. If still no poster, fallback to static default poster
    4. Always update DB row
    """
    total = 0
    refreshed_count = 0
    failed_count = 0
    refreshed = []

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    rows = cur.execute("SELECT media_id, tmdb_id, title, type FROM metadata").fetchall()
    total = len([r for r in rows if r["tmdb_id"] or r["title"]])

    print(f"[{datetime.now()}] 🎬 Re-enriching {total} posters…")

    for row in rows:
        media_id = row["media_id"]
        tmdb_id = row["tmdb_id"]
        title = row["title"]
        media_type = row["type"]

        poster_path = None
        new_url = None

        try:
            # Primary: lookup by TMDB ID
            if tmdb_id:
                tmdb_url = f"https://api.themoviedb.org/3/{'tv' if media_type == 'tv' else 'movie'}/{tmdb_id}?api_key={TMDB_API_KEY}&language=en-US"
                resp = requests.get(tmdb_url, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                poster_path = data.get("poster_path")

            # Fallback 1: search by title if no poster found
            if not poster_path and title:
                search_url = f"https://api.themoviedb.org/3/search/{'tv' if media_type == 'tv' else 'movie'}"
                resp = requests.get(search_url, params={"api_key": TMDB_API_KEY, "query": title}, timeout=10)
                resp.raise_for_status()
                results = resp.json().get("results", [])
                if results:
                    poster_path = results[0].get("poster_path")

            # Fallback 2: local static
            if not poster_path:
                new_url = FALLBACK_POSTER
                print(f"[{datetime.now()}] ⚠️ No poster found for {media_id}, using fallback")
                failed_count += 1
            else:
                # Download poster fresh
                img_url = f"https://image.tmdb.org/t/p/w500{poster_path}"
                img_data = requests.get(img_url, timeout=10).content

                # Save with sha1 hash
                sha1 = hashlib.sha1(img_data).hexdigest()
                filename = f"{sha1}.jpg"
                filepath = os.path.join(POSTER_DIR, filename)

                with open(filepath, "wb") as f:
                    f.write(img_data)

                new_url = f"/static/poster/{filename}"
                refreshed_count += 1
                print(f"[{datetime.now()}] 🔄 Refreshed poster for {media_id} -> {filename}")

            # Update DB
            cur.execute("UPDATE metadata SET poster_url=? WHERE media_id=?", (new_url, media_id))
            conn.commit()
            refreshed.append({"media_id": media_id, "poster": new_url})

        except Exception as e:
            # Final fallback
            cur.execute("UPDATE metadata SET poster_url=? WHERE media_id=?", (FALLBACK_POSTER, media_id))
            conn.commit()
            failed_count += 1
            print(f"[{datetime.now()}] ❌ Failed for {media_id}, set fallback: {e}")

    conn.close()

    print(f"[{datetime.now()}] ✅ Refresh complete: {refreshed_count}/{total} posters updated, {failed_count} fallbacked.")
    return {
        "total": total,
        "updated": refreshed_count,
        "failed": failed_count,
        "details": refreshed
    }