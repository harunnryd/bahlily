from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import grpc
import grpc.aio
import structlog

from bahlily_transcription.pb.audio_core.v1 import audio_pb2, audio_pb2_grpc

_log = structlog.get_logger()


class AudioCoreClient:
    def __init__(self, addr: str = "localhost:50051") -> None:
        self._addr = addr

    async def stream_segments(self) -> AsyncIterator[audio_pb2.AudioSegment]:
        backoff = 1.0
        while True:
            try:
                async with grpc.aio.insecure_channel(self._addr) as channel:
                    stub = audio_pb2_grpc.AudioServiceStub(channel)  # type: ignore[no-untyped-call]
                    backoff = 1.0
                    async for response in stub.StreamAudio(audio_pb2.StreamAudioRequest()):
                        yield response.segment
            except grpc.aio.AioRpcError as exc:
                _log.warning(
                    "audio_core_connection_lost",
                    addr=self._addr,
                    backoff_s=backoff,
                    error=str(exc),
                )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
