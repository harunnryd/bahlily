from __future__ import annotations

import datetime
import json
import uuid
from typing import Annotated

import structlog
from bahlily_logging.errors import BahlilyError
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from bahlily_storage.db import get_session
from bahlily_storage.errors import (
    StorageEmbeddingDimNotConfiguredError,
    StorageMeetingAlreadyExistsError,
    StorageMeetingNotFoundError,
    StorageSpeakerProfileNameConflictError,
    StorageSpeakerProfileNotFoundError,
    StorageSummaryAlreadyExistsError,
    StorageSummaryNotFoundError,
    StorageTemplateNotFoundError,
)
from bahlily_storage.grpc_subscriber import subscriber_status
from bahlily_storage.models import Meeting, SpeakerProfile, Summary, SummaryTemplate
from bahlily_storage.repos import (
    MeetingRepo,
    SegmentRepo,
    SpeakerProfileRepo,
    SummaryRepo,
    TemplateRepo,
)
from bahlily_storage.schemas import (
    BatchSegmentItem,
    BatchSegmentsRequest,
    CreateMeetingRequest,
    CreateSpeakerProfileRequest,
    CreateSummaryRequest,
    CreateTemplateRequest,
    LabelSpeakerRequest,
    MatchBulkEntry,
    MatchBulkRequest,
    MatchBulkResponse,
    MatchSpeakerProfileRequest,
    MatchSpeakerProfileResponse,
    MeetingResponse,
    MergeSpeakersRequest,
    PatchMeetingRequest,
    PatchSpeakerProfileRequest,
    PatchTemplateRequest,
    SegmentResponse,
    SpeakerProfileResponse,
    SummaryResponse,
    TemplateResponse,
)
from bahlily_storage.speaker_matching import best_match

_log = structlog.get_logger()

app = FastAPI(title="bahlily-storage")

_ERROR_STATUS: dict[type[Exception], int] = {
    StorageMeetingNotFoundError: 404,
    StorageMeetingAlreadyExistsError: 409,
    StorageSummaryAlreadyExistsError: 409,
    StorageSummaryNotFoundError: 404,
    StorageTemplateNotFoundError: 404,
    StorageSpeakerProfileNotFoundError: 404,
    StorageSpeakerProfileNameConflictError: 409,
    StorageEmbeddingDimNotConfiguredError: 500,
}

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@app.exception_handler(StorageMeetingNotFoundError)
@app.exception_handler(StorageMeetingAlreadyExistsError)
@app.exception_handler(StorageSummaryAlreadyExistsError)
@app.exception_handler(StorageSummaryNotFoundError)
@app.exception_handler(StorageTemplateNotFoundError)
@app.exception_handler(StorageSpeakerProfileNotFoundError)
@app.exception_handler(StorageSpeakerProfileNameConflictError)
@app.exception_handler(StorageEmbeddingDimNotConfiguredError)
async def _error_handler(request: Request, exc: BahlilyError) -> JSONResponse:
    status = _ERROR_STATUS[type(exc)]
    return JSONResponse(
        status_code=status,
        content={"code": exc.code, "message": str(exc)},
    )


def _summary_to_response(s: Summary) -> SummaryResponse:
    return SummaryResponse(
        id=s.id,
        meeting_id=s.meeting_id,
        title=s.title,
        overview=s.overview,
        key_points=json.loads(s.key_points),
        action_items=json.loads(s.action_items),
        quotes=json.loads(s.quotes),
        provider=s.provider,
        model=s.model,
        created_at=s.created_at,
    )


def _meeting_to_response(m: Meeting) -> MeetingResponse:
    return MeetingResponse(
        id=m.id,
        title=m.title,
        status=m.status,
        language=m.language,
        engine=m.engine,
        model_name=m.model_name,
        started_at=m.started_at,
        ended_at=m.ended_at,
        segments_count=m.segments_count,
        recording_path=m.recording_path,
        diarization_status=m.diarization_status,
        has_summary=m.summary is not None,
    )


