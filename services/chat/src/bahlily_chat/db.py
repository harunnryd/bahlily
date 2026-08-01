from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

_DIMENSION_KEY = "embedding_dimension"


def connect(db_path: str, dimension: int) -> sqlite3.Connection:
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    if db_path != ":memory:":
        # Each request opens its own connection (see app.get_connection), so
        # concurrent requests mean concurrent writers to the same file. WAL
        # lets readers proceed during a write, and busy_timeout makes a
        # contended writer wait instead of failing immediately with
        # "database is locked".
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")

    conn.execute("CREATE TABLE IF NOT EXISTS chat_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    # `INSERT OR IGNORE` (rather than SELECT-then-INSERT) keeps two concurrent
    # first-time connects from racing into a UNIQUE constraint violation,
    # which would otherwise leave a connection with an uncommitted write
    # transaction dangling and starve every other connection's busy_timeout.
    conn.execute(
        "INSERT OR IGNORE INTO chat_meta(key, value) VALUES (?, ?)",
        [_DIMENSION_KEY, str(dimension)],
    )
    row = conn.execute("SELECT value FROM chat_meta WHERE key = ?", [_DIMENSION_KEY]).fetchone()
    assert row is not None
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
    return conn
