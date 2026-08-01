from __future__ import annotations

import datetime
import json
import uuid
from typing import Annotated

import structlog
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from bahlily_storage.db import get_session
from bahlily_storage.errors import (
    StorageMeetingAlreadyExistsError,
    StorageMeetingNotFoundError,
    StorageSummaryAlreadyExistsError,
    StorageSummaryNotFoundError,
)
from bahlily_storage.grpc_subscriber import subscriber_status
from bahlily_storage.models import Meeting, Summary
from bahlily_storage.repos import MeetingRepo, SegmentRepo, SummaryRepo
from bahlily_storage.schemas import (
    BatchSegmentsRequest,
    CreateMeetingRequest,
    CreateSummaryRequest,
    MeetingResponse,
    PatchMeetingRequest,
    SegmentResponse,
    SummaryResponse,
)

_log = structlog.get_logger()

app = FastAPI(title="bahlily-storage")

_ERROR_STATUS: dict[type[Exception], int] = {
    StorageMeetingNotFoundError: 404,
    StorageMeetingAlreadyExistsError: 409,
    StorageSummaryAlreadyExistsError: 409,
    StorageSummaryNotFoundError: 404,
}

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@app.exception_handler(StorageMeetingNotFoundError)
@app.exception_handler(StorageMeetingAlreadyExistsError)
@app.exception_handler(StorageSummaryAlreadyExistsError)
@app.exception_handler(StorageSummaryNotFoundError)
async def _error_handler(request: Request, exc: Exception) -> JSONResponse:
    status = _ERROR_STATUS[type(exc)]
    return JSONResponse(
        status_code=status,
        content={"code": exc.code, "message": str(exc)},  # type: ignore[attr-defined]
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
        has_summary=m.summary is not None,
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
    await repo.create(m)
    await session.commit()
    await session.refresh(m)
    return _meeting_to_response(m)


@app.get("/meetings")
async def list_meetings(
    session: SessionDep,
    limit: int = 20,
    offset: int = 0,
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
        )
        for s in segments
    ]


@app.post("/meetings/{meeting_id}/segments/batch", status_code=204)
async def batch_upsert_segments(
    meeting_id: str, req: BatchSegmentsRequest, session: SessionDep
) -> None:
    repo_m = MeetingRepo(session)
    m = await repo_m.get(meeting_id)
    if m is None:
        raise StorageMeetingNotFoundError(meeting_id)
    repo_s = SegmentRepo(session)
    rows: list[dict[str, object]] = [
        {
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
        for seg in req.segments
    ]
    await repo_s.upsert_batch(rows)
    updated_segments = await repo_s.list_by_meeting(meeting_id)
    await repo_m.update(meeting_id, segments_count=len(updated_segments))
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
    await repo_s.create(summary)
    await session.commit()
    await session.refresh(summary)
    return SummaryResponse(
        id=summary.id,
        meeting_id=summary.meeting_id,
        title=summary.title,
        overview=summary.overview,
        key_points=json.loads(summary.key_points),
        action_items=json.loads(summary.action_items),
        quotes=json.loads(summary.quotes),
        provider=summary.provider,
        model=summary.model,
        created_at=summary.created_at,
    )


@app.get("/meetings/{meeting_id}/summary")
async def get_summary(meeting_id: str, session: SessionDep) -> SummaryResponse:
    repo_m = MeetingRepo(session)
    if await repo_m.get(meeting_id) is None:
        raise StorageMeetingNotFoundError(meeting_id)
    repo_s = SummaryRepo(session)
    s = await repo_s.get_by_meeting(meeting_id)
    if s is None:
        raise StorageSummaryNotFoundError(meeting_id)
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
