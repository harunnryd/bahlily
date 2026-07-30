from __future__ import annotations

import pytest

from bahlily_transcription.grpc_server import BroadcastChannel
from bahlily_transcription.pb.transcription.v1.transcription_pb2 import TranscriptSegment


def _make_segment(segment_id: int, text: str = "hello") -> TranscriptSegment:
    seg = TranscriptSegment()
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
    # Pre-fill q_full directly so only it is at capacity; q_ok stays empty
    q_full.put_nowait(_make_segment(0))
    # This publish should skip q_full (full) but reach q_ok
    await channel.publish(_make_segment(1))
    assert q_ok.qsize() == 1
    # q_full only has the pre-filled message
    assert q_full.qsize() == 1


@pytest.mark.asyncio
async def test_unsubscribe_stops_receiving() -> None:
    channel = BroadcastChannel(capacity=10)
    q = channel.subscribe()
    channel.unsubscribe(q)
    await channel.publish(_make_segment(3))
    assert q.empty()
