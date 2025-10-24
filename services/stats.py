import sqlite3, json
from services.indexer import DB_FILE
from modules.connector import load_connectors
from datetime import datetime


def safe_int(val, default=0):
    try:
        if val is None or val == "None":
            return default
        return int(val)
    except Exception:
        return default



def get_archive_stats():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # --- Counts --- #
    counts = {
        "movies": safe_int(cur.execute("SELECT COUNT(*) FROM media WHERE type='movie'").fetchone()[0]),
        "series": safe_int(cur.execute("SELECT COUNT(*) FROM media WHERE type='tv'").fetchone()[0]),
        "episodes": safe_int(cur.execute("SELECT SUM(episode_count) FROM media WHERE type='tv'").fetchone()[0])
    }

    # --- Sizes --- #
    sizes = {
        "movies": safe_int(cur.execute("SELECT SUM(total_size) FROM media WHERE type='movie'").fetchone()[0]),
        "series": safe_int(cur.execute("SELECT SUM(total_size) FROM media WHERE type='tv'").fetchone()[0])
    }
    sizes["total"] = sizes["movies"] + sizes["series"]

    # --- Drives --- #
    drives = {
        "count": safe_int(cur.execute("SELECT COUNT(*) FROM drives").fetchone()[0]),
        "capacity": safe_int(cur.execute("SELECT SUM(total_size) FROM drives").fetchone()[0])
    }

    # 1. Media Distribution
    movies_per_drive = cur.execute("""
        SELECT d.path AS drive, COUNT(m.id) AS count
        FROM media m
        JOIN drives d ON m.drive_id = d.id
        WHERE m.type='movie'
        GROUP BY d.id
    """).fetchall()

    series_per_drive = cur.execute("""
        SELECT d.path AS drive, COUNT(m.id) AS count
        FROM media m
        JOIN drives d ON m.drive_id = d.id
        WHERE m.type='tv'
        GROUP BY d.id
    """).fetchall()

    breakdown_by_year = cur.execute("""
        SELECT release_year, COUNT(*) AS count
        FROM media
        WHERE release_year IS NOT NULL
        GROUP BY release_year
        ORDER BY release_year DESC
        LIMIT 10
    """).fetchall()

    top5_largest = cur.execute("""
        SELECT title, total_size
        FROM media
        ORDER BY total_size DESC
        LIMIT 5
    """).fetchall()

    # 2. Redundancy / Backup Awareness
    redundant = cur.execute("""
        SELECT title, COUNT(DISTINCT drive_id) AS copies
        FROM media
        GROUP BY title
    """).fetchall()

    backed_up = sum(1 for r in redundant if safe_int(r["copies"]) > 1)
    unprotected = sum(1 for r in redundant if safe_int(r["copies"]) == 1)
    total_items = len(redundant)

    redundancy = {
        "backed_up": backed_up,
        "unprotected": unprotected,
        "percent_protected": round((backed_up / total_items * 100), 2) if total_items else 0
    }

    # 3. Storage Utilization
    per_drive = cur.execute("""
        SELECT d.path AS drive,
               COALESCE(d.total_size, 0) AS total,
               COALESCE(SUM(m.total_size), 0) AS used
        FROM drives d
        LEFT JOIN media m ON m.drive_id = d.id
        GROUP BY d.id
    """).fetchall()

    utilization = {
        "per_drive": [
            {
                "drive": row["drive"],
                "total": safe_int(row["total"]),
                "used": safe_int(row["used"]),
                "percent": round((safe_int(row["used"]) / safe_int(row["total"])) * 100, 2)
                           if safe_int(row["total"]) else 0
            } for row in per_drive
        ]
    }

    # 4. Growth & Trends (disabled for now, no created_at column)
    growth = {
        "last_7_days": 0,
        "last_30_days": 0,
        "last_90_days": 0
    }

    avg_sizes = {
        "movie": cur.execute("SELECT AVG(total_size) FROM media WHERE type='movie'").fetchone()[0] or 0,
        "series": cur.execute("SELECT AVG(total_size) FROM media WHERE type='tv'").fetchone()[0] or 0
    }

    # 5. Health / Warnings
    stale_files = cur.execute("""
        SELECT id, title FROM media
        WHERE total_size=0 OR total_size IS NULL
    """).fetchall()

    duplicates = cur.execute("""
        SELECT tmdb_id, COUNT(*) AS cnt
        FROM media
        WHERE tmdb_id IS NOT NULL
        GROUP BY tmdb_id
        HAVING cnt > 1
    """).fetchall()

    conn.close()

    return {
        "counts": counts,
        "sizes": sizes,
        "drives": drives,
        "distribution": {
            "movies_per_drive": [
                {"name": row["drive"], "movie_count": row["count"]}
                for row in movies_per_drive
            ],
            "series_per_drive": [
                {"name": row["drive"], "series_count": row["count"]}
                for row in series_per_drive
            ],
            "breakdown_by_year": [
                {"year": row["release_year"], "count": row["count"]}
                for row in breakdown_by_year
            ],
            "top5_largest": [
                {"title": row["title"], "total_size": row["total_size"]}
                for row in top5_largest
            ],
        },
        "redundancy": {
            "backed_up_count": redundancy["backed_up"],
            "archive_only_count": redundancy["unprotected"],  # if no connector match
            "active_only_count": 0,  # placeholder until you check connector media
            "coverage": f"{redundancy['percent_protected']}%"
        },
        "utilization" : {
            "per_drive": [
                {
                    "drive": row["drive"],
                    "total": safe_int(row["total"]),
                    "used": safe_int(row["used"]),
                    "percent": round((safe_int(row["used"]) / safe_int(row["total"])) * 100, 2)
                            if safe_int(row["total"]) else 0
                }
                for row in per_drive
            ],
            "largest_drive": dict(max(per_drive, key=lambda r: safe_int(r["total"]), default={})) if per_drive else None,
            "smallest_drive": dict(min(per_drive, key=lambda r: safe_int(r["total"]), default={})) if per_drive else None,

        },
        "trends": {
            "added": {
                "last_7_days": growth["last_7_days"],
                "last_30_days": growth["last_30_days"],
                "last_90_days": growth["last_90_days"],
            },
            "avg_movie_size": avg_sizes["movie"],
            "avg_episode_size": avg_sizes["series"],
        },
        "health": {
            "stale": len(stale_files),
            "duplicates": [dict(row) for row in duplicates],
            "orphaned": 0  # placeholder
        }
    }


