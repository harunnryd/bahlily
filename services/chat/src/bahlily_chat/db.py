from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import sqlite_vec

_DIMENSION_KEY = "embedding_dimension"
_SCHEMA_RETRIES = 10
_SCHEMA_RETRY_DELAY_SECONDS = 0.1


def connect(db_path: str, dimension: int) -> sqlite3.Connection:
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    _initialize_with_retry(conn, db_path, dimension)
    return conn


def _initialize_with_retry(conn: sqlite3.Connection, db_path: str, dimension: int) -> None:
    for attempt in range(_SCHEMA_RETRIES):
        try:
            _configure_and_setup_schema(conn, db_path, dimension)
            return
        except sqlite3.OperationalError as exc:
            if attempt == _SCHEMA_RETRIES - 1 or "locked" not in str(exc).lower():
                conn.close()
                raise
            time.sleep(_SCHEMA_RETRY_DELAY_SECONDS)


def _configure_and_setup_schema(conn: sqlite3.Connection, db_path: str, dimension: int) -> None:
    if db_path != ":memory:":
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")

    conn.execute("CREATE TABLE IF NOT EXISTS chat_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        "INSERT OR IGNORE INTO chat_meta(key, value) VALUES (?, ?)",
        [_DIMENSION_KEY, str(dimension)],
    )
    row = conn.execute("SELECT value FROM chat_meta WHERE key = ?", [_DIMENSION_KEY]).fetchone()
    if row is None:
        conn.close()
        raise RuntimeError(
            f"chat_meta row for {_DIMENSION_KEY!r} is missing after INSERT OR IGNORE"
        )
    existing_dimension = int(row[0])
    if existing_dimension != dimension:
        conn.close()
        raise RuntimeError(
            f"database at {db_path!r} was created with embedding dimension "
            f"{existing_dimension}, but BAHLILY_CHAT_EMBEDDING_DIMENSION is set to "
            f"{dimension}. Re-ingest all meetings into a fresh database, or fix the "
            "configured dimension to match the existing database."
        )

    conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS segments USING vec0(
          embedding float[{dimension}],
          meeting_id TEXT partition key,
          segment_id INTEGER,
          +text TEXT,
          +speaker TEXT,
          +start_time FLOAT,
          +end_time FLOAT
        )
        """
    )
    conn.commit()
