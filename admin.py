#!/usr/bin/env python3
"""
Create or update an admin user in the SQLite DB and optionally generate an API key.

Reads ADMIN_USER and ADMIN_PASSWORD from .env by default (optional).
If not present, prompts interactively.

Usage:
  python admin.py
"""

import os
import sqlite3
import secrets
import bcrypt
import logging
from logging.handlers import TimedRotatingFileHandler
from dotenv import load_dotenv
from getpass import getpass
from pathlib import Path

# --- Paths ---
here = Path(__file__).resolve().parent
dotenv_path = here / ".env"
load_dotenv(dotenv_path)

# --- Logging setup ---
log_dir = here / "logs"
log_dir.mkdir(exist_ok=True)

file_handler = TimedRotatingFileHandler(
    filename=log_dir / "log",   # base name (will rotate)
    when="midnight",            # rotate daily
    interval=1,
    backupCount=30,             # keep last 30 days
    encoding="utf-8"
)
file_handler.suffix = "%Y-%m-%d.log"  # final filenames look like 2025-10-27.log

formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[stream_handler, file_handler]
)
logger = logging.getLogger(__name__)

# --- Database (default to index.db in install root) ---
DB_FILE = os.getenv("DB_FILE", "index.db")
DB_FILE = str((here / DB_FILE).resolve())  # always resolve relative to install dir


def ensure_user_tables(conn):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS api_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        key TEXT UNIQUE NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)
    conn.commit()
    logger.debug("Ensured users and api_keys tables exist.")


def create_or_update_admin(username, password, create_api_key=True):
    if not username:
        raise ValueError("username is required")
    if not password:
        raise ValueError("password is required (empty not allowed)")

    conn = sqlite3.connect(DB_FILE)
    ensure_user_tables(conn)
    cur = conn.cursor()

    # hash password
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    cur.execute("SELECT id FROM users WHERE username=?", (username,))
    row = cur.fetchone()

    if row:
        user_id = row[0]
        cur.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, user_id))
        logger.info(f"Updated password for existing user '{username}' (id={user_id})")
    else:
        cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, pw_hash))
        user_id = cur.lastrowid
        logger.info(f"Created new user '{username}' (id={user_id})")

    conn.commit()

    api_key = None
    if create_api_key:
        api_key = secrets.token_hex(32)
        cur.execute("INSERT INTO api_keys (user_id, key) VALUES (?, ?)", (user_id, api_key))
        conn.commit()
        logger.info(f"Generated new API key for user '{username}'")

    conn.close()
    return {"user_id": user_id, "username": username, "api_key": api_key}


def main():
    env_user = os.getenv("ADMIN_USER")
    env_pw = os.getenv("ADMIN_PASSWORD")

    if env_user and env_pw:
        username = env_user
        password = env_pw
        logger.info("Using ADMIN_USER and ADMIN_PASSWORD from .env")
    else:
        logger.warning("ADMIN_USER and/or ADMIN_PASSWORD not found in .env. Prompting interactively.")
        username = input("Admin username: ").strip()
        while not username:
            username = input("Admin username (cannot be empty): ").strip()
        password = getpass("Admin password: ").strip()
        while not password:
            password = getpass("Admin password (cannot be empty): ").strip()

    result = create_or_update_admin(username, password, create_api_key=True)

    logger.info("=== Admin user created/updated ===")
    logger.info(f"username: {result['username']}")
    logger.info(f"user_id: {result['user_id']}")
    if result["api_key"]:
        logger.warning("Important: API key generated (store it now — this is shown only once)")
        print("\nAPI Key:", result["api_key"], "\n")  # still shown on screen
    else:
        logger.info("No API key generated.")


if __name__ == "__main__":
    main()
