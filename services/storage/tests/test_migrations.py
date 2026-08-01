from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def test_alembic_upgrade_head(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    os.environ["BAHLILY_STORAGE_DB"] = str(db_path)
    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config("alembic.ini")
        command.upgrade(cfg, "head")

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = {row[0] for row in rows}
        conn.close()
        assert "meetings" in tables
        assert "segments" in tables
        assert "summaries" in tables
    finally:
        del os.environ["BAHLILY_STORAGE_DB"]
