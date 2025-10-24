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
from dotenv import load_dotenv
from getpass import getpass
from pathlib import Path

# --- Paths ---
here = Path(__file__).resolve().parent
dotenv_path = here / ".env"
load_dotenv(dotenv_path)

# --- Database (default to index.db in install root) ---
DB_FILE = os.getenv("DB_FILE", "index.db")
DB_FILE = str((here / DB_FILE).resolve())  # always resolve relative to install dir


def ensure_user_tables(conn):
    cur = conn.cursor()
    # users table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    # api_keys table
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

    # insert or update user
    cur.execute("SELECT id FROM users WHERE username=?", (username,))
    row = cur.fetchone()

    if row:
        user_id = row[0]
        cur.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, user_id))
    else:
        cur.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, pw_hash))
        user_id = cur.lastrowid

    conn.commit()

    api_key = None
    if create_api_key:
        api_key = secrets.token_hex(32)
        cur.execute("INSERT INTO api_keys (user_id, key) VALUES (?, ?)", (user_id, api_key))
        conn.commit()

    conn.close()
    return {"user_id": user_id, "username": username, "api_key": api_key}


def main():
    env_user = os.getenv("ADMIN_USER")
    env_pw = os.getenv("ADMIN_PASSWORD")

    if env_user and env_pw:
        username = env_user
        password = env_pw
        print("Using ADMIN_USER and ADMIN_PASSWORD from .env")
    else:
        print("ADMIN_USER and/or ADMIN_PASSWORD not found in .env. Prompting interactively.")
        username = input("Admin username: ").strip()
        while not username:
            username = input("Admin username (cannot be empty): ").strip()
        password = getpass("Admin password: ").strip()
        while not password:
            password = getpass("Admin password (cannot be empty): ").strip()

    result = create_or_update_admin(username, password, create_api_key=True)

    print("\n=== Admin user created/updated ===")
    print("username:", result["username"])
    print("user_id:", result["user_id"])
    if result["api_key"]:
        print("\nImportant: API key (store it now — this is shown only once):\n")
        print(result["api_key"])
    else:
        print("No API key generated.")


if __name__ == "__main__":
    main()
