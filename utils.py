import os, requests

POSTER_DIR = os.path.join(os.path.dirname(__file__), "static", "posters")
os.makedirs(POSTER_DIR, exist_ok=True)

def normalize_poster(media_id, poster_url, tmdb_id=None, media_type="movie", conn=None, tmdb_api_key=None, db_file=None):
    local_rel = f"/static/posters/{media_id}.jpg"
    local_abs = os.path.join(POSTER_DIR, f"{media_id}.jpg")

    if poster_url and poster_url.startswith("/static/") and os.path.exists(local_abs):
        return local_rel

    if tmdb_id and tmdb_api_key:
        try:
            url = f"https://api.themoviedb.org/3/{'tv' if media_type=='tv' else 'movie'}/{tmdb_id}"
            r = requests.get(url, params={"api_key": tmdb_api_key}, timeout=10)
            r.raise_for_status()
            data = r.json()
            if data.get("poster_path"):
                tmdb_poster_url = f"https://image.tmdb.org/t/p/w500{data['poster_path']}"
                img = requests.get(tmdb_poster_url, timeout=10)
                if img.status_code == 200:
                    with open(local_abs, "wb") as f:
                        f.write(img.content)

                    if conn:
                        cur = conn.cursor()
                        cur.execute("UPDATE metadata SET poster_url=? WHERE media_id=?", (local_rel, media_id))
                        conn.commit()

                    return local_rel
        except Exception as e:
            print(f"⚠️ Failed fetching poster for {media_id}: {e}")

    return poster_url
