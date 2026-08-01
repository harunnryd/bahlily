from __future__ import annotations

import dataclasses
import sqlite3

import sqlite_vec


@dataclasses.dataclass(frozen=True)
class SegmentMatch:
    meeting_id: str
    segment_id: int
    text: str
    speaker: str | None
    start_time: float | None
    end_time: float | None
    distance: float


IngestRow = tuple[int, str, str | None, float | None, float | None, list[float]]


def upsert_meeting(conn: sqlite3.Connection, meeting_id: str, rows: list[IngestRow]) -> None:
    conn.execute("DELETE FROM segments WHERE meeting_id = ?", [meeting_id])
    values = [
        (
            meeting_id,
            segment_id,
            sqlite_vec.serialize_float32(embedding),
            text,
            speaker,
            start_time,
            end_time,
        )
        for segment_id, text, speaker, start_time, end_time, embedding in rows
    ]
    conn.executemany(
        """
        INSERT INTO segments(
          meeting_id, segment_id, embedding, text, speaker, start_time, end_time
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    conn.commit()


def delete_meeting(conn: sqlite3.Connection, meeting_id: str) -> None:
    conn.execute("DELETE FROM segments WHERE meeting_id = ?", [meeting_id])
    conn.commit()


def meeting_exists(conn: sqlite3.Connection, meeting_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM segments WHERE meeting_id = ? LIMIT 1", [meeting_id]
    ).fetchone()
    return row is not None


def search(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    k: int,
    meeting_id: str | None = None,
) -> list[SegmentMatch]:
    query_vec = sqlite_vec.serialize_float32(query_embedding)
    query = """
        SELECT meeting_id, segment_id, text, speaker, start_time, end_time, distance
        FROM segments
        WHERE embedding MATCH ? AND k = ?
    """
    params: list[object] = [query_vec, k]
    if meeting_id is not None:
        query += " AND meeting_id = ?"
        params.append(meeting_id)
    query += " ORDER BY distance"
    rows = conn.execute(query, params).fetchall()
    return [
        SegmentMatch(
            meeting_id=r[0],
            segment_id=r[1],
            text=r[2],
            speaker=r[3],
            start_time=r[4],
            end_time=r[5],
            distance=r[6],
        )
        for r in rows
    ]
