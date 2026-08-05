from __future__ import annotations

import asyncio
import datetime
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bahlily_storage import db as db_module
from bahlily_storage.app import app, create_meeting, create_summary
from bahlily_storage.db import get_session
from bahlily_storage.errors import (
    StorageMeetingAlreadyExistsError,
    StorageSummaryAlreadyExistsError,
)
from bahlily_storage.models import Base, Meeting
from bahlily_storage.schemas import CreateMeetingRequest, CreateSummaryRequest


def _emb(*values: float) -> list[float]:
    return list(values) + [0.0] * (512 - len(values))


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("BAHLILY_STORAGE_DB", str(db_path))

    engine = db_module._make_engine(f"sqlite+aiosqlite:///{db_path}")
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _create_schema() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_schema())

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as c:
            yield c
    finally:
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


def test_create_and_get_template(client: TestClient) -> None:
    body = {"name": "Custom", "system_prompt": "Summarize this."}
    r = client.post("/templates", json=body)
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Custom"
    assert data["version"] == "1.0.0"
    assert data["few_shot_examples"] == []
    template_id = data["id"]

    r2 = client.get(f"/templates/{template_id}")
    assert r2.status_code == 200
    assert r2.json()["system_prompt"] == "Summarize this."


def test_create_template_rejects_unknown_field(client: TestClient) -> None:
    body = {"name": "Custom", "system_prompt": "P", "not_a_real_field": "x"}
    r = client.post("/templates", json=body)
    assert r.status_code == 422


def test_get_template_not_found(client: TestClient) -> None:
    r = client.get("/templates/nonexistent")
    assert r.status_code == 404
    assert r.json()["code"] == "STORAGE_TEMPLATE_NOT_FOUND"


def test_list_templates(client: TestClient) -> None:
    client.post("/templates", json={"name": "A", "system_prompt": "P1"})
    client.post("/templates", json={"name": "B", "system_prompt": "P2"})
    r = client.get("/templates")
    assert r.status_code == 200
    names = {t["name"] for t in r.json()}
    assert names == {"A", "B"}


def test_list_templates_rejects_out_of_range_limit(client: TestClient) -> None:
    assert client.get("/templates", params={"limit": 0}).status_code == 422
    assert client.get("/templates", params={"limit": 101}).status_code == 422
    assert client.get("/templates", params={"offset": -1}).status_code == 422


def test_patch_template(client: TestClient) -> None:
    created = client.post("/templates", json={"name": "A", "system_prompt": "P1"}).json()
    r = client.patch(f"/templates/{created['id']}", json={"name": "Renamed"})
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"
    assert r.json()["updated_at"] != created["updated_at"]


def test_patch_template_rejects_unknown_field(client: TestClient) -> None:
    created = client.post("/templates", json={"name": "A", "system_prompt": "P1"}).json()
    r = client.patch(f"/templates/{created['id']}", json={"nam": "x"})
    assert r.status_code == 422


def test_patch_template_clears_explicit_null_focus_instructions(client: TestClient) -> None:
    created = client.post(
        "/templates",
        json={"name": "A", "system_prompt": "P1", "focus_instructions": "Be concise."},
    ).json()
    assert created["focus_instructions"] == "Be concise."

    r = client.patch(f"/templates/{created['id']}", json={"focus_instructions": None})
    assert r.status_code == 200
    assert r.json()["focus_instructions"] is None


def test_patch_template_not_found(client: TestClient) -> None:
    r = client.patch("/templates/nonexistent", json={"name": "x"})
    assert r.status_code == 404
    assert r.json()["code"] == "STORAGE_TEMPLATE_NOT_FOUND"


def test_delete_template(client: TestClient) -> None:
    created = client.post("/templates", json={"name": "A", "system_prompt": "P1"}).json()
    r = client.delete(f"/templates/{created['id']}")
    assert r.status_code == 204
    assert client.get(f"/templates/{created['id']}").status_code == 404


def test_delete_template_not_found(client: TestClient) -> None:
    r = client.delete("/templates/nonexistent")
    assert r.status_code == 404
    assert r.json()["code"] == "STORAGE_TEMPLATE_NOT_FOUND"


def test_create_template_rejects_malformed_few_shot_example(client: TestClient) -> None:
    body = {
        "name": "Custom",
        "system_prompt": "P",
        "few_shot_examples": [{"foo": "bar"}],
    }
    r = client.post("/templates", json=body)
    assert r.status_code == 422


