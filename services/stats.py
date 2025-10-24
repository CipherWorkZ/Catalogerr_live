import os
import sqlite3
import json
import logging
from datetime import datetime
from services.indexer import DB_FILE



def safe_int(val, default=0):
    try:
        if val is None or val == "None":
            return default
        return int(val)
    except Exception:
        return default


def safe_json(val, default):
    try:
        return json.loads(val) if val else default
    except Exception as e:
        logging.warning(f"[{datetime.now()}] ⚠️ JSON decode error: {e}")
        return default

def parse_size(val):
    """Convert DB stored sizes like '2 TB', '1 GB', or numeric values into bytes."""
    if val is None or val == "None":
        return 0
    try:
        # already numeric (like media.total_size in bytes)
        if isinstance(val, (int, float)):
            return int(val)

        parts = str(val).split()
        if len(parts) != 2:
            return 0
        num, unit = float(parts[0]), parts[1].upper()
        multipliers = {
            "B": 1,
            "KB": 1024,
            "MB": 1024**2,
            "GB": 1024**3,
            "TB": 1024**4,
            "PB": 1024**5,
        }
        return int(num * multipliers.get(unit, 1))
    except Exception:
        return 0

def get_archive_stats():
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # --- Counts --- #
        counts = {
            "movies": safe_int(cur.execute("SELECT COUNT(*) FROM media WHERE type='movie'").fetchone()[0]),
            "series": safe_int(cur.execute("SELECT COUNT(*) FROM media WHERE type='tv'").fetchone()[0]),
            "episodes": safe_int(cur.execute("SELECT SUM(episode_count) FROM media WHERE type='tv'").fetchone()[0]),
        }

        # --- Sizes (already stored in bytes for media) --- #
        sizes = {
            "movies": safe_int(cur.execute("SELECT SUM(total_size) FROM media WHERE type='movie'").fetchone()[0]),
            "series": safe_int(cur.execute("SELECT SUM(total_size) FROM media WHERE type='tv'").fetchone()[0]),
        }
        sizes["total"] = sizes["movies"] + sizes["series"]

        # --- Drives --- #
        drive_rows = cur.execute("SELECT total_size FROM drives").fetchall()
        capacity = sum(parse_size(row["total_size"]) for row in drive_rows)

        drives = {
            "count": safe_int(cur.execute("SELECT COUNT(*) FROM drives").fetchone()[0]),
            "capacity": capacity,
        }

        # Distribution
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

        # Redundancy
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
            "percent_protected": round((backed_up / total_items * 100), 2) if total_items else 0,
        }

        # Utilization
        per_drive = cur.execute("""
            SELECT d.path AS drive,
                   d.total_size AS total,
                   COALESCE(SUM(m.total_size), 0) AS used
            FROM drives d
            LEFT JOIN media m ON m.drive_id = d.id
            GROUP BY d.id
        """).fetchall()

        utilization = []
        for row in per_drive:
            total_bytes = parse_size(row["total"])
            used_bytes = safe_int(row["used"])
            utilization.append({
                "drive": row["drive"],
                "total": total_bytes,
                "used": used_bytes,
                "percent": round((used_bytes / total_bytes) * 100, 2) if total_bytes else 0,
            })

        largest_drive = max(utilization, key=lambda r: r["total"], default=None)
        smallest_drive = min(utilization, key=lambda r: r["total"], default=None)

        # Health
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

        # Trends
        avg_movie_size = cur.execute(
            "SELECT AVG(total_size) FROM media WHERE type='movie'"
        ).fetchone()[0] or 0

        avg_episode_size = cur.execute(
            "SELECT AVG(total_size) FROM media WHERE type='tv'"
        ).fetchone()[0] or 0

    # conn auto-closes here

    return {
        "counts": counts,
        "sizes": sizes,
        "drives": drives,
        "distribution": {
            "movies_per_drive": [{"name": row["drive"], "movie_count": row["count"]} for row in movies_per_drive],
            "series_per_drive": [{"name": row["drive"], "series_count": row["count"]} for row in series_per_drive],
            "breakdown_by_year": [{"year": row["release_year"], "count": row["count"]} for row in breakdown_by_year],
            "top5_largest": [{"title": row["title"], "total_size": row["total_size"]} for row in top5_largest],
        },
        "redundancy": {
            "backed_up_count": redundancy["backed_up"],
            "archive_only_count": redundancy["unprotected"],
            "active_only_count": 0,  # TODO: check connector match
            "coverage": f"{redundancy['percent_protected']}%",
        },
        "utilization": {
            "per_drive": utilization,
            "largest_drive": largest_drive,
            "smallest_drive": smallest_drive,
        },
        "trends": {
            "added": {
                "last_7_days": 0,
                "last_30_days": 0,
                "last_90_days": 0,
            },
            "avg_movie_size": avg_movie_size,
            "avg_episode_size": avg_episode_size,
        },
        "health": {
            "stale": len(stale_files),
            "duplicates": [dict(row) for row in duplicates],
            "orphaned": 0,
        },
    }


def get_connector_stats():
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        logging.info(f"[{datetime.now()}] 🔍 Fetching latest connector stats...")

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
                "last_check": row["checked_at"],
            }
            connectors.append(connector_data)

        logging.info(f"[{datetime.now()}] 🎯 Total connectors fetched: {len(connectors)}")

    return connectors


def get_stats():
    archive = get_archive_stats()
    connectors = get_connector_stats()

    # --- Build quick lookup sets ---
    # Archive titles
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        archive_titles = set([
            row["title"].strip().lower()
            for row in cur.execute("SELECT title FROM media WHERE title IS NOT NULL").fetchall()
        ])

        active_titles = set([
            row["title"].strip().lower()
            for row in cur.execute("SELECT title FROM connector_media WHERE title IS NOT NULL").fetchall()
        ])

    # --- Compare sets ---
    both = archive_titles.intersection(active_titles)
    archive_only = archive_titles - active_titles
    active_only = active_titles - archive_titles

    redundancy = {
        "archive_count": len(archive_titles),
        "active_count": len(active_titles),
        "both_count": len(both),
        "archive_only_count": len(archive_only),
        "active_only_count": len(active_only),
        "coverage": f"{round((len(both) / len(archive_titles) * 100), 2) if archive_titles else 0}%"
    }

    return {
        "archive": archive,
        "connectors": connectors,
        "redundancy": redundancy
    }

