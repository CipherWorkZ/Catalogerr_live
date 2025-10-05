import sqlite3
from datetime import datetime
from indexer import DB_FILE

def migrate_connector_media():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    print(f"[{datetime.now()}] 🚀 Starting migration of connector_media...")

    # 1. Check if UNIQUE constraint already exists
    cur.execute("PRAGMA table_info(connector_media)")
    cols = [c[1] for c in cur.fetchall()]
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='connector_media'")
    ddl = cur.fetchone()[0]
    if "UNIQUE(connector_id, external_id)" in ddl:
        print(f"[{datetime.now()}] ✅ connector_media already has UNIQUE constraint. No migration needed.")
        conn.close()
        return

    # 2. Backup rows
    cur.execute("SELECT * FROM connector_media")
    rows = cur.fetchall()
    colnames = [d[0] for d in cur.description]
    print(f"[{datetime.now()}] 📦 Backed up {len(rows)} rows")

    # 3. Rename old table
    cur.execute("ALTER TABLE connector_media RENAME TO connector_media_old")

    # 4. Create new table with UNIQUE constraint
    cur.execute("""
        CREATE TABLE connector_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            connector_id TEXT NOT NULL,
            media_type TEXT NOT NULL,
            external_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            year INTEGER,
            tmdb_id INTEGER,
            imdb_id TEXT,
            tvdb_id INTEGER,
            monitored INTEGER,
            added TEXT,
            raw_json TEXT,
            remote_id TEXT,
            title_slug TEXT,
            poster_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (connector_id) REFERENCES connectors(id),
            UNIQUE(connector_id, external_id) ON CONFLICT REPLACE
        )
    """)

    # 5. Insert deduplicated rows
    inserted = 0
    for row in rows:
        rowdict = dict(zip(colnames, row))
        cur.execute("""
            INSERT OR REPLACE INTO connector_media
            (connector_id, media_type, external_id, title, year, tmdb_id, imdb_id, tvdb_id,
             monitored, added, raw_json, remote_id, title_slug, poster_url, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rowdict.get("connector_id"),
            rowdict.get("media_type"),
            rowdict.get("external_id"),
            rowdict.get("title"),
            rowdict.get("year"),
            rowdict.get("tmdb_id"),
            rowdict.get("imdb_id"),
            rowdict.get("tvdb_id"),
            rowdict.get("monitored"),
            rowdict.get("added"),
            rowdict.get("raw_json"),
            rowdict.get("remote_id"),
            rowdict.get("title_slug"),
            rowdict.get("poster_url"),
            rowdict.get("created_at"),
        ))
        inserted += 1

    # 6. Drop old table
    cur.execute("DROP TABLE connector_media_old")
    conn.commit()
    conn.close()

    print(f"[{datetime.now()}] ✅ Migration complete. {inserted} rows restored with UNIQUE constraint.")


if __name__ == "__main__":
    migrate_connector_media()
