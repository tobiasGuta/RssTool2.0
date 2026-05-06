"""
db.py — Shared SQLite database layer for RssTool2.0
Replaces feeds_config.json and seen_entries.txt with a proper database.
WAL mode allows concurrent reads from both rss_alerts.py and slash_control_bot.py.
"""

import sqlite3
import os
import json
import logging
import time

DB_PATH = os.getenv("DB_PATH", os.path.join("data", "rsstool.db"))
log = logging.getLogger("db")


def get_connection() -> sqlite3.Connection:
    """Open and return a SQLite connection with WAL mode and Row factory."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    """Create all tables and migrate legacy feeds_config.json if it exists."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS feeds (
            url          TEXT PRIMARY KEY,
            webhook      TEXT NOT NULL,
            category     TEXT DEFAULT 'General',
            enabled      INTEGER DEFAULT 1,
            keywords     TEXT DEFAULT '',
            added_at     REAL DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS seen_entries (
            hash         TEXT PRIMARY KEY,
            feed_url     TEXT,
            seen_at      REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sent_articles (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_url     TEXT,
            title        TEXT,
            link         TEXT,
            category     TEXT,
            image        TEXT,
            sent_at      REAL DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS feed_health (
            url          TEXT PRIMARY KEY,
            last_checked REAL,
            last_success REAL,
            fail_count   INTEGER DEFAULT 0,
            last_error   TEXT
        );
    """)
    conn.commit()

    # ── Migrate legacy feeds_config.json ──────────────────────────────────
    config_file = "feeds_config.json"
    if os.path.exists(config_file):
        try:
            with open(config_file) as f:
                config = json.load(f)
            if config:
                for url, entry in config.items():
                    conn.execute(
                        "INSERT OR IGNORE INTO feeds (url, webhook, category) VALUES (?, ?, ?)",
                        (url, entry.get("webhook", ""), entry.get("category", "General")),
                    )
                conn.commit()
                log.info(f"Migrated {len(config)} feeds from feeds_config.json")
                os.rename(config_file, config_file + ".migrated")
        except Exception as e:
            log.error(f"Migration failed: {e}")

    conn.close()


# ── Feed operations ────────────────────────────────────────────────────────

def get_all_feeds(conn: sqlite3.Connection):
    return conn.execute("SELECT * FROM feeds ORDER BY added_at DESC").fetchall()


def get_enabled_feeds(conn: sqlite3.Connection):
    return conn.execute("SELECT * FROM feeds WHERE enabled=1").fetchall()


def add_feed(conn: sqlite3.Connection, url: str, webhook: str,
             category: str = "General", keywords: str = ""):
    conn.execute(
        "INSERT OR REPLACE INTO feeds (url, webhook, category, keywords) VALUES (?, ?, ?, ?)",
        (url, webhook, category, keywords),
    )
    conn.commit()


def remove_feed(conn: sqlite3.Connection, url: str):
    conn.execute("DELETE FROM feeds WHERE url=?", (url,))
    conn.commit()


def toggle_feed(conn: sqlite3.Connection, url: str, enabled: bool):
    conn.execute("UPDATE feeds SET enabled=? WHERE url=?", (1 if enabled else 0, url))
    conn.commit()


def update_feed_keywords(conn: sqlite3.Connection, url: str, keywords: str):
    conn.execute("UPDATE feeds SET keywords=? WHERE url=?", (keywords, url))
    conn.commit()


def get_feed(conn: sqlite3.Connection, url: str):
    return conn.execute("SELECT * FROM feeds WHERE url=?", (url,)).fetchone()


# ── Seen-entry deduplication ───────────────────────────────────────────────

def is_seen(conn: sqlite3.Connection, hash_val: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM seen_entries WHERE hash=?", (hash_val,)
    ).fetchone() is not None


def mark_seen(conn: sqlite3.Connection, hash_val: str, feed_url: str):
    conn.execute(
        "INSERT OR IGNORE INTO seen_entries (hash, feed_url, seen_at) VALUES (?, ?, ?)",
        (hash_val, feed_url, time.time()),
    )
    conn.commit()


def prune_seen(conn: sqlite3.Connection, max_age_days: int = 30):
    cutoff = time.time() - (max_age_days * 86400)
    deleted = conn.execute(
        "DELETE FROM seen_entries WHERE seen_at < ?", (cutoff,)
    ).rowcount
    conn.commit()
    if deleted:
        log.info(f"Pruned {deleted} old seen entries (>{max_age_days}d)")


# ── Article history ────────────────────────────────────────────────────────

def log_article(conn: sqlite3.Connection, feed_url: str, title: str,
                link: str, category: str, image: str = None):
    conn.execute(
        "INSERT INTO sent_articles (feed_url, title, link, category, image, sent_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (feed_url, title, link, category, image, time.time()),
    )
    conn.commit()


def get_recent_articles(conn: sqlite3.Connection, limit: int = 100):
    return conn.execute(
        "SELECT * FROM sent_articles ORDER BY sent_at DESC LIMIT ?", (limit,)
    ).fetchall()


# ── Feed health tracking ───────────────────────────────────────────────────

def update_health(conn: sqlite3.Connection, url: str, success: bool, error: str = None):
    now = time.time()
    if success:
        conn.execute(
            """INSERT OR REPLACE INTO feed_health (url, last_checked, last_success, fail_count, last_error)
               VALUES (?, ?, ?, 0, NULL)""",
            (url, now, now),
        )
    else:
        conn.execute(
            """INSERT INTO feed_health (url, last_checked, fail_count, last_error)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(url) DO UPDATE SET
                   last_checked = excluded.last_checked,
                   fail_count   = fail_count + 1,
                   last_error   = excluded.last_error""",
            (url, now, str(error)),
        )
    conn.commit()


def get_feed_health(conn: sqlite3.Connection):
    return conn.execute("SELECT * FROM feed_health ORDER BY fail_count DESC").fetchall()