def test_create_template_rejects_empty_few_shot_example_field(client: TestClient) -> None:
    body = {
        "name": "Custom",
        "system_prompt": "P",
        "few_shot_examples": [{"input": "", "output": "fine"}],
    }
    r = client.post("/templates", json=body)
    assert r.status_code == 422


def test_create_template_accepts_well_formed_few_shot_example(client: TestClient) -> None:
    body = {
        "name": "Custom",
        "system_prompt": "P",
        "few_shot_examples": [{"input": "hi", "output": "hello"}],
    }
    r = client.post("/templates", json=body)
    assert r.status_code == 201
    assert r.json()["few_shot_examples"] == [{"input": "hi", "output": "hello"}]


def test_create_template_rejects_empty_system_prompt(client: TestClient) -> None:
    body = {"name": "Custom", "system_prompt": ""}
    r = client.post("/templates", json=body)
    assert r.status_code == 422


def test_patch_template_rejects_empty_system_prompt(client: TestClient) -> None:
    created = client.post("/templates", json={"name": "A", "system_prompt": "P1"}).json()
    r = client.patch(f"/templates/{created['id']}", json={"system_prompt": ""})
    assert r.status_code == 422


def test_patch_template_empty_body_does_not_change_updated_at(client: TestClient) -> None:
    created = client.post("/templates", json={"name": "A", "system_prompt": "P1"}).json()
    r = client.patch(f"/templates/{created['id']}", json={})
    assert r.status_code == 200
    assert r.json()["updated_at"] == created["updated_at"]
    assert r.json()["name"] == created["name"]


