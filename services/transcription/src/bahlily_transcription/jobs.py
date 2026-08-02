from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

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
        self._ttl = ttl_seconds
        self._sweep_interval = sweep_interval_seconds
        self._is_terminal = is_terminal
        self._clock = clock
        self._sweeper: asyncio.Task[None] | None = None

    def put(self, job_id: str, state: StateT) -> None:
        now = self._clock()
        self._jobs[job_id] = Job(job_id=job_id, state=state, created_at=now, updated_at=now)

    def get(self, job_id: str) -> Job[StateT]:
        job = self._jobs[job_id]
        job.updated_at = self._clock()
        return job

    def update(self, job_id: str, state: StateT) -> None:
        job = self._jobs[job_id]
        job.state = state
        job.updated_at = self._clock()

    def discard(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)
