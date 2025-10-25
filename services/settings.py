# services/settings.py
import os
import yaml
import sqlite3
from sqlalchemy import create_engine

# --- File locations (root of project) ---
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_FILE = os.path.join(ROOT_DIR, "config.yaml")
DB_FILE = os.path.join(ROOT_DIR, "index.db")
ENV_FILE = os.path.join(ROOT_DIR, ".env")

# DB engine
engine = create_engine(f"sqlite:///{DB_FILE}", future=True, echo=False)


# ----------------- Helpers -----------------
def normalize_path(path: str) -> str | None:
    """Normalize absolute filesystem paths. Reject aliases like 'movie'."""
    if not path:
        return None
    path = path.strip()

    # Must be absolute
    if not path.startswith("/"):
        return None

    # Normalize: collapse slashes, lowercase
    return os.path.normpath(path).lower()

# ----------------- DB Migrations -----------------
def ensure_unique_path():
    """Ensure drives.path has UNIQUE constraint and cleanup duplicates."""
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row

        # Check if path column already unique
        idxs = conn.execute("PRAGMA index_list(drives)").fetchall()
        has_unique = False
        for idx in idxs:
            if idx[2] == 1:  # unique index
                cols = conn.execute(f"PRAGMA index_info({idx[1]})").fetchall()
                if any(c[2] == "path" for c in cols):
                    has_unique = True
                    break

        if not has_unique:
            print("[⚡] Rebuilding drives table with UNIQUE(path)")

            rows = conn.execute("SELECT * FROM drives").fetchall()
            conn.execute("PRAGMA foreign_keys=off;")
            conn.execute("ALTER TABLE drives RENAME TO drives_old;")

            conn.execute("""
                CREATE TABLE drives (
                    id INTEGER PRIMARY KEY,   -- ✅ no AUTOINCREMENT
                    path TEXT UNIQUE,
                    device TEXT,
                    brand TEXT,
                    model TEXT,
                    serial TEXT,
                    total_size TEXT
                )
            """)

            seen = set()
            for row in rows:
                norm_path = normalize_path(row["path"])
                if norm_path not in seen:
                    conn.execute("""
                        INSERT INTO drives (path, device, brand, model, serial, total_size)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                        norm_path,
                        row["device"],
                        row["brand"],
                        row["model"],
                        row["serial"],
                        row["total_size"]
                    ))
                    seen.add(norm_path)

            conn.execute("DROP TABLE drives_old;")
            conn.commit()

        # Cleanup duplicates (keep lowest id)
        conn.execute("""
            DELETE FROM drives
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM drives
                GROUP BY LOWER(TRIM(path))
            )
        """)
        conn.commit()


# ----------------- Config.yaml logic -----------------
def get_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def save_config(data):
    parent_paths = data.get("parent_paths", [])

    # Save config.yaml as-is
    with open(CONFIG_FILE, "w") as f:
        yaml.safe_dump({"parent_paths": parent_paths}, f)

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row

        # Fetch DB paths exactly as stored
        db_rows = conn.execute("SELECT id, path FROM drives").fetchall()
        db_paths = {row["id"]: row["path"] for row in db_rows}

        yaml_paths = [p.get("path") for p in parent_paths if p.get("path")]

        # ✅ Insert only missing (no overwrite!)
        for raw_path in yaml_paths:
            if raw_path not in db_paths.values():
                conn.execute("INSERT INTO drives (path) VALUES (?)", (raw_path,))
                print(f"[➕] Added drive path: {raw_path}")

        # ✅ Remove orphaned (only delete if not in yaml)
        for db_id, db_path in db_paths.items():
            if db_path not in yaml_paths:
                conn.execute("DELETE FROM drives WHERE id=?", (db_id,))
                print(f"[🗑️] Removed drive path: {db_path}")

        conn.commit()

    return {
        "status": "saved",
        "parent_paths": parent_paths,
        "synced": yaml_paths
    }




# ----------------- ENV logic -----------------
def get_env():
    env_vars = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    env_vars[k] = v
    return env_vars


def save_env(env_vars):
    with open(ENV_FILE, "w") as f:
        for k, v in env_vars.items():
            f.write(f"{k}={v}\n")
    return {"status": "saved", "count": len(env_vars)}
