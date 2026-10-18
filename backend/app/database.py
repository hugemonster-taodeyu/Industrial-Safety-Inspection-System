import sqlite3
import threading
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DB_PATH = DATA_DIR / "safety.db"
PHOTO_DIR = DATA_DIR / "photos"
SNAPSHOT_DIR = DATA_DIR / "snapshots"

_lock = threading.Lock()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock:
        conn = connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS detections (
                    code INTEGER PRIMARY KEY,
                    category TEXT NOT NULL,
                    category_name TEXT NOT NULL,
                    title TEXT NOT NULL,
                    method TEXT NOT NULL,
                    problem TEXT NOT NULL,
                    stages TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS people (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    list_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    employee_no TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT '',
                    qualification_expiry TEXT NOT NULL DEFAULT '',
                    badge_no TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    photo_path TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                );

                CREATE TABLE IF NOT EXISTS alarms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    code INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    person TEXT NOT NULL DEFAULT '',
                    stage TEXT NOT NULL DEFAULT '',
                    simulated INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS stage_cameras (
                    stage TEXT PRIMARY KEY,
                    device_index INTEGER NOT NULL,
                    device_name TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS zones (
                    stage TEXT PRIMARY KEY,
                    points TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS environments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS environment_detections (
                    environment_id INTEGER NOT NULL,
                    code INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (environment_id, code)
                );

                CREATE TABLE IF NOT EXISTS tools (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tool_no TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    calibration_expiry TEXT NOT NULL DEFAULT '',
                    qr_text TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                );
                """
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('stage', '交流耐压试验')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('sound_enabled', '0')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('leave_seconds', '30')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('dwell_minutes', '10')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('test_running', '0')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('ack_backfill', '0')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('alarm_window_seconds', '3')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('alarm_count', '3')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('alarm_gap_seconds', '20')"
            )
            columns = [row[1] for row in conn.execute("PRAGMA table_info(stage_cameras)")]
            if "source_type" not in columns:
                conn.execute(
                    "ALTER TABLE stage_cameras ADD COLUMN source_type TEXT NOT NULL DEFAULT 'local'"
                )
            if "stream_url" not in columns:
                conn.execute(
                    "ALTER TABLE stage_cameras ADD COLUMN stream_url TEXT NOT NULL DEFAULT ''"
                )
            people_columns = [row[1] for row in conn.execute("PRAGMA table_info(people)")]
            if "face_embedding" not in people_columns:
                conn.execute("ALTER TABLE people ADD COLUMN face_embedding BLOB")
            alarm_columns = [row[1] for row in conn.execute("PRAGMA table_info(alarms)")]
            if "acknowledged" not in alarm_columns:
                conn.execute("ALTER TABLE alarms ADD COLUMN acknowledged INTEGER NOT NULL DEFAULT 0")
            if "snapshot_path" not in alarm_columns:
                conn.execute("ALTER TABLE alarms ADD COLUMN snapshot_path TEXT NOT NULL DEFAULT ''")
            backfill = conn.execute("SELECT value FROM settings WHERE key = 'ack_backfill'").fetchone()
            if backfill and backfill[0] != "1":
                conn.execute("UPDATE alarms SET acknowledged = 1")
                conn.execute("UPDATE settings SET value = '1' WHERE key = 'ack_backfill'")
            conn.commit()
        finally:
            conn.close()


def query_all(sql: str, params: tuple = ()) -> list[dict]:
    with _lock:
        conn = connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query_all(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> int:
    with _lock:
        conn = connect()
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.lastrowid or 0
        finally:
            conn.close()
