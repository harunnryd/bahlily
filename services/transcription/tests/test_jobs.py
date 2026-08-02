from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from bahlily_transcription.jobs import JobStore


@dataclass
class FakeState:
    status: str = "pending"


def _store(
    *,
    ttl_seconds: float = 3600.0,
    sweep_interval_seconds: float = 60.0,
    is_terminal: Callable[[FakeState], bool] | None = None,
    clock: Callable[[], float] | None = None,
) -> JobStore[FakeState]:
    return JobStore[FakeState](
        ttl_seconds=ttl_seconds,
        sweep_interval_seconds=sweep_interval_seconds,
        is_terminal=is_terminal if is_terminal is not None else (lambda s: s.status == "failed"),
        clock=clock if clock is not None else time.monotonic,
    )


def test_put_get_roundtrip() -> None:
    store = _store(clock=lambda: 1000.0)
    store.put("a", FakeState(status="started"))
    job = store.get("a")
    assert job.job_id == "a"
    assert job.state.status == "started"
    assert job.created_at == 1000.0
    assert job.updated_at == 1000.0


def test_get_unknown_raises_keyerror() -> None:
    store = _store()
    with pytest.raises(KeyError):
        store.get("missing")


def test_update_replaces_state_and_refreshes_updated_at() -> None:
    clock_value = 1000.0

    def clock() -> float:
        return clock_value

    store = _store(clock=clock)
    store.put("a", FakeState(status="started"))
    clock_value = 2000.0
    store.update("a", FakeState(status="running"))
    job = store.get("a")
    assert job.state.status == "running"
    assert job.updated_at == 2000.0


def test_update_unknown_raises_keyerror() -> None:
    store = _store()
    with pytest.raises(KeyError):
        store.update("missing", FakeState(status="started"))


def test_discard_removes_entry() -> None:
    store = _store()
    store.put("a", FakeState())
    store.discard("a")
    with pytest.raises(KeyError):
        store.get("a")


def test_discard_unknown_is_silent() -> None:
    store = _store()
    store.discard("never-existed")
