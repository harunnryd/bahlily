from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import Embeddings

from bahlily_chat.app import app, get_connection, get_embedder
from bahlily_chat.db import connect


class FakeEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.1, 0.1, 0.1] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.1, 0.1, 0.1]


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    db_path = tmp_path / "test.db"

    def override_connection() -> Iterator[sqlite3.Connection]:
        conn = connect(str(db_path), dimension=4)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_connection] = override_connection
    app.dependency_overrides[get_embedder] = lambda: FakeEmbeddings()
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def _ingest_body() -> dict[str, object]:
    return {
        "segments": [
            {"text": "We decided to ship on Friday.", "segment_id": 1, "speaker": "Alice"},
            {"text": "Unrelated chatter.", "segment_id": 2, "speaker": "Bob"},
        ]
    }


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ingest_meeting(client: TestClient) -> None:
    response = client.post("/meetings/m1/ingest", json=_ingest_body())
    assert response.status_code == 201
    assert response.json() == {"meeting_id": "m1", "segments_indexed": 2}


def test_ingest_rejects_empty_segments(client: TestClient) -> None:
    response = client.post("/meetings/m1/ingest", json={"segments": []})
    assert response.status_code == 422


def test_delete_meeting(client: TestClient) -> None:
    client.post("/meetings/m1/ingest", json=_ingest_body())
    response = client.delete("/meetings/m1")
    assert response.status_code == 204


def test_delete_never_ingested_meeting_is_not_an_error(client: TestClient) -> None:
    response = client.delete("/meetings/never-ingested")
    assert response.status_code == 204


def test_chat_scoped_to_meeting(client: TestClient) -> None:
    client.post("/meetings/m1/ingest", json=_ingest_body())

    with patch("bahlily_chat.chat.init_chat_model") as mock_init:
        fake_response = MagicMock()
        fake_response.content = "You decided to ship on Friday."
        mock_init.return_value.invoke.return_value = fake_response

        response = client.post(
            "/chat",
            json={
                "question": "When do we ship?",
                "meeting_id": "m1",
                "provider": "openai",
                "model": "gpt-4o-mini",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "You decided to ship on Friday."
    assert len(body["citations"]) == 2


def test_chat_unscoped_meeting_not_ingested_returns_404(client: TestClient) -> None:
    response = client.post(
        "/chat",
        json={
            "question": "anything",
            "meeting_id": "never-ingested",
            "provider": "openai",
            "model": "gpt-4o-mini",
        },
    )
    assert response.status_code == 404


def test_chat_global_query_on_empty_index_still_answers(client: TestClient) -> None:
    with patch("bahlily_chat.chat.init_chat_model") as mock_init:
        fake_response = MagicMock()
        fake_response.content = "I don't have any meetings yet."
        mock_init.return_value.invoke.return_value = fake_response

        response = client.post(
            "/chat",
            json={"question": "anything", "provider": "openai", "model": "gpt-4o-mini"},
        )

    assert response.status_code == 200
    assert response.json()["answer"] == "I don't have any meetings yet."
