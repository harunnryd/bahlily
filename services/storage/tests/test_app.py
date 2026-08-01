from __future__ import annotations

import asyncio
import datetime
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bahlily_storage import db as db_module
from bahlily_storage.app import app, create_meeting, create_summary
from bahlily_storage.db import get_session
from bahlily_storage.errors import (
    StorageMeetingAlreadyExistsError,
    StorageSummaryAlreadyExistsError,
)
from bahlily_storage.models import Base, Meeting
from bahlily_storage.schemas import CreateMeetingRequest, CreateSummaryRequest


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("BAHLILY_STORAGE_DB", str(db_path))

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _create_schema() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_schema())

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

    asyncio.run(engine.dispose())


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


def test_create_meeting_rejects_unknown_field(client: TestClient) -> None:
    r = client.post("/meetings", json={"id": "m1", "not_a_real_field": "x"})
    assert r.status_code == 422


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


def test_patch_meeting_rejects_unknown_field(client: TestClient) -> None:
    client.post("/meetings", json={"id": "m1"})
    r = client.patch("/meetings/m1", json={"statuss": "stopped"})
    assert r.status_code == 422


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

    meeting = client.get("/meetings/m1").json()
    assert meeting["segments_count"] == 1


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


def test_list_meetings_rejects_out_of_range_limit(client: TestClient) -> None:
    assert client.get("/meetings", params={"limit": 0}).status_code == 422
    assert client.get("/meetings", params={"limit": 101}).status_code == 422
    assert client.get("/meetings", params={"offset": -1}).status_code == 422


def test_batch_upsert_rejects_invalid_segment(client: TestClient) -> None:
    client.post("/meetings", json={"id": "m1"})
    bad_segment = {
        "segment_id": -1,
        "text": "hello",
        "engine": "whisper",
        "model_name": "tiny",
        "audio_start_time": 1.0,
        "audio_end_time": 0.0,
        "is_partial": False,
        "trace_id": "t1",
    }
    r = client.post("/meetings/m1/segments/batch", json={"segments": [bad_segment]})
    assert r.status_code == 422


async def test_create_meeting_race_maps_to_conflict(tmp_path: Path) -> None:
    """Two genuinely concurrent requests for the same id: exactly one must
    succeed and the other must recover via the commit-time `IntegrityError`
    handler (not surface a raw 500), since both can pass the up-front
    existence check before either commits.

    Calls `create_meeting` directly (bypassing the ASGI/TestClient layer,
    which runs requests strictly one at a time) with two sessions sharing one
    real sqlite file, so the two attempts' `MeetingRepo.get` checks and
    inserts genuinely interleave via aiosqlite's own thread-pool scheduling —
    no repository method is mocked.
    """
    engine = db_module._make_engine(f"sqlite+aiosqlite:///{tmp_path / 'race.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def attempt() -> str:
            async with factory() as session:
                try:
                    await create_meeting(CreateMeetingRequest(id="m-race"), session)
                except StorageMeetingAlreadyExistsError:
                    return "conflict"
                return "created"

        outcomes = await asyncio.gather(attempt(), attempt())
    finally:
        await engine.dispose()

    assert outcomes.count("created") == 1
    assert outcomes.count("conflict") == 1


async def test_create_summary_race_maps_to_conflict(tmp_path: Path) -> None:
    """Same race as above, one level down: two concurrent summary creations
    for the same meeting must yield exactly one success and one conflict."""
    engine = db_module._make_engine(f"sqlite+aiosqlite:///{tmp_path / 'race.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as session:
            session.add(
                Meeting(
                    id="m1",
                    status="recording",
                    started_at=datetime.datetime.now(datetime.UTC),
                    segments_count=0,
                )
            )
            await session.commit()

        body = CreateSummaryRequest(
            title="T", overview="O", key_points=[], action_items=[], provider="p", model="m"
        )

        async def attempt() -> str:
            async with factory() as session:
                try:
                    await create_summary("m1", body, session)
                except StorageSummaryAlreadyExistsError:
                    return "conflict"
                return "created"

        outcomes = await asyncio.gather(attempt(), attempt())
    finally:
        await engine.dispose()

    assert outcomes.count("created") == 1
    assert outcomes.count("conflict") == 1
