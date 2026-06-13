"""
db.py — SQLite persistence for Waypoint telemetry events.

Schema: one table, two partial unique indexes for server-side deduplication.
Never stores IP addresses, user agents, or any client-identifying information
beyond the anonymous install_id supplied by the client.
"""

import os
import sqlite3
from datetime import datetime, timezone

DEFAULT_PATH = os.path.expanduser("~/.waypoint/telemetry.db")
_db_path: str = DEFAULT_PATH


def configure(path: str) -> None:
    """Override the database file path. Must be called before init()."""
    global _db_path
    _db_path = path


def init() -> None:
    """Create schema if it does not already exist."""
    conn = _connect()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                install_id  TEXT    NOT NULL,
                event       TEXT    NOT NULL
                    CHECK(event IN ('install', 'heartbeat')),
                date        TEXT    NOT NULL,
                platform    TEXT    NOT NULL
                    CHECK(platform IN ('darwin', 'win32', 'linux')),
                schema_ver  INTEGER NOT NULL DEFAULT 1,
                received_at TEXT    NOT NULL
            );

            -- At most one install event per install_id.
            CREATE UNIQUE INDEX IF NOT EXISTS uq_install
                ON events(install_id) WHERE event = 'install';

            -- At most one heartbeat per install_id per calendar date.
            CREATE UNIQUE INDEX IF NOT EXISTS uq_heartbeat
                ON events(install_id, date) WHERE event = 'heartbeat';
        """)
        conn.commit()
    finally:
        conn.close()


def insert_event(
    install_id: str,
    event: str,
    date: str,
    platform: str,
) -> bool:
    """
    Insert one validated event row. Returns True if inserted, False if duplicate.

    received_at is assigned server-side in UTC; client-supplied date is stored
    as-is for DAU/WAU/MAU accounting.  No IP address or user agent is accepted
    or stored.
    """
    received_at = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO events (install_id, event, date, platform, received_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (install_id, event, date, platform, received_at),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def metrics() -> dict:
    """
    Return a snapshot of install and active-user counts.

      total_installs — distinct install_ids that ever sent an "install" event
      dau            — distinct install_ids with any event dated today
      wau            — distinct install_ids with any event in the last 7 days
      mau            — distinct install_ids with any event in the last 30 days
    """
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(DISTINCT install_id) FROM events WHERE event = 'install'"
        )
        total_installs = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(DISTINCT install_id) FROM events"
            " WHERE date = DATE('now')"
        )
        dau = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(DISTINCT install_id) FROM events"
            " WHERE date >= DATE('now', '-6 days')"
        )
        wau = cur.fetchone()[0]

        cur.execute(
            "SELECT COUNT(DISTINCT install_id) FROM events"
            " WHERE date >= DATE('now', '-29 days')"
        )
        mau = cur.fetchone()[0]

        return {
            "total_installs": total_installs,
            "dau":            dau,
            "wau":            wau,
            "mau":            mau,
        }
    finally:
        conn.close()


# ── Internal ──────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    dirpath = os.path.dirname(os.path.abspath(_db_path))
    os.makedirs(dirpath, exist_ok=True)
    return sqlite3.connect(_db_path)