def safe_json(val, default):
    try:
        return json.loads(val) if val else default
    except Exception as e:
        print(f"[{datetime.now()}] ⚠️ JSON decode error: {e}")
        return default


def get_connector_stats():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print(f"\n[{datetime.now()}] 🔍 Fetching latest connector stats...")

    cur.execute("""
        SELECT cs.connector_id, cs.status, cs.version, cs.error,
               cs.queue, cs.diskspace, cs.checked_at,
               c.app_type
        FROM connector_stats cs
        JOIN connectors c ON cs.connector_id = c.id
        INNER JOIN (
            SELECT connector_id, MAX(checked_at) AS latest
            FROM connector_stats
            GROUP BY connector_id
        ) latest_cs
        ON cs.connector_id = latest_cs.connector_id
        AND cs.checked_at = latest_cs.latest
    """)
    rows = cur.fetchall()

    connectors = []
    for row in rows:
        print(f"\n[{datetime.now()}] 📦 DB row for {row['connector_id']}:")
        for k in row.keys():
            print(f"   {k}: {row[k]}")

        cur.execute("SELECT COUNT(*) FROM connector_media WHERE connector_id = ?", (row["connector_id"],))
        media_count = safe_int(cur.fetchone()[0])

        connector_data = {
            "id": row["connector_id"],
            "app_type": row["app_type"],
            "status": row["status"],
            "version": row["version"],
            "error": row["error"],
            "media_count": media_count,
            "queue": safe_json(row["queue"], {"records": []}),
            "diskspace": safe_json(row["diskspace"], []),
            "last_check": row["checked_at"]
        }

        connectors.append(connector_data)

        print(f"[{datetime.now()}] ✅ Final connector object for frontend:")
        for k, v in connector_data.items():
            print(f"   {k}: {v}")

    conn.close()
    print(f"[{datetime.now()}] 🎯 Total connectors fetched: {len(connectors)}\n")
    return connectors


def get_stats():
    return {
        "archive": get_archive_stats(),
        "connectors": get_connector_stats()
    }
