from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from bahlily_chat import db, index


def _conn(tmp_path: Path) -> sqlite3.Connection:
    return db.connect(str(tmp_path / "test.db"), dimension=4)


def test_connect_creates_segments_table(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE name = 'segments'").fetchall()
    assert len(rows) == 1


def test_connect_is_idempotent(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    db.connect(db_path, dimension=4).close()
    conn = db.connect(db_path, dimension=4)  # must not raise on second call
    rows = conn.execute("SELECT name FROM sqlite_master WHERE name = 'segments'").fetchall()
    assert len(rows) == 1


def test_upsert_and_search_returns_nearest_first(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    index.upsert_meeting(
        conn,
        "m1",
        [
            (1, "close match", "Alice", 0.0, 1.0, [0.1, 0.1, 0.1, 0.1]),
            (2, "far match", "Bob", 1.0, 2.0, [0.9, 0.9, 0.9, 0.9]),
        ],
    )
    results = index.search(conn, [0.11, 0.11, 0.11, 0.11], k=5)
    assert [r.segment_id for r in results] == [1, 2]
    assert results[0].text == "close match"
    assert results[0].speaker == "Alice"
    assert results[0].start_time == 0.0
    assert results[0].distance < results[1].distance


def test_search_scoped_to_meeting_id(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    index.upsert_meeting(conn, "m1", [(1, "in m1", None, None, None, [0.1, 0.1, 0.1, 0.1])])
    index.upsert_meeting(
        conn, "m2", [(1, "in m2, closer", None, None, None, [0.10, 0.10, 0.10, 0.10])]
    )

    results = index.search(conn, [0.1, 0.1, 0.1, 0.1], k=5, meeting_id="m1")
    assert len(results) == 1
    assert results[0].meeting_id == "m1"
    assert results[0].text == "in m1"


def test_upsert_meeting_replaces_existing_rows(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    index.upsert_meeting(conn, "m1", [(1, "old", None, None, None, [0.1, 0.1, 0.1, 0.1])])
    index.upsert_meeting(conn, "m1", [(2, "new", None, None, None, [0.2, 0.2, 0.2, 0.2])])

    results = index.search(conn, [0.2, 0.2, 0.2, 0.2], k=5, meeting_id="m1")
    assert [r.segment_id for r in results] == [2]
    assert results[0].text == "new"


def test_delete_meeting_removes_only_that_meeting(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    index.upsert_meeting(conn, "m1", [(1, "a", None, None, None, [0.1, 0.1, 0.1, 0.1])])
    index.upsert_meeting(conn, "m2", [(1, "b", None, None, None, [0.2, 0.2, 0.2, 0.2])])

    index.delete_meeting(conn, "m1")

    assert index.meeting_exists(conn, "m1") is False
    assert index.meeting_exists(conn, "m2") is True


def test_meeting_exists_false_for_never_ingested_meeting(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    assert index.meeting_exists(conn, "never-ingested") is False


def test_search_on_empty_index_returns_empty_list(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    assert index.search(conn, [0.1, 0.1, 0.1, 0.1], k=5) == []


def test_search_on_empty_meeting_scope_returns_empty_list(tmp_path: Path) -> None:
    conn = _conn(tmp_path)
    index.upsert_meeting(conn, "m1", [(1, "a", None, None, None, [0.1, 0.1, 0.1, 0.1])])
    assert index.search(conn, [0.1, 0.1, 0.1, 0.1], k=5, meeting_id="no-such-meeting") == []


def test_connect_creates_missing_parent_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "does" / "not" / "exist" / "chat.db"
    conn = db.connect(str(db_path), dimension=4)
    conn.close()
    assert db_path.exists()


def test_connect_allows_reopening_with_same_dimension(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    db.connect(db_path, dimension=4).close()
    conn = db.connect(db_path, dimension=4)
    conn.close()


def test_connect_rejects_mismatched_dimension_against_existing_db(tmp_path: Path) -> None:
    db_path = str(tmp_path / "test.db")
    db.connect(db_path, dimension=4).close()

    with pytest.raises(RuntimeError, match="dimension"):
        db.connect(db_path, dimension=8)


def test_connections_are_usable_across_threads(tmp_path: Path) -> None:
    import threading

    conn = _conn(tmp_path)
    errors: list[BaseException] = []

    def query_from_thread() -> None:
        try:
            conn.execute("SELECT 1").fetchone()
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=query_from_thread)
    thread.start()
    thread.join()

    assert errors == []
