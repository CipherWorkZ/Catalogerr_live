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
def normalize_path(path: str) -> str:
    """Normalize valid absolute paths: lowercase + strip trailing slashes."""
    if not path:
        return ""
    path = path.strip()
    if not path.startswith("/"):
        # Reject relative/alias names like "movie" or "archive_tvshow"
        return ""
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

    # Save config.yaml
    with open(CONFIG_FILE, "w") as f:
        yaml.safe_dump({"parent_paths": parent_paths}, f)

    ensure_unique_path()

    yaml_paths = []
    for p in parent_paths:
        raw_path = p.get("path")
        if not raw_path:
            continue
        norm_path = normalize_path(raw_path)
        if norm_path:
            yaml_paths.append(norm_path)
        else:
            print(f"[⚠️] Skipping invalid path: {raw_path}")

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row

        # ✅ Insert new paths if missing
        for path in yaml_paths:
            exists = conn.execute("SELECT 1 FROM drives WHERE path=?", (path,)).fetchone()
            if not exists:
                conn.execute("INSERT INTO drives (path) VALUES (?)", (path,))
                print(f"[➕] Added drive path: {path}")

        # ✅ Remove paths not in config.yaml OR invalid leftovers
        db_paths = [row["path"] for row in conn.execute("SELECT path FROM drives").fetchall()]
        for db_path in db_paths:
            if db_path not in yaml_paths:
                conn.execute("DELETE FROM drives WHERE path=?", (db_path,))
                print(f"[🗑️] Removed orphan/invalid drive: {db_path}")

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
