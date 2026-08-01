from __future__ import annotations

import asyncio
import datetime
from typing import Any

import grpc
import grpc.aio
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bahlily_storage.pb.transcription.v1 import transcription_pb2, transcription_pb2_grpc
from bahlily_storage.repos import MeetingRepo, SegmentRepo

_log = structlog.get_logger()

_ENGINE_MAP = {
    transcription_pb2.ENGINE_WHISPER: "whisper",
    transcription_pb2.ENGINE_PARAKEET: "parakeet",
}

_status: dict[str, Any] = {"connected": False, "last_segment_at": None}


def subscriber_status() -> dict[str, object]:
    return dict(_status)


class TranscriptionSubscriber:
    def __init__(
        self,
        addr: str,
        session_factory: async_sessionmaker[AsyncSession],
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ) -> None:
        self._addr = addr
        self._factory = session_factory
        self._initial_backoff = initial_backoff
        self._max_backoff = max_backoff
        self._backoff = initial_backoff

    @property
    def backoff(self) -> float:
        """Seconds to wait before the next reconnect attempt."""
        return self._backoff

    async def run(self) -> None:
        while True:
            try:
                await self._stream_once()
            except grpc.aio.AioRpcError as exc:
                _status["connected"] = False
                _log.warning(
                    "transcription_subscriber_disconnected",
                    addr=self._addr,
                    backoff_s=self._backoff,
                    error=str(exc),
                )
            except Exception:
                _status["connected"] = False
                _log.exception("transcription_subscriber_error")
            await asyncio.sleep(self._backoff)
            self._backoff = min(self._backoff * 2, self._max_backoff)

    async def _stream_once(self) -> None:
        """Open a channel and consume the transcript stream until it ends.

        `grpc.aio.insecure_channel` is lazy: it never blocks on an actual
        connection, so having a channel and a stub proves nothing about the
        peer. The backoff is therefore only reset once a response has really
        been received — otherwise a down transcription service would be retried
        at the initial interval forever and the growth would be dead code.
        """
        async with grpc.aio.insecure_channel(self._addr) as channel:
            stub = transcription_pb2_grpc.TranscriptionServiceStub(  # type: ignore[no-untyped-call]
                channel
            )
            async for response in stub.StreamTranscripts(
                transcription_pb2.StreamTranscriptsRequest()
            ):
                self._backoff = self._initial_backoff
                _status["connected"] = True
                await self._handle_segment(response.segment)
                _status["last_segment_at"] = datetime.datetime.now(datetime.UTC).isoformat()

    async def _handle_segment(self, seg: transcription_pb2.TranscriptSegment) -> None:
        async with self._factory() as session:
            repo_m = MeetingRepo(session)
            meeting = await repo_m.get(seg.recording_id)
            if meeting is None:
                _log.warning(
                    "segment_for_unknown_meeting",
                    recording_id=seg.recording_id,
                    segment_id=seg.segment_id,
                )
                return

            engine_str = _ENGINE_MAP.get(seg.engine, "unknown")
            inserted = await SegmentRepo(session).upsert(
                {
                    "meeting_id": seg.recording_id,
                    "segment_id": seg.segment_id,
                    "text": seg.text,
                    "confidence": seg.confidence if seg.HasField("confidence") else None,
                    "engine": engine_str,
                    "model_name": seg.model_name,
                    "audio_start_time": seg.audio_start_time,
                    "audio_end_time": seg.audio_end_time,
                    "language": seg.language if seg.HasField("language") else None,
                    "is_partial": seg.is_partial,
                    "trace_id": seg.trace_id,
                }
            )
            # Only a genuine INSERT moves the counter; a redelivered segment
            # (reconnect, at-least-once stream) is an UPDATE and must not.
            if inserted:
                await repo_m.increment_segments_count(seg.recording_id)

            if not meeting.engine:
                await repo_m.update_engine_metadata(
                    seg.recording_id,
                    engine=engine_str,
                    model_name=seg.model_name,
                    language=seg.language if seg.HasField("language") else None,
                )

            await session.commit()
