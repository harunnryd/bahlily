from __future__ import annotations

import asyncio
import datetime
from collections.abc import AsyncGenerator, AsyncIterator

import grpc
import grpc.aio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bahlily_storage.models import Base, Meeting
from bahlily_storage.pb.transcription.v1 import transcription_pb2, transcription_pb2_grpc
from bahlily_storage.repos import MeetingRepo, SegmentRepo


def _make_segment(recording_id: str, segment_id: int) -> transcription_pb2.TranscriptSegment:
    seg = transcription_pb2.TranscriptSegment()
    seg.recording_id = recording_id
    seg.segment_id = segment_id
    seg.text = f"segment {segment_id}"
    seg.engine = transcription_pb2.ENGINE_WHISPER
    seg.model_name = "tiny"
    seg.audio_start_time = float(segment_id)
    seg.audio_end_time = float(segment_id) + 1.0
    seg.is_partial = False
    seg.trace_id = "trace-1"
    return seg


class FakeTranscriptionServicer(transcription_pb2_grpc.TranscriptionServiceServicer):
    def __init__(self, segments: list[transcription_pb2.TranscriptSegment]) -> None:
        self._segments = segments

    async def StreamTranscripts(
        self,
        request: transcription_pb2.StreamTranscriptsRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[transcription_pb2.StreamTranscriptsResponse]:
        for seg in self._segments:
            yield transcription_pb2.StreamTranscriptsResponse(segment=seg)


@pytest.fixture
def unused_tcp_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("", 0))
        port: int = s.getsockname()[1]
        return port


DbSession = tuple[AsyncSession, async_sessionmaker[AsyncSession]]


@pytest.fixture
async def db_session() -> AsyncGenerator[DbSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s, factory
    await engine.dispose()


async def test_subscriber_persists_known_segment(
    db_session: DbSession, unused_tcp_port: int
) -> None:
    session, factory = db_session

    repo_m = MeetingRepo(session)
    await repo_m.create(
        Meeting(
            id="rec-1",
            status="recording",
            started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            segments_count=0,
        )
    )
    await session.commit()

    server = grpc.aio.server()
    transcription_pb2_grpc.add_TranscriptionServiceServicer_to_server(  # type: ignore[no-untyped-call]
        FakeTranscriptionServicer([_make_segment("rec-1", 0)]), server
    )
    server.add_insecure_port(f"localhost:{unused_tcp_port}")
    await server.start()

    try:
        from bahlily_storage.grpc_subscriber import TranscriptionSubscriber

        sub = TranscriptionSubscriber(
            addr=f"localhost:{unused_tcp_port}",
            session_factory=factory,
        )
        try:
            await asyncio.wait_for(sub.run(), timeout=2.0)
        except (TimeoutError, Exception):
            pass

        async with factory() as check_session:
            segments = await SegmentRepo(check_session).list_by_meeting("rec-1")
        assert len(segments) == 1
        assert segments[0].text == "segment 0"
    finally:
        await server.stop(grace=0)


async def test_subscriber_skips_unknown_meeting(
    db_session: DbSession, unused_tcp_port: int
) -> None:
    session, factory = db_session

    server = grpc.aio.server()
    transcription_pb2_grpc.add_TranscriptionServiceServicer_to_server(  # type: ignore[no-untyped-call]
        FakeTranscriptionServicer([_make_segment("unknown-id", 0)]), server
    )
    server.add_insecure_port(f"localhost:{unused_tcp_port}")
    await server.start()

    try:
        from bahlily_storage.grpc_subscriber import TranscriptionSubscriber

        sub = TranscriptionSubscriber(
            addr=f"localhost:{unused_tcp_port}",
            session_factory=factory,
        )
        try:
            await asyncio.wait_for(sub.run(), timeout=2.0)
        except (TimeoutError, Exception):
            pass

        async with factory() as check_session:
            from sqlalchemy import select

            from bahlily_storage.models import Segment

            result = await check_session.execute(select(Segment))
            assert result.scalars().all() == []
    finally:
        await server.stop(grace=0)
