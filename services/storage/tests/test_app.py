from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bahlily_storage.app import app
from bahlily_storage.db import get_session
from bahlily_storage.models import Base


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    db_path = tmp_path / "test.db"
    os.environ["BAHLILY_STORAGE_DB"] = str(db_path)

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "transcription_subscriber" in response.json()


def test_create_and_get_meeting(client: TestClient) -> None:
    r = client.post("/meetings", json={"id": "m1", "title": "Test"})
    assert r.status_code == 201
    assert r.json()["id"] == "m1"
    assert r.json()["status"] == "recording"

    r2 = client.get("/meetings/m1")
    assert r2.status_code == 200
    assert r2.json()["title"] == "Test"


def test_create_meeting_conflict(client: TestClient) -> None:
    client.post("/meetings", json={"id": "m1"})
    r = client.post("/meetings", json={"id": "m1"})
    assert r.status_code == 409
    assert r.json()["code"] == "STORAGE_MEETING_ALREADY_EXISTS"


def test_get_meeting_not_found(client: TestClient) -> None:
    r = client.get("/meetings/nonexistent")
    assert r.status_code == 404
    assert r.json()["code"] == "STORAGE_MEETING_NOT_FOUND"


def test_list_meetings(client: TestClient) -> None:
    client.post("/meetings", json={"id": "m1"})
    client.post("/meetings", json={"id": "m2"})
    r = client.get("/meetings")
    assert r.status_code == 200
    ids = {m["id"] for m in r.json()}
    assert ids == {"m1", "m2"}


def test_patch_meeting(client: TestClient) -> None:
    client.post("/meetings", json={"id": "m1"})
    r = client.patch("/meetings/m1", json={"status": "stopped", "title": "Updated"})
    assert r.status_code == 200
    assert r.json()["status"] == "stopped"
    assert r.json()["title"] == "Updated"


def test_patch_meeting_not_found(client: TestClient) -> None:
    r = client.patch("/meetings/nonexistent", json={"status": "stopped"})
    assert r.status_code == 404
    assert r.json()["code"] == "STORAGE_MEETING_NOT_FOUND"


def test_delete_meeting(client: TestClient) -> None:
    client.post("/meetings", json={"id": "m1"})
    r = client.delete("/meetings/m1")
    assert r.status_code == 204
    assert client.get("/meetings/m1").status_code == 404


def test_delete_meeting_not_found(client: TestClient) -> None:
    r = client.delete("/meetings/nonexistent")
    assert r.status_code == 404
    assert r.json()["code"] == "STORAGE_MEETING_NOT_FOUND"


def test_list_segments_meeting_not_found(client: TestClient) -> None:
    r = client.get("/meetings/nonexistent/segments")
    assert r.status_code == 404
    assert r.json()["code"] == "STORAGE_MEETING_NOT_FOUND"


def test_batch_upsert_segments(client: TestClient) -> None:
    client.post("/meetings", json={"id": "m1"})
    seg = {
        "segment_id": 0,
        "text": "hello",
        "engine": "whisper",
        "model_name": "tiny",
        "audio_start_time": 0.0,
        "audio_end_time": 1.0,
        "is_partial": False,
        "trace_id": "t1",
    }
    r = client.post("/meetings/m1/segments/batch", json={"segments": [seg]})
    assert r.status_code == 204
    segments = client.get("/meetings/m1/segments").json()
    assert len(segments) == 1
    assert segments[0]["text"] == "hello"

    meeting = client.get("/meetings/m1").json()
    assert meeting["segments_count"] == 1


def test_batch_upsert_idempotent(client: TestClient) -> None:
    client.post("/meetings", json={"id": "m1"})
    seg = {
        "segment_id": 0,
        "text": "hello",
        "engine": "whisper",
        "model_name": "tiny",
        "audio_start_time": 0.0,
        "audio_end_time": 1.0,
        "is_partial": False,
        "trace_id": "t1",
    }
    client.post("/meetings/m1/segments/batch", json={"segments": [seg]})
    client.post("/meetings/m1/segments/batch", json={"segments": [seg]})
    segments = client.get("/meetings/m1/segments").json()
    assert len(segments) == 1


def test_batch_upsert_meeting_not_found(client: TestClient) -> None:
    r = client.post("/meetings/nonexistent/segments/batch", json={"segments": []})
    assert r.status_code == 404
    assert r.json()["code"] == "STORAGE_MEETING_NOT_FOUND"


def test_create_and_get_summary(client: TestClient) -> None:
    client.post("/meetings", json={"id": "m1"})
    summary_body = {
        "title": "My Meeting",
        "overview": "We discussed X.",
        "key_points": ["point 1"],
        "action_items": [],
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
    }
    r = client.post("/meetings/m1/summary", json=summary_body)
    assert r.status_code == 201
    assert r.json()["title"] == "My Meeting"
    r2 = client.get("/meetings/m1/summary")
    assert r2.status_code == 200
    assert r2.json()["key_points"] == ["point 1"]

    meeting = client.get("/meetings/m1").json()
    assert meeting["has_summary"] is True


def test_create_summary_conflict(client: TestClient) -> None:
    client.post("/meetings", json={"id": "m1"})
    body = {
        "title": "T",
        "overview": "O",
        "key_points": [],
        "action_items": [],
        "provider": "p",
        "model": "m",
    }
    client.post("/meetings/m1/summary", json=body)
    r = client.post("/meetings/m1/summary", json=body)
    assert r.status_code == 409
    assert r.json()["code"] == "STORAGE_SUMMARY_ALREADY_EXISTS"


def test_create_summary_meeting_not_found(client: TestClient) -> None:
    body = {
        "title": "T",
        "overview": "O",
        "key_points": [],
        "action_items": [],
        "provider": "p",
        "model": "m",
    }
    r = client.post("/meetings/nonexistent/summary", json=body)
    assert r.status_code == 404
    assert r.json()["code"] == "STORAGE_MEETING_NOT_FOUND"


def test_get_summary_not_found(client: TestClient) -> None:
    client.post("/meetings", json={"id": "m1"})
    r = client.get("/meetings/m1/summary")
    assert r.status_code == 404
    assert r.json()["code"] == "STORAGE_SUMMARY_NOT_FOUND"
    assert "message" in r.json()
    assert "detail" not in r.json()
