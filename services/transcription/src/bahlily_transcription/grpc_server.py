from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import grpc
import grpc.aio
import structlog

from bahlily_transcription.pb.transcription.v1 import transcription_pb2, transcription_pb2_grpc

_log = structlog.get_logger()

_BROADCAST_CAPACITY = 100


class BroadcastChannel:
    def __init__(self, capacity: int = _BROADCAST_CAPACITY) -> None:
        self._capacity = capacity
        self._subscribers: list[asyncio.Queue[transcription_pb2.TranscriptSegment]] = []

    def subscribe(self) -> asyncio.Queue[transcription_pb2.TranscriptSegment]:
        q: asyncio.Queue[transcription_pb2.TranscriptSegment] = asyncio.Queue(
            maxsize=self._capacity
        )
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[transcription_pb2.TranscriptSegment]) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def publish(self, segment: transcription_pb2.TranscriptSegment) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(segment)
            except asyncio.QueueFull:
                _log.warning(
                    "transcript_broadcast_lagged",
                    code="AUDIO_STREAM_LAGGED",
                    recording_id=segment.recording_id,
                )


class TranscriptionGrpcService(transcription_pb2_grpc.TranscriptionServiceServicer):
    def __init__(self, broadcast: BroadcastChannel) -> None:
        self._broadcast = broadcast

    async def StreamTranscripts(
        self,
        request: transcription_pb2.StreamTranscriptsRequest,
        context: grpc.aio.ServicerContext[
            transcription_pb2.StreamTranscriptsRequest,
            transcription_pb2.StreamTranscriptsResponse,
        ],
    ) -> AsyncIterator[transcription_pb2.StreamTranscriptsResponse]:
        q = self._broadcast.subscribe()
        try:
            while True:
                segment = await q.get()
                yield transcription_pb2.StreamTranscriptsResponse(segment=segment)
        finally:
            self._broadcast.unsubscribe(q)


async def serve(broadcast: BroadcastChannel, port: int) -> None:
    server = grpc.aio.server()
    transcription_pb2_grpc.add_TranscriptionServiceServicer_to_server(  # type: ignore[no-untyped-call]
        TranscriptionGrpcService(broadcast), server
    )
    bound_port = server.add_insecure_port(f"0.0.0.0:{port}")
    if bound_port == 0:
        raise OSError(f"gRPC server failed to bind to port {port}")
    await server.start()
    _log.info("transcription_grpc_server_started", port=bound_port)
    await server.wait_for_termination()
