from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import structlog

from bahlily_transcription.models import (
    DiarizeJobStatus,
    DiarizeSpeaker,
    TranscriptSegmentSchema,
)
from bahlily_transcription.worker import SessionWorker


@dataclass
class Job[StateT]:
    job_id: str
    state: StateT
    created_at: float
    updated_at: float


@dataclass
class SessionState:
    status: str
    worker: SessionWorker


@dataclass
class DiarizeJobState:
    status: DiarizeJobStatus
    result: tuple[list[TranscriptSegmentSchema], list[DiarizeSpeaker]] | None = None
    error: str | None = None


class JobStore[StateT]:
    def __init__(
        self,
        *,
        ttl_seconds: float,
        sweep_interval_seconds: float,
        is_terminal: Callable[[StateT], bool],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._jobs: dict[str, Job[StateT]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._sweep_interval = sweep_interval_seconds
        self._is_terminal = is_terminal
        self._clock = clock
        self._sweeper: asyncio.Task[None] | None = None

    def put(self, job_id: str, state: StateT) -> None:
        with self._lock:
            now = self._clock()
            self._jobs[job_id] = Job(job_id=job_id, state=state, created_at=now, updated_at=now)

    def get(self, job_id: str) -> Job[StateT]:
        # Reading a job refreshes its `updated_at` so the TTL sweep sees recent
        # activity; without this, a long-polling client would lose the entry
        # the moment `updated_at` crossed `now - ttl_seconds`.
        with self._lock:
            job = self._jobs[job_id]
            job.updated_at = self._clock()
            return job

    def update(self, job_id: str, state: StateT) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.state = state
            job.updated_at = self._clock()

    def discard(self, job_id: str) -> None:
        with self._lock:
            self._jobs.pop(job_id, None)

    def start_sweeper(self) -> None:
        if self._sweeper is not None:
            return
        self._sweeper = asyncio.create_task(self._sweep_loop())

    async def stop_sweeper(self) -> None:
        task = self._sweeper
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._sweeper = None

    def _sweep_once(self, now: float) -> None:
        with self._lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if self._is_terminal(job.state) and now - job.updated_at > self._ttl
            ]
            for job_id in expired:
                self._jobs.pop(job_id, None)

    async def _sweep_loop(self) -> None:
        _log = structlog.get_logger()
        while True:
            await asyncio.sleep(self._sweep_interval)
            try:
                self._sweep_once(self._clock())
            except Exception:
                _log.exception("job_store_sweep_failed")
