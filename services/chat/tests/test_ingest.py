from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from langchain_core.embeddings import Embeddings

from bahlily_chat import db, index
from bahlily_chat.errors import ChatProviderUnavailableError, ChatStorageError
from bahlily_chat.ingest import ingest
from bahlily_chat.models import IngestRequest, TranscriptSegment


class FakeEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.1, 0.1, 0.1] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.1, 0.1, 0.1]


class ShortCountEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.1, 0.1, 0.1]]

    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.1, 0.1, 0.1]


class WrongDimensionEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 8 for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1] * 8


class FailingEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("provider down")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("provider down")


class PartialFailureEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.2, 0.2, 0.2, 0.2], [0.3] * 8]

    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.1, 0.1, 0.1]


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    return db.connect(str(tmp_path / "test.db"), dimension=4)


def _request(*segments: TranscriptSegment) -> IngestRequest:
    return IngestRequest(segments=list(segments))


def test_ingest_indexes_all_segments(conn: sqlite3.Connection) -> None:
    request = _request(
        TranscriptSegment(text="We decided to ship on Friday.", segment_id=1, speaker="Alice"),
        TranscriptSegment(text="I will handle deployment.", segment_id=2, speaker="Bob"),
    )
    response = ingest(conn, FakeEmbeddings(), "m1", request)
    assert response.meeting_id == "m1"
    assert response.segments_indexed == 2
    assert index.meeting_exists(conn, "m1")


def test_ingest_replaces_existing_rows(conn: sqlite3.Connection) -> None:
    ingest(conn, FakeEmbeddings(), "m1", _request(TranscriptSegment(text="old", segment_id=1)))
    ingest(conn, FakeEmbeddings(), "m1", _request(TranscriptSegment(text="new", segment_id=2)))
    matches = index.search(conn, [0.1, 0.1, 0.1, 0.1], k=5, meeting_id="m1")
    assert [m.segment_id for m in matches] == [2]


def test_ingest_embedding_failure_is_classified(conn: sqlite3.Connection) -> None:
    request = _request(TranscriptSegment(text="hi", segment_id=1))
    with pytest.raises(ChatProviderUnavailableError):
        ingest(conn, FailingEmbeddings(), "m1", request)


def test_ingest_vector_count_mismatch_is_classified(conn: sqlite3.Connection) -> None:
    request = _request(
        TranscriptSegment(text="a", segment_id=1),
        TranscriptSegment(text="b", segment_id=2),
    )
    with pytest.raises(ChatProviderUnavailableError):
        ingest(conn, ShortCountEmbeddings(), "m1", request)


def test_ingest_dimension_mismatch_is_storage_error(conn: sqlite3.Connection) -> None:
    request = _request(TranscriptSegment(text="hi", segment_id=1))
    with pytest.raises(ChatStorageError):
        ingest(conn, WrongDimensionEmbeddings(), "m1", request)


def test_ingest_failure_does_not_corrupt_or_lose_existing_rows(
    conn: sqlite3.Connection,
) -> None:
    ingest(conn, FakeEmbeddings(), "m1", _request(TranscriptSegment(text="original", segment_id=1)))

    failing_request = _request(
        TranscriptSegment(text="partial insert survivor", segment_id=2),
        TranscriptSegment(text="bad dim fails here", segment_id=3),
    )
    with pytest.raises(ChatStorageError):
        ingest(conn, PartialFailureEmbeddings(), "m1", failing_request)

    ingest(
        conn, FakeEmbeddings(), "m2", _request(TranscriptSegment(text="unrelated", segment_id=1))
    )

    m1_rows = conn.execute(
        "SELECT segment_id, text FROM segments WHERE meeting_id = 'm1'"
    ).fetchall()
    assert m1_rows == [(1, "original")]

    m2_rows = conn.execute(
        "SELECT segment_id, text FROM segments WHERE meeting_id = 'm2'"
    ).fetchall()
    assert m2_rows == [(1, "unrelated")]
