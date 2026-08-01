from __future__ import annotations

import asyncio
import contextlib
import datetime
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from pathlib import Path

import grpc
import grpc.aio
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from bahlily_storage.models import Base, Meeting
from bahlily_storage.pb.transcription.v1 import transcription_pb2, transcription_pb2_grpc
from bahlily_storage.repos import MeetingRepo, SegmentRepo


async def _wait_until[T](
    fetch: Callable[[], Awaitable[T]],
    condition: Callable[[T], bool],
    timeout: float = 5.0,
    interval: float = 0.02,
) -> T:
    """Poll `fetch()` until `condition(result)` is true, instead of a fixed sleep."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        value = await fetch()
        if condition(value):
            return value
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(f"condition not met within {timeout}s (last value: {value!r})")
        await asyncio.sleep(interval)


async def _segment_count(factory: async_sessionmaker[AsyncSession], meeting_id: str) -> int:
    async with factory() as session:
        return len(await SegmentRepo(session).list_by_meeting(meeting_id))


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
    def __init__(
        self,
        segments: list[transcription_pb2.TranscriptSegment],
        *,
        hang_after: bool = False,
    ) -> None:
        self._segments = segments
        self._hang_after = hang_after
        self.yielded_count = 0

    async def StreamTranscripts(
        self,
        request: transcription_pb2.StreamTranscriptsRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[transcription_pb2.StreamTranscriptsResponse]:
        for seg in self._segments:
            yield transcription_pb2.StreamTranscriptsResponse(segment=seg)
            self.yielded_count += 1
        if self._hang_after:
            # Keep the stream open (rather than letting it end naturally) so a
            # caller can observe "connected" state that outlives the last
            # segment, instead of racing the subscriber's own post-stream
            # cleanup.
            await asyncio.sleep(30.0)


@pytest.fixture
def unused_tcp_port() -> int:
    import socket

    with socket.socket() as s:
        s.bind(("", 0))
        port: int = s.getsockname()[1]
        return port


DbSession = tuple[AsyncSession, async_sessionmaker[AsyncSession]]


@pytest.fixture
async def db_session(tmp_path: Path) -> AsyncGenerator[DbSession, None]:
    # A real (temp-file) SQLite database is used instead of ":memory:" because
    # this fixture is shared by a background TranscriptionSubscriber and the
    # test's own polling loop, both of which open sessions concurrently via
    # `factory()`. StaticPool alone (still needed below, to avoid
    # "database is locked" errors since all access funnels through one
    # physical connection) is not sufficient for ":memory:": when a test
    # cancels the subscriber task while it holds an open session, the
    # in-flight rollback can raise asyncio.CancelledError, which SQLAlchemy's
    # pool treats as a reason to invalidate and transparently recreate the
    # pooled connection. For "sqlite+aiosqlite:///:memory:" a freshly created
    # connection is a brand-new, empty in-memory database with no tables at
    # all ("no such table: segments"), whereas a temp-file database is still
    # intact on disk after reconnecting.
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
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
            initial_backoff=0.01,
            max_backoff=0.02,
        )
        task = asyncio.create_task(sub.run())
        try:
            await _wait_until(
                lambda: _segment_count(factory, "rec-1"),
                lambda count: count > 0,
            )
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

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
    servicer = FakeTranscriptionServicer([_make_segment("unknown-id", 0)])
    transcription_pb2_grpc.add_TranscriptionServiceServicer_to_server(  # type: ignore[no-untyped-call]
        servicer, server
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
        except TimeoutError:
            pass

        # Confirm the fake stream was actually consumed, not that nothing ran.
        assert servicer.yielded_count > 0

        async with factory() as check_session:
            from sqlalchemy import select

            from bahlily_storage.models import Segment

            result = await check_session.execute(select(Segment))
            assert result.scalars().all() == []
    finally:
        await server.stop(grace=0)


async def test_backoff_grows_when_nothing_is_listening(
    db_session: DbSession, unused_tcp_port: int
) -> None:
    """`insecure_channel` is lazy, so an open channel must not reset the backoff."""
    _, factory = db_session

    from bahlily_storage.grpc_subscriber import TranscriptionSubscriber

    sub = TranscriptionSubscriber(
        addr=f"localhost:{unused_tcp_port}",  # nothing bound here
        session_factory=factory,
        initial_backoff=0.01,
        max_backoff=100.0,
    )
    assert sub.backoff == 0.01

    try:
        await asyncio.wait_for(sub.run(), timeout=1.0)
    except TimeoutError:
        pass

    assert sub.backoff > 0.01


async def test_backoff_resets_once_a_segment_actually_arrives(
    db_session: DbSession, unused_tcp_port: int
) -> None:
    session, factory = db_session

    await MeetingRepo(session).create(
        Meeting(
            id="rec-b",
            status="recording",
            started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            segments_count=0,
        )
    )
    await session.commit()

    server = grpc.aio.server()
    transcription_pb2_grpc.add_TranscriptionServiceServicer_to_server(  # type: ignore[no-untyped-call]
        FakeTranscriptionServicer([_make_segment("rec-b", 0)]), server
    )
    server.add_insecure_port(f"localhost:{unused_tcp_port}")
    await server.start()

    try:
        from bahlily_storage.grpc_subscriber import TranscriptionSubscriber

        sub = TranscriptionSubscriber(
            addr=f"localhost:{unused_tcp_port}",
            session_factory=factory,
            initial_backoff=0.01,
            max_backoff=100.0,
        )
        sub._backoff = 8.0
        try:
            await asyncio.wait_for(sub.run(), timeout=1.0)
        except TimeoutError:
            pass

        # A real response arrived, so the backoff was reset to its initial value
        # (it may have grown again afterwards, but never past 8.0).
        assert sub.backoff < 8.0
    finally:
        await server.stop(grace=0)


async def test_redelivered_segment_does_not_double_count(
    db_session: DbSession, unused_tcp_port: int
) -> None:
    """A redelivered (meeting_id, segment_id) is an UPDATE, so must not bump the count."""
    session, factory = db_session

    await MeetingRepo(session).create(
        Meeting(
            id="rec-dup",
            status="recording",
            started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            segments_count=0,
        )
    )
    await session.commit()

    seg = _make_segment("rec-dup", 0)
    server = grpc.aio.server()
    transcription_pb2_grpc.add_TranscriptionServiceServicer_to_server(  # type: ignore[no-untyped-call]
        FakeTranscriptionServicer([seg, seg]), server
    )
    server.add_insecure_port(f"localhost:{unused_tcp_port}")
    await server.start()

    try:
        from bahlily_storage.grpc_subscriber import TranscriptionSubscriber

        sub = TranscriptionSubscriber(
            addr=f"localhost:{unused_tcp_port}",
            session_factory=factory,
            initial_backoff=0.01,
            max_backoff=0.02,
        )
        task = asyncio.create_task(sub.run())
        try:
            # Wait for the redelivery to actually have happened rather than for
            # a fixed wall-clock budget: the stream yields the same segment
            # twice, and the fast backoff redelivers it on every reconnect.
            deadline = asyncio.get_running_loop().time() + 5.0
            while asyncio.get_running_loop().time() < deadline:
                async with factory() as check:
                    segments = await SegmentRepo(check).list_by_meeting("rec-dup")
                if segments:
                    break
                await asyncio.sleep(0.02)
            # let several more reconnect/redelivery rounds land
            await asyncio.sleep(0.3)
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        async with factory() as check:
            segments = await SegmentRepo(check).list_by_meeting("rec-dup")
            meeting = await MeetingRepo(check).get("rec-dup")
        assert len(segments) == 1
        assert meeting is not None
        assert meeting.segments_count == 1
    finally:
        await server.stop(grace=0)


async def test_subscriber_status_reports_connected_on_real_segment(
    db_session: DbSession, unused_tcp_port: int
) -> None:
    from bahlily_storage.grpc_subscriber import TranscriptionSubscriber, subscriber_status

    session, factory = db_session
    await MeetingRepo(session).create(
        Meeting(
            id="rec-status",
            status="recording",
            started_at=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
            segments_count=0,
        )
    )
    await session.commit()

    server = grpc.aio.server()
    transcription_pb2_grpc.add_TranscriptionServiceServicer_to_server(  # type: ignore[no-untyped-call]
        FakeTranscriptionServicer([_make_segment("rec-status", 0)], hang_after=True), server
    )
    server.add_insecure_port(f"localhost:{unused_tcp_port}")
    await server.start()

    try:
        sub = TranscriptionSubscriber(
            addr=f"localhost:{unused_tcp_port}",
            session_factory=factory,
            initial_backoff=0.01,
            max_backoff=0.02,
        )
        task = asyncio.create_task(sub.run())
        try:
            await _wait_until(
                lambda: _segment_count(factory, "rec-status"),
                lambda count: count > 0,
            )
            status = subscriber_status()
            assert status["connected"] is True
            assert status["last_segment_at"] is not None
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    finally:
        await server.stop(grace=0)
