from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from bahlily_transcription.grpc_server import BroadcastChannel
from bahlily_transcription.pb.audio_core.v1 import audio_pb2
from bahlily_transcription.pb.transcription.v1.transcription_pb2 import TranscriptSegment
from bahlily_transcription.worker import SessionWorker


def _make_audio_segment(segment_id: int, sample_rate: int = 16000) -> audio_pb2.AudioSegment:
    seg = audio_pb2.AudioSegment()
    seg.segment_id = segment_id
    seg.sample_rate = sample_rate
    seg.data.extend([0.0] * 16000)
    seg.trace_id = "trace-1"
    return seg


async def _stream_segments(
    segments: list[audio_pb2.AudioSegment],
) -> AsyncIterator[audio_pb2.AudioSegment]:
    for seg in segments:
        yield seg


@pytest.mark.asyncio
async def test_worker_transcribes_segments_in_order(fake_engine) -> None:  # type: ignore[no-untyped-def]
    fake_engine.load_model("test-model")
    broadcast = BroadcastChannel(capacity=50)
    q = broadcast.subscribe()
    executor = ThreadPoolExecutor(max_workers=1)

    worker = SessionWorker(
        recording_id="rec-1",
        engine=fake_engine,
        broadcast=broadcast,
        executor=executor,
        batch_window_s=0.05,
        max_batch_size=4,
    )

    segments = [_make_audio_segment(i) for i in range(3)]
    task = asyncio.create_task(worker.run(_stream_segments(segments)))
    await asyncio.sleep(0.3)
    count = await worker.stop()
    await task

    received_ids = []
    while not q.empty():
        seg: TranscriptSegment = q.get_nowait()
        received_ids.append(seg.segment_id)

    assert received_ids == sorted(received_ids)
    assert count == 3
    assert worker.segments_transcribed == 3


@pytest.mark.asyncio
async def test_worker_resamples_non_16k_audio(fake_engine) -> None:  # type: ignore[no-untyped-def]
    fake_engine.load_model("test-model")
    broadcast = BroadcastChannel(capacity=50)
    q = broadcast.subscribe()
    executor = ThreadPoolExecutor(max_workers=1)

    worker = SessionWorker(
        recording_id="rec-1",
        engine=fake_engine,
        broadcast=broadcast,
        executor=executor,
        batch_window_s=0.05,
        max_batch_size=4,
    )

    seg = _make_audio_segment(0, sample_rate=44100)
    seg.data.extend([0.0] * (44100 - 16000))

    task = asyncio.create_task(worker.run(_stream_segments([seg])))
    await asyncio.sleep(0.3)
    count = await worker.stop()
    await task

    assert count == 1
    assert not q.empty()
    result = q.get_nowait()
    assert result.segment_id == 0


@pytest.mark.asyncio
async def test_worker_emits_error_segment_after_engine_exhaustion() -> None:
    import stamina

    class AlwaysFailEngine:
        _name = "fake"
        _loaded: str | None = "test"

        @property
        def name(self) -> str:
            return self._name

        def is_model_loaded(self) -> bool:
            return True

        def current_model(self) -> str | None:
            return self._loaded

        def load_model(self, name: str) -> None:
            self._loaded = name

        def unload_model(self) -> None:
            self._loaded = None

        def transcribe(self, audio: np.ndarray, language: str | None) -> None:  # type: ignore[override]
            from bahlily_transcription.errors import TranscriptionEngineFailedError

            raise TranscriptionEngineFailedError("fake", "always fails")

        def transcribe_batch(self, audios: list[np.ndarray], language: str | None) -> list[None]:  # type: ignore[override]
            return [self.transcribe(a, language) for a in audios]

    broadcast = BroadcastChannel(capacity=50)
    q = broadcast.subscribe()
    executor = ThreadPoolExecutor(max_workers=1)
    engine = AlwaysFailEngine()

    worker = SessionWorker(
        recording_id="rec-1",
        engine=engine,  # type: ignore[arg-type]
        broadcast=broadcast,
        executor=executor,
        batch_window_s=0.05,
        max_batch_size=4,
    )

    with stamina.set_testing(True):
        task = asyncio.create_task(worker.run(_stream_segments([_make_audio_segment(0)])))
        await asyncio.sleep(0.3)
        count = await worker.stop()
        await task

    assert count == 0

    result = q.get_nowait()
    assert result.text == ""
    assert not result.is_partial