def _template_to_response(t: SummaryTemplate) -> TemplateResponse:
    return TemplateResponse(
        id=t.id,
        name=t.name,
        version=t.version,
        system_prompt=t.system_prompt,
        focus_instructions=t.focus_instructions,
        few_shot_examples=json.loads(t.few_shot_examples),
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


def _speaker_profile_to_response(p: SpeakerProfile) -> SpeakerProfileResponse:
    return SpeakerProfileResponse(
        id=p.id,
        name=p.name,
        voice_embedding=json.loads(p.voice_embedding),
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "transcription_subscriber": subscriber_status()}


@app.post("/meetings", status_code=201)
async def create_meeting(req: CreateMeetingRequest, session: SessionDep) -> MeetingResponse:
    repo = MeetingRepo(session)
    if await repo.get(req.id) is not None:
        raise StorageMeetingAlreadyExistsError(req.id)
    m = Meeting(
        id=req.id,
        title=req.title,
        language=req.language,
        status="recording",
        started_at=req.started_at or datetime.datetime.now(datetime.UTC),
        segments_count=0,
    )
    try:
        await repo.create(m)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise StorageMeetingAlreadyExistsError(req.id) from None
    await session.refresh(m)
    return _meeting_to_response(m)


@app.get("/meetings")
async def list_meetings(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MeetingResponse]:
    repo = MeetingRepo(session)
    meetings = await repo.list_all(limit=limit, offset=offset)
    return [_meeting_to_response(m) for m in meetings]


@app.get("/meetings/{meeting_id}")
async def get_meeting(meeting_id: str, session: SessionDep) -> MeetingResponse:
    repo = MeetingRepo(session)
    m = await repo.get(meeting_id)
    if m is None:
        raise StorageMeetingNotFoundError(meeting_id)
    return _meeting_to_response(m)


@app.patch("/meetings/{meeting_id}")
async def patch_meeting(
    meeting_id: str, req: PatchMeetingRequest, session: SessionDep
) -> MeetingResponse:
    repo = MeetingRepo(session)
    fields = req.model_dump(exclude_none=True)
    m = await repo.update(meeting_id, **fields)
    if m is None:
        raise StorageMeetingNotFoundError(meeting_id)
    await session.commit()
    await session.refresh(m)
    return _meeting_to_response(m)


@app.delete("/meetings/{meeting_id}", status_code=204)
async def delete_meeting(meeting_id: str, session: SessionDep) -> None:
    repo = MeetingRepo(session)
    if not await repo.delete(meeting_id):
        raise StorageMeetingNotFoundError(meeting_id)
    await session.commit()


@app.get("/meetings/{meeting_id}/segments")
async def list_segments(meeting_id: str, session: SessionDep) -> list[SegmentResponse]:
    repo_m = MeetingRepo(session)
    if await repo_m.get(meeting_id) is None:
        raise StorageMeetingNotFoundError(meeting_id)
    repo_s = SegmentRepo(session)
    segments = await repo_s.list_by_meeting(meeting_id)
    return [
        SegmentResponse(
            segment_id=s.segment_id,
            text=s.text,
            confidence=s.confidence,
            engine=s.engine,
            model_name=s.model_name,
            audio_start_time=s.audio_start_time,
            audio_end_time=s.audio_end_time,
            language=s.language,
            is_partial=s.is_partial,
            trace_id=s.trace_id,
            speaker_cluster_label=s.speaker_cluster_label,
            speaker_profile_id=s.speaker_profile_id,
        )
        for s in segments
    ]


_SPEAKER_FIELDS = ("speaker_cluster_label", "speaker_profile_id")


def _segment_row(meeting_id: str, seg: BatchSegmentItem) -> dict[str, object]:
    row: dict[str, object] = {
        "meeting_id": meeting_id,
        "segment_id": seg.segment_id,
        "text": seg.text,
        "confidence": seg.confidence,
        "engine": seg.engine,
        "model_name": seg.model_name,
        "audio_start_time": seg.audio_start_time,
        "audio_end_time": seg.audio_end_time,
        "language": seg.language,
        "is_partial": seg.is_partial,
        "trace_id": seg.trace_id,
    }
    # Each speaker field is included independently, based on whether the
    # caller actually set it -- not as an all-or-nothing pair. Including a
    # key (even as `None`) tells `upsert_batch`'s `ON CONFLICT DO UPDATE` to
    # overwrite that column; omitting it leaves any previously-stored value
    # on an existing segment untouched. An item that sets only
    # `speaker_profile_id`, for example, must not also carry
    # `speaker_cluster_label: None` and silently wipe a previously-set label.
    if "speaker_cluster_label" in seg.model_fields_set:
        row["speaker_cluster_label"] = seg.speaker_cluster_label
    if "speaker_profile_id" in seg.model_fields_set:
        row["speaker_profile_id"] = seg.speaker_profile_id
    return row


@app.post("/meetings/{meeting_id}/segments/batch", status_code=204)
async def batch_upsert_segments(
    meeting_id: str, req: BatchSegmentsRequest, session: SessionDep
) -> None:
    repo_m = MeetingRepo(session)
    m = await repo_m.get(meeting_id)
    if m is None:
        raise StorageMeetingNotFoundError(meeting_id)
    repo_s = SegmentRepo(session)
    # `upsert_batch` requires every row in one call to share the same set of
    # keys (it derives `update_cols` from `rows[0]`), so rows are grouped by
    # which of the two speaker fields (if any) were actually set -- up to
    # four groups: neither, only `speaker_cluster_label`, only
    # `speaker_profile_id`, or both.
    groups: dict[frozenset[str], list[dict[str, object]]] = {}
    for seg in req.segments:
        row = _segment_row(meeting_id, seg)
        key = frozenset(seg.model_fields_set & set(_SPEAKER_FIELDS))
        groups.setdefault(key, []).append(row)

    inserted_count = 0
    for rows in groups.values():
        inserted_count += await repo_s.upsert_batch(rows)
    if inserted_count:
        await repo_m.add_segments_count(meeting_id, inserted_count)
    await session.commit()


@app.post("/meetings/{meeting_id}/summary", status_code=201)
async def create_summary(
    meeting_id: str, req: CreateSummaryRequest, session: SessionDep
) -> SummaryResponse:
    repo_m = MeetingRepo(session)
    if await repo_m.get(meeting_id) is None:
        raise StorageMeetingNotFoundError(meeting_id)
    repo_s = SummaryRepo(session)
    if await repo_s.get_by_meeting(meeting_id) is not None:
        raise StorageSummaryAlreadyExistsError(meeting_id)
    summary = Summary(
        id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        title=req.title,
        overview=req.overview,
        key_points=json.dumps(req.key_points),
        action_items=json.dumps(req.action_items),
        quotes=json.dumps(req.quotes),
        provider=req.provider,
        model=req.model,
        created_at=datetime.datetime.now(datetime.UTC),
    )
    try:
        await repo_s.create(summary)
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise StorageSummaryAlreadyExistsError(meeting_id) from None
    await session.refresh(summary)
    return _summary_to_response(summary)


@app.get("/meetings/{meeting_id}/summary")
async def get_summary(meeting_id: str, session: SessionDep) -> SummaryResponse:
    repo_m = MeetingRepo(session)
    if await repo_m.get(meeting_id) is None:
        raise StorageMeetingNotFoundError(meeting_id)
    repo_s = SummaryRepo(session)
    s = await repo_s.get_by_meeting(meeting_id)
    if s is None:
        raise StorageSummaryNotFoundError(meeting_id)
    return _summary_to_response(s)


@app.post("/templates", status_code=201)
async def create_template(req: CreateTemplateRequest, session: SessionDep) -> TemplateResponse:
    repo = TemplateRepo(session)
    now = datetime.datetime.now(datetime.UTC)
    template = SummaryTemplate(
        id=str(uuid.uuid4()),
        name=req.name,
        version=req.version,
        system_prompt=req.system_prompt,
        focus_instructions=req.focus_instructions,
        few_shot_examples=json.dumps([e.model_dump() for e in req.few_shot_examples]),
        created_at=now,
        updated_at=now,
    )
    await repo.create(template)
    await session.commit()
    await session.refresh(template)
    return _template_to_response(template)


@app.get("/templates")
async def list_templates(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TemplateResponse]:
    repo = TemplateRepo(session)
    templates = await repo.list_all(limit=limit, offset=offset)
    return [_template_to_response(t) for t in templates]


@app.get("/templates/{template_id}")
async def get_template(template_id: str, session: SessionDep) -> TemplateResponse:
    repo = TemplateRepo(session)
    template = await repo.get(template_id)
    if template is None:
        raise StorageTemplateNotFoundError(template_id)
    return _template_to_response(template)


@app.patch("/templates/{template_id}")
async def patch_template(
    template_id: str, req: PatchTemplateRequest, session: SessionDep
) -> TemplateResponse:
    repo = TemplateRepo(session)
    fields: dict[str, object] = req.model_dump(exclude_none=True)
    # `exclude_none=True` drops `focus_instructions` whether it was omitted or
    # explicitly sent as `null` — but only omission should mean "leave it
    # alone"; an explicit `null` is a request to clear the stored value.
    if "focus_instructions" in req.model_fields_set:
        fields["focus_instructions"] = req.focus_instructions
    if "few_shot_examples" in fields:
        fields["few_shot_examples"] = json.dumps(
            [e.model_dump() for e in req.few_shot_examples or []]
        )
    if not fields:
        template = await repo.get(template_id)
        if template is None:
            raise StorageTemplateNotFoundError(template_id)
        return _template_to_response(template)
    fields["updated_at"] = datetime.datetime.now(datetime.UTC)
    template = await repo.update(template_id, **fields)
    if template is None:
        raise StorageTemplateNotFoundError(template_id)
    await session.commit()
    await session.refresh(template)
    return _template_to_response(template)


@app.delete("/templates/{template_id}", status_code=204)
async def delete_template(template_id: str, session: SessionDep) -> None:
    repo = TemplateRepo(session)
    if not await repo.delete(template_id):
        raise StorageTemplateNotFoundError(template_id)
    await session.commit()


@app.post("/speaker-profiles", status_code=201)
async def create_speaker_profile(
    req: CreateSpeakerProfileRequest, session: SessionDep
) -> SpeakerProfileResponse:
    repo = SpeakerProfileRepo(session)
    if await repo.get_by_name(req.name) is not None:
        raise StorageSpeakerProfileNameConflictError(req.name)
    now = datetime.datetime.now(datetime.UTC)
    profile = SpeakerProfile(
        id=str(uuid.uuid4()),
        name=req.name,
        voice_embedding=json.dumps(req.voice_embedding),
        created_at=now,
        updated_at=now,
    )
    try:
        await repo.create(profile)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if "uq_speaker_profiles_name" in str(exc.orig):
            raise StorageSpeakerProfileNameConflictError(req.name) from exc
        raise
    await session.refresh(profile)
    return _speaker_profile_to_response(profile)


@app.get("/speaker-profiles")
async def list_speaker_profiles(
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SpeakerProfileResponse]:
    repo = SpeakerProfileRepo(session)
    profiles = await repo.list_all(limit=limit, offset=offset)
    return [_speaker_profile_to_response(p) for p in profiles]


@app.get("/speaker-profiles/{profile_id}")
async def get_speaker_profile(profile_id: str, session: SessionDep) -> SpeakerProfileResponse:
    repo = SpeakerProfileRepo(session)
    profile = await repo.get(profile_id)
    if profile is None:
        raise StorageSpeakerProfileNotFoundError(profile_id)
    return _speaker_profile_to_response(profile)


@app.patch("/speaker-profiles/{profile_id}")
async def patch_speaker_profile(
    profile_id: str, req: PatchSpeakerProfileRequest, session: SessionDep
) -> SpeakerProfileResponse:
    repo = SpeakerProfileRepo(session)
    fields: dict[str, object] = req.model_dump(exclude_none=True)
    if "voice_embedding" in fields:
        fields["voice_embedding"] = json.dumps(req.voice_embedding)
    if not fields:
        profile = await repo.get(profile_id)
        if profile is None:
            raise StorageSpeakerProfileNotFoundError(profile_id)
        return _speaker_profile_to_response(profile)
    fields["updated_at"] = datetime.datetime.now(datetime.UTC)
    profile = await repo.update(profile_id, **fields)
    if profile is None:
        raise StorageSpeakerProfileNotFoundError(profile_id)
    await session.commit()
    await session.refresh(profile)
    return _speaker_profile_to_response(profile)


@app.delete("/speaker-profiles/{profile_id}", status_code=204)
async def delete_speaker_profile(profile_id: str, session: SessionDep) -> None:
    repo = SpeakerProfileRepo(session)
    if not await repo.delete(profile_id):
        raise StorageSpeakerProfileNotFoundError(profile_id)
    await session.commit()


@app.post("/speaker-profiles/match")
async def match_speaker_profile(
    req: MatchSpeakerProfileRequest, session: SessionDep
) -> MatchSpeakerProfileResponse:
    repo = SpeakerProfileRepo(session)
    profiles = await repo.list_all_for_matching()
    candidates = [(p.id, json.loads(p.voice_embedding)) for p in profiles]
    matched_id = best_match(req.voice_embedding, candidates)
    if matched_id is None:
        return MatchSpeakerProfileResponse(profile=None)
    matched = await repo.get(matched_id)
    if matched is None:
        # Vanished between the matching scan and this re-fetch (e.g. a
        # concurrent DELETE /speaker-profiles/{id}) -- a genuine race, not a
        # client error, so treat it the same as "no match" rather than 500ing.
        return MatchSpeakerProfileResponse(profile=None)
    return MatchSpeakerProfileResponse(profile=_speaker_profile_to_response(matched))


async def _match_one(
    repo: SpeakerProfileRepo,
    embedding: list[float],
    candidates: list[tuple[str, list[float]]],
) -> SpeakerProfile | None:
    matched_id = best_match(embedding, candidates)
    if matched_id is None:
        return None
    matched = await repo.get(matched_id)
    return matched


@app.post("/speaker-profiles/match-bulk")
async def match_speaker_profile_bulk(
    req: MatchBulkRequest, session: SessionDep
) -> MatchBulkResponse:
    repo = SpeakerProfileRepo(session)
    profiles = await repo.list_all_for_matching()
    candidates = [(p.id, json.loads(p.voice_embedding)) for p in profiles]
    matches = [
        MatchBulkEntry(
            key=item.key,
            profile=(
                _speaker_profile_to_response(matched)
                if (matched := await _match_one(repo, item.voice_embedding, candidates))
                else None
            ),
        )
        for item in req.embeddings
    ]
    return MatchBulkResponse(matches=matches)


@app.post("/meetings/{meeting_id}/speakers/{cluster_label}/label")
async def label_speaker_in_meeting(
    meeting_id: str,
    cluster_label: str,
    req: LabelSpeakerRequest,
    session: SessionDep,
) -> SpeakerProfileResponse:
    meeting_repo = MeetingRepo(session)
    if await meeting_repo.get(meeting_id) is None:
        raise StorageMeetingNotFoundError(meeting_id)

    profile_repo = SpeakerProfileRepo(session)
    profile = await profile_repo.get_by_name(req.name)
    if profile is None:
        if req.voice_embedding is None:
            raise HTTPException(
                status_code=422,
                detail=f"name '{req.name}' is new; voice_embedding required",
            )
        profile = SpeakerProfile(
            id=str(uuid.uuid4()),
            name=req.name,
            voice_embedding=json.dumps(req.voice_embedding),
            created_at=datetime.datetime.now(datetime.UTC),
            updated_at=datetime.datetime.now(datetime.UTC),
        )
        try:
            await profile_repo.create(profile)
        except IntegrityError:
            await session.rollback()
            existing = await profile_repo.get_by_name(req.name)
            if existing is None:
                raise
            profile = existing
    await session.flush()

    segment_repo = SegmentRepo(session)
    linked = await segment_repo.set_speaker_profile_for_cluster(
        meeting_id, cluster_label, profile.id
    )
    await session.commit()
    _log.info(
        "label_speaker_cluster",
        meeting_id=meeting_id,
        cluster_label=cluster_label,
        speaker_profile_id=profile.id,
        linked_segments=linked,
    )
    await session.refresh(profile)
    return _speaker_profile_to_response(profile)


@app.post("/speaker-profiles/{profile_id}/merge")
async def merge_speaker_profiles(
    profile_id: str,
    req: MergeSpeakersRequest,
    session: SessionDep,
) -> SpeakerProfileResponse:
    if profile_id == req.other_profile_id:
        raise HTTPException(status_code=422, detail="cannot merge a profile with itself")

    repo = SpeakerProfileRepo(session)
    winner = await repo.get(profile_id)
    if winner is None:
        raise StorageSpeakerProfileNotFoundError(profile_id)
    loser = await repo.get(req.other_profile_id)
    if loser is None:
        await session.commit()
        return _speaker_profile_to_response(winner)

    segment_repo = SegmentRepo(session)
    moved = await segment_repo.reassign_speaker_profile(
        from_profile_id=loser.id, to_profile_id=winner.id
    )
    await repo.delete(loser.id)
    await session.commit()
    _log.info(
        "merge_speaker_profiles",
        winner_id=winner.id,
        loser_id=loser.id,
        moved_segments=moved,
    )
    await session.refresh(winner)
    return _speaker_profile_to_response(winner)
