from __future__ import annotations

from collections.abc import AsyncIterator

import grpc
import grpc.aio
import pytest

from bahlily_transcription.grpc_client import AudioCoreClient
from bahlily_transcription.pb.audio_core.v1 import audio_pb2, audio_pb2_grpc


def _make_audio_segment(segment_id: int) -> audio_pb2.AudioSegment:
    seg = audio_pb2.AudioSegment()
    seg.segment_id = segment_id
    seg.sample_rate = 16000
    seg.device_type = audio_pb2.DEVICE_TYPE_MICROPHONE
    seg.trace_id = "test-trace"
    return seg


class FakeAudioCoreServicer(audio_pb2_grpc.AudioServiceServicer):
    def __init__(self, segments: list[audio_pb2.AudioSegment]) -> None:
        self._segments = segments

    async def StreamAudio(
        self,
        request: audio_pb2.StreamAudioRequest,
        context: grpc.aio.ServicerContext,  # type: ignore[type-arg]
    ) -> AsyncIterator[audio_pb2.StreamAudioResponse]:
        for seg in self._segments:
            yield audio_pb2.StreamAudioResponse(segment=seg)


@pytest.fixture
async def fake_server(unused_tcp_port: int) -> AsyncIterator[str]:
    segments = [_make_audio_segment(i) for i in range(3)]
    server = grpc.aio.server()
    audio_pb2_grpc.add_AudioServiceServicer_to_server(FakeAudioCoreServicer(segments), server)
    server.add_insecure_port(f"localhost:{unused_tcp_port}")
    await server.start()
    yield f"localhost:{unused_tcp_port}"
    await server.stop(grace=0)


async def test_client_receives_segments_from_server(fake_server: str) -> None:
    client = AudioCoreClient(addr=fake_server)
    received = []
    async for seg in client.stream_segments():
        received.append(seg.segment_id)
        if len(received) == 3:
            break
    assert received == [0, 1, 2]