def test_create_and_get_speaker_profile(client: TestClient) -> None:
    emb = _emb(0.1, 0.2, 0.3)
    resp = client.post("/speaker-profiles", json={"name": "Alice", "voice_embedding": emb})
    assert resp.status_code == 201
    profile_id = resp.json()["id"]

    resp = client.get(f"/speaker-profiles/{profile_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Alice"
    assert resp.json()["voice_embedding"] == emb


def test_create_speaker_profile_rejects_unknown_field(client: TestClient) -> None:
    resp = client.post(
        "/speaker-profiles",
        json={"name": "Alice", "voice_embedding": [0.1], "nonexistent": True},
    )
    assert resp.status_code == 422


def test_create_speaker_profile_rejects_wrong_embedding_dim(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BAHLILY_STORAGE_EMBEDDING_DIM", "512")
    resp = client.post(
        "/speaker-profiles",
        json={"name": "Wrong Dim", "voice_embedding": [0.1, 0.2]},
    )
    assert resp.status_code == 422
    assert "expected 512" in resp.text


def test_get_speaker_profile_not_found(client: TestClient) -> None:
    resp = client.get("/speaker-profiles/missing")
    assert resp.status_code == 404
    assert resp.json()["code"] == "STORAGE_SPEAKER_PROFILE_NOT_FOUND"


def test_list_speaker_profiles(client: TestClient) -> None:
    client.post("/speaker-profiles", json={"name": "Alice", "voice_embedding": _emb(0.1)})
    client.post("/speaker-profiles", json={"name": "Bob", "voice_embedding": _emb(0.2)})

    resp = client.get("/speaker-profiles")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_patch_speaker_profile(client: TestClient) -> None:
    resp = client.post("/speaker-profiles", json={"name": "Alice", "voice_embedding": _emb(0.1)})
    profile_id = resp.json()["id"]

    resp = client.patch(f"/speaker-profiles/{profile_id}", json={"name": "Alicia"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Alicia"


def test_delete_speaker_profile(client: TestClient) -> None:
    resp = client.post("/speaker-profiles", json={"name": "Alice", "voice_embedding": _emb(0.1)})
    profile_id = resp.json()["id"]

    resp = client.delete(f"/speaker-profiles/{profile_id}")
    assert resp.status_code == 204
    assert client.get(f"/speaker-profiles/{profile_id}").status_code == 404


def test_batch_upsert_reupload_without_speaker_fields_preserves_them(
    client: TestClient,
) -> None:
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
        "speaker_cluster_label": "Speaker 1",
    }
    client.post("/meetings/m1/segments/batch", json={"segments": [seg]})

    reupload = {k: v for k, v in seg.items() if k != "speaker_cluster_label"}
    reupload["text"] = "hello again"
    resp = client.post("/meetings/m1/segments/batch", json={"segments": [reupload]})
    assert resp.status_code == 204

    segments = client.get("/meetings/m1/segments").json()
    assert segments[0]["text"] == "hello again"
    assert segments[0]["speaker_cluster_label"] == "Speaker 1"


def test_batch_upsert_setting_only_profile_id_preserves_existing_cluster_label(
    client: TestClient,
) -> None:
    client.post("/meetings", json={"id": "m1"})
    profile_resp = client.post(
        "/speaker-profiles", json={"name": "Alice", "voice_embedding": _emb(0.1)}
    )
    profile_id = profile_resp.json()["id"]

    seg = {
        "segment_id": 0,
        "text": "hello",
        "engine": "whisper",
        "model_name": "tiny",
        "audio_start_time": 0.0,
        "audio_end_time": 1.0,
        "is_partial": False,
        "trace_id": "t1",
        "speaker_cluster_label": "Speaker 1",
        "speaker_profile_id": None,
    }
    client.post("/meetings/m1/segments/batch", json={"segments": [seg]})

    profile_only = {k: v for k, v in seg.items() if k != "speaker_cluster_label"}
    profile_only["speaker_profile_id"] = profile_id
    resp = client.post("/meetings/m1/segments/batch", json={"segments": [profile_only]})
    assert resp.status_code == 204

    segments = client.get("/meetings/m1/segments").json()
    assert segments[0]["speaker_cluster_label"] == "Speaker 1"
    assert segments[0]["speaker_profile_id"] == profile_id


def test_delete_speaker_profile_referenced_by_a_segment_sets_it_null(client: TestClient) -> None:
    profile_resp = client.post(
        "/speaker-profiles", json={"name": "Alice", "voice_embedding": _emb(0.1)}
    )
    profile_id = profile_resp.json()["id"]

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
        "speaker_profile_id": profile_id,
    }
    client.post("/meetings/m1/segments/batch", json={"segments": [seg]})

    resp = client.delete(f"/speaker-profiles/{profile_id}")
    assert resp.status_code == 204

    segments = client.get("/meetings/m1/segments").json()
    assert segments[0]["speaker_profile_id"] is None


def test_match_speaker_profile_finds_the_closest_match(client: TestClient) -> None:
    client.post("/speaker-profiles", json={"name": "Alice", "voice_embedding": _emb(1.0, 0.0)})
    client.post("/speaker-profiles", json={"name": "Bob", "voice_embedding": _emb(0.0, 1.0)})

    resp = client.post("/speaker-profiles/match", json={"voice_embedding": _emb(0.99, 0.01)})
    assert resp.status_code == 200
    assert resp.json()["profile"]["name"] == "Alice"


def test_match_speaker_profile_returns_null_when_no_profiles_exist(client: TestClient) -> None:
    resp = client.post("/speaker-profiles/match", json={"voice_embedding": _emb(1.0, 0.0)})
    assert resp.status_code == 200
    assert resp.json()["profile"] is None


def test_patch_meeting_accepts_recording_path_and_diarization_status(client: TestClient) -> None:
    client.post("/meetings", json={"id": "m1"})

    resp = client.patch(
        "/meetings/m1",
        json={"recording_path": "/data/recordings/m1.flac", "diarization_status": "pending"},
    )
    assert resp.status_code == 200
    assert resp.json()["recording_path"] == "/data/recordings/m1.flac"
    assert resp.json()["diarization_status"] == "pending"


def test_new_meeting_defaults_diarization_status_to_not_started(client: TestClient) -> None:
    client.post("/meetings", json={"id": "m1"})
    resp = client.get("/meetings/m1")
    assert resp.json()["diarization_status"] == "not_started"
    assert resp.json()["recording_path"] is None


def test_batch_segments_accepts_speaker_fields(client: TestClient) -> None:
    client.post("/meetings", json={"id": "m1"})
    resp = client.post(
        "/meetings/m1/segments/batch",
        json={
            "segments": [
                {
                    "segment_id": 0,
                    "text": "hello",
                    "engine": "whisper",
                    "model_name": "tiny",
                    "audio_start_time": 0.0,
                    "audio_end_time": 1.0,
                    "is_partial": False,
                    "trace_id": "t1",
                    "speaker_cluster_label": "Speaker 1",
                }
            ]
        },
    )
    assert resp.status_code == 204

    resp = client.get("/meetings/m1/segments")
    assert resp.json()[0]["speaker_cluster_label"] == "Speaker 1"
    assert resp.json()[0]["speaker_profile_id"] is None
