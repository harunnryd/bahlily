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
    ) -> None:
        self._addr = addr
        self._factory = session_factory

    async def run(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with grpc.aio.insecure_channel(self._addr) as channel:
                    stub = transcription_pb2_grpc.TranscriptionServiceStub(  # type: ignore[no-untyped-call]
                        channel
                    )
                    backoff = 1.0
                    _status["connected"] = True
                    async for response in stub.StreamTranscripts(
                        transcription_pb2.StreamTranscriptsRequest()
                    ):
                        await self._handle_segment(response.segment)
                        _status["last_segment_at"] = datetime.datetime.now(datetime.UTC).isoformat()
            except grpc.aio.AioRpcError as exc:
                _status["connected"] = False
                _log.warning(
                    "transcription_subscriber_disconnected",
                    addr=self._addr,
                    backoff_s=backoff,
                    error=str(exc),
                )
            except Exception:
                _status["connected"] = False
                _log.exception("transcription_subscriber_error")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

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
            await SegmentRepo(session).upsert(
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
            await repo_m.increment_segments_count(seg.recording_id)

            if not meeting.engine:
                await repo_m.update_engine_metadata(
                    seg.recording_id,
                    engine=engine_str,
                    model_name=seg.model_name,
                    language=seg.language if seg.HasField("language") else None,
                )

            await session.commit()
