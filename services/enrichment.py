

def enrich_unmatched():
    with engine.begin() as conn:
        result = conn.execute(text("""
            SELECT id, title FROM media
            WHERE tmdb_id IS NULL OR radarr_id IS NULL OR sonarr_id IS NULL
        """))
        for row in result.mappings():
            title = row["title"]
            media_id = row["id"]
            # call your TMDB/TVDB/OMDb lookup
            ids = match_title_to_ids(title)
            if ids:
                conn.execute(text("""
                    UPDATE media
                    SET tmdb_id = :tmdb, radarr_id = :radarr, sonarr_id = :sonarr
                    WHERE id = :id
                """), {"tmdb": ids.get("tmdb"), "radarr": ids.get("radarr"), "sonarr": ids.get("sonarr"), "id": media_id})
