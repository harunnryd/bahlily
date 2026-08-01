from __future__ import annotations

import sqlite3

import sqlite_vec


def connect(db_path: str, dimension: int) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
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
