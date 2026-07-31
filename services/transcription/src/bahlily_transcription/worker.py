from __future__ import annotations

import asyncio
import contextlib
import functools
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import scipy.signal
import stamina
import structlog

from bahlily_transcription.engine import TranscriptionEngine
from bahlily_transcription.errors import TranscriptionEngineFailedError
from bahlily_transcription.grpc_server import BroadcastChannel
from bahlily_transcription.models import TranscriptResult
from bahlily_transcription.pb.audio_core.v1 import audio_pb2
from bahlily_transcription.pb.transcription.v1 import transcription_pb2

_log = structlog.get_logger()
_TARGET_SAMPLE_RATE = 16000

_ENGINE_NAME_MAP: dict[str, int] = {
    "whisper": transcription_pb2.ENGINE_WHISPER,
    "parakeet": transcription_pb2.ENGINE_PARAKEET,
}


class SessionWorker:
    def __init__(
        self,
        recording_id: str,
        engine: TranscriptionEngine,
        broadcast: BroadcastChannel,
        executor: ThreadPoolExecutor,
        batch_window_s: float = 0.3,
        max_batch_size: int = 8,
        language: str | None = None,
    ) -> None:
        self._recording_id = recording_id
        self._engine = engine
        self._broadcast = broadcast
        self._executor = executor
        self._batch_window_s = batch_window_s
        self._max_batch_size = max_batch_size
        self._language = language
        self._queue: asyncio.Queue[audio_pb2.AudioSegment] = asyncio.Queue()
        self._stop_event = asyncio.Event()
        self._batch_task: asyncio.Task[None] | None = None
        self._ingest_task: asyncio.Task[None] | None = None
        self.segments_received = 0
        self.segments_transcribed = 0

    async def run(self, audio_stream: AsyncIterator[audio_pb2.AudioSegment]) -> None:
        self._batch_task = asyncio.create_task(self._batch_loop())
        self._ingest_task = asyncio.create_task(self._ingest(audio_stream))
        try:
            await asyncio.gather(self._ingest_task, self._batch_task)
        except Exception:
            if self._ingest_task is not None:
                self._ingest_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._ingest_task
            if self._batch_task is not None:
                self._batch_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._batch_task
            raise

    async def stop(self) -> int:
        self._stop_event.set()
        if self._batch_task is not None:
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass
            except Exception:
                _log.exception(
                    "session_batch_loop_failed",
                    recording_id=self._recording_id,
                )
        if self._ingest_task is not None:
            self._ingest_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._ingest_task
        return self.segments_transcribed

    async def _ingest(self, stream: AsyncIterator[audio_pb2.AudioSegment]) -> None:
        async for seg in stream:
            self.segments_received += 1
            await self._queue.put(seg)

    async def _batch_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop_event.is_set() or not self._queue.empty():
            batch: list[audio_pb2.AudioSegment] = []

            # Block on the first item to avoid busy-spinning when idle.
            if not self._stop_event.is_set():
                try:
                    first = await asyncio.wait_for(self._queue.get(), timeout=self._batch_window_s)
                    batch.append(first)
                except TimeoutError:
                    continue

            # Drain additional items within the window without blocking.
            deadline = loop.time() + self._batch_window_s
            while loop.time() < deadline and len(batch) < self._max_batch_size:
                try:
                    seg = self._queue.get_nowait()
                    batch.append(seg)
                except asyncio.QueueEmpty:
                    break

            if not batch:
                continue

            valid_batch: list[audio_pb2.AudioSegment] = []
            for seg in batch:
                if seg.sample_rate <= 0:
                    _log.warning(
                        "transcription_segment_invalid_sample_rate",
                        recording_id=self._recording_id,
                        segment_id=seg.segment_id,
                        sample_rate=seg.sample_rate,
                    )
                    await self._emit_error(seg.segment_id)
                else:
                    valid_batch.append(seg)

            if not valid_batch:
                continue

            audios = [self._to_numpy(seg) for seg in valid_batch]
            segment_ids = [seg.segment_id for seg in valid_batch]

            try:
                results = await self._transcribe_with_retry(audios)
            except TranscriptionEngineFailedError:
                for seg_id in segment_ids:
                    await self._emit_error(seg_id)
                continue

            if len(results) != len(segment_ids):
                _log.error(
                    "transcription_result_count_mismatch",
                    recording_id=self._recording_id,
                    expected=len(segment_ids),
                    got=len(results),
                )
                for seg_id in segment_ids:
                    await self._emit_error(seg_id)
                continue

            pairs = sorted(zip(segment_ids, results, strict=True), key=lambda x: x[0])
            for seg_id, result in pairs:
                seg_proto = self._result_to_proto(seg_id, result, valid_batch)
                await self._broadcast.publish(seg_proto)
                self.segments_transcribed += 1

    @stamina.retry(
        on=TranscriptionEngineFailedError,
        attempts=3,
        wait_initial=0.1,
        wait_max=1.0,
    )
    async def _transcribe_with_retry(self, audios: list[np.ndarray]) -> list[TranscriptResult]:
        loop = asyncio.get_running_loop()
        fn = functools.partial(self._engine.transcribe_batch, audios, self._language)
        return await loop.run_in_executor(self._executor, fn)

    async def _emit_error(self, segment_id: int) -> None:
        _log.warning(
            "transcription_segment_failed",
            code="TRANSCRIPTION_ENGINE_FAILED",
            recording_id=self._recording_id,
            segment_id=segment_id,
        )
        seg = transcription_pb2.TranscriptSegment()
        seg.segment_id = segment_id
        seg.text = ""
        seg.is_partial = False
        seg.recording_id = self._recording_id
        seg.engine = _ENGINE_NAME_MAP.get(  # type: ignore[assignment]
            self._engine.name, transcription_pb2.ENGINE_UNSPECIFIED
        )
        seg.model_name = self._engine.current_model() or ""
        await self._broadcast.publish(seg)

    def _to_numpy(self, seg: audio_pb2.AudioSegment) -> np.ndarray:
        audio = np.array(seg.data, dtype=np.float32)
        if seg.sample_rate != _TARGET_SAMPLE_RATE:
            audio = scipy.signal.resample_poly(
                audio,
                up=_TARGET_SAMPLE_RATE,
                down=seg.sample_rate,
            ).astype(np.float32)
        return audio

    def _result_to_proto(
        self,
        segment_id: int,
        result: Any,
        batch: list[audio_pb2.AudioSegment],
    ) -> transcription_pb2.TranscriptSegment:
        seg_proto = transcription_pb2.TranscriptSegment()
        seg_proto.segment_id = segment_id
        seg_proto.recording_id = self._recording_id
        seg_proto.is_partial = False
        if isinstance(result, TranscriptResult):
            seg_proto.text = result.text
            seg_proto.audio_start_time = result.audio_start_time
            seg_proto.audio_end_time = result.audio_end_time
            if result.confidence is not None:
                seg_proto.confidence = result.confidence
            if result.language is not None:
                seg_proto.language = result.language
        for orig_seg in batch:
            if orig_seg.segment_id == segment_id:
                seg_proto.trace_id = orig_seg.trace_id
                break
        seg_proto.engine = _ENGINE_NAME_MAP.get(  # type: ignore[assignment]
            self._engine.name, transcription_pb2.ENGINE_UNSPECIFIED
        )
        seg_proto.model_name = self._engine.current_model() or ""
        return seg_proto
