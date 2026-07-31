from __future__ import annotations

import asyncio

import grpc
import grpc.aio
import pytest

from bahlily_transcription.grpc_server import BroadcastChannel, TranscriptionGrpcService, serve
from bahlily_transcription.pb.transcription.v1 import transcription_pb2, transcription_pb2_grpc


def _make_segment(segment_id: int, text: str = "hello") -> transcription_pb2.TranscriptSegment:
    seg = transcription_pb2.TranscriptSegment()
    seg.segment_id = segment_id
    seg.text = text
    seg.recording_id = "rec-1"
    return seg


@pytest.mark.asyncio
async def test_single_subscriber_receives_published_segment() -> None:
    channel = BroadcastChannel(capacity=10)
    q = channel.subscribe()
    seg = _make_segment(1)
    await channel.publish(seg)
    received = q.get_nowait()
    assert received.segment_id == 1


@pytest.mark.asyncio
async def test_two_subscribers_each_receive_segment() -> None:
    channel = BroadcastChannel(capacity=10)
    q1 = channel.subscribe()
    q2 = channel.subscribe()
    await channel.publish(_make_segment(2))
    assert q1.get_nowait().segment_id == 2
    assert q2.get_nowait().segment_id == 2


@pytest.mark.asyncio
async def test_full_queue_skips_that_subscriber_only() -> None:
    channel = BroadcastChannel(capacity=1)
    q_full = channel.subscribe()
    q_ok = channel.subscribe()
    q_full.put_nowait(_make_segment(0))
    await channel.publish(_make_segment(1))
    assert q_ok.qsize() == 1
    assert q_full.qsize() == 1


@pytest.mark.asyncio
async def test_unsubscribe_stops_receiving() -> None:
    channel = BroadcastChannel(capacity=10)
    q = channel.subscribe()
    channel.unsubscribe(q)
    await channel.publish(_make_segment(3))
    assert q.empty()


@pytest.mark.asyncio
async def test_stream_transcripts_delivers_published_segments(
    unused_tcp_port: int,
) -> None:
    channel = BroadcastChannel(capacity=10)
    server = grpc.aio.server()
    transcription_pb2_grpc.add_TranscriptionServiceServicer_to_server(  # type: ignore[no-untyped-call]
        TranscriptionGrpcService(channel), server
    )
    server.add_insecure_port(f"localhost:{unused_tcp_port}")
    await server.start()

    try:
        import asyncio

        async with grpc.aio.insecure_channel(f"localhost:{unused_tcp_port}") as grpc_channel:
            stub = transcription_pb2_grpc.TranscriptionServiceStub(grpc_channel)  # type: ignore[no-untyped-call]
            received: list[transcription_pb2.TranscriptSegment] = []

            async def _receive_one() -> None:
                async for resp in stub.StreamTranscripts(
                    transcription_pb2.StreamTranscriptsRequest()
                ):
                    received.append(resp.segment)
                    return

            receive_task = asyncio.create_task(_receive_one())
            # Wait for the subscriber to register before publishing.
            for _ in range(50):
                if len(channel._subscribers) > 0:
                    break
                await asyncio.sleep(0.01)
            await channel.publish(_make_segment(42, text="hello rpc"))
            await asyncio.wait_for(receive_task, timeout=2.0)

        assert len(received) == 1
        assert received[0].segment_id == 42
        assert received[0].text == "hello rpc"
    finally:
        await server.stop(grace=0)


@pytest.mark.asyncio
async def test_stream_transcripts_unsubscribes_on_disconnect(
    unused_tcp_port: int,
) -> None:
    channel = BroadcastChannel(capacity=10)
    server = grpc.aio.server()
    transcription_pb2_grpc.add_TranscriptionServiceServicer_to_server(  # type: ignore[no-untyped-call]
        TranscriptionGrpcService(channel), server
    )
    server.add_insecure_port(f"localhost:{unused_tcp_port}")
    await server.start()

    try:
        assert len(channel._subscribers) == 0
        async with grpc.aio.insecure_channel(f"localhost:{unused_tcp_port}") as grpc_channel:
            stub = transcription_pb2_grpc.TranscriptionServiceStub(grpc_channel)  # type: ignore[no-untyped-call]
            # Wait for subscriber to register.
            receive_iter = stub.StreamTranscripts(transcription_pb2.StreamTranscriptsRequest())
            for _ in range(50):
                if len(channel._subscribers) > 0:
                    break
                await asyncio.sleep(0.01)
            await channel.publish(_make_segment(1))
            async for _ in receive_iter:
                break
        # After channel context closes, poll until cleanup completes.
        for _ in range(100):
            if len(channel._subscribers) == 0:
                break
            await asyncio.sleep(0.01)
        assert len(channel._subscribers) == 0
    finally:
        await server.stop(grace=0)


@pytest.mark.asyncio
async def test_serve_raises_oserror_on_bind_failure(unused_tcp_port: int) -> None:
    """serve() raises OSError when add_insecure_port returns 0 (bind failed)."""
    from unittest.mock import MagicMock, patch

    broadcast = BroadcastChannel(capacity=1)
    mock_server = MagicMock()
    mock_server.add_insecure_port.return_value = 0
    with patch("bahlily_transcription.grpc_server.grpc.aio.server", return_value=mock_server):
        with pytest.raises(OSError, match="failed to bind"):
            await serve(broadcast, unused_tcp_port)


@pytest.mark.asyncio
async def test_serve_starts_successfully_and_logs_bound_port(unused_tcp_port: int) -> None:
    """serve() calls server.start() and waits for termination when bind succeeds."""
    from unittest.mock import AsyncMock, MagicMock, patch

    broadcast = BroadcastChannel(capacity=1)
    mock_server = MagicMock()
    mock_server.add_insecure_port.return_value = unused_tcp_port
    mock_server.start = AsyncMock()
    mock_server.wait_for_termination = AsyncMock()

    with patch("bahlily_transcription.grpc_server.grpc.aio.server", return_value=mock_server):
        await serve(broadcast, unused_tcp_port)

    mock_server.add_insecure_port.assert_called_once_with(f"0.0.0.0:{unused_tcp_port}")
    mock_server.start.assert_called_once()
    mock_server.wait_for_termination.assert_called_once()
