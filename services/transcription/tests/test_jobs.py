from __future__ import annotations

import asyncio
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


def test_pop_if_terminal_returns_and_removes_when_terminal() -> None:
    store = _store(is_terminal=lambda s: s.status == "done")
    store.put("a", FakeState(status="done"))
    job = store.pop_if_terminal("a")
    assert job is not None
    assert job.job_id == "a"
    with pytest.raises(KeyError):
        store.get("a")


def test_pop_if_terminal_returns_none_when_not_terminal() -> None:
    store = _store(is_terminal=lambda s: s.status == "done")
    store.put("a", FakeState(status="running"))
    assert store.pop_if_terminal("a") is None
    assert store.get("a").state.status == "running"


def test_pop_if_terminal_returns_none_when_missing() -> None:
    store = _store()
    assert store.pop_if_terminal("nope") is None


def test_sweep_once_removes_terminal_older_than_ttl() -> None:
    store = _store(
        ttl_seconds=100.0,
        is_terminal=lambda s: s.status == "done",
        clock=lambda: 1000.0,
    )
    store.put("a", FakeState(status="done"))
    store._sweep_once(now=2000.0)
    with pytest.raises(KeyError):
        store.get("a")


def test_sweep_once_skips_terminal_within_ttl() -> None:
    store = _store(
        ttl_seconds=100.0,
        is_terminal=lambda s: s.status == "done",
        clock=lambda: 1000.0,
    )
    store.put("a", FakeState(status="done"))
    store._sweep_once(now=1050.0)
    assert store.get("a").state.status == "done"


def test_sweep_once_skips_nonterminal_even_if_old() -> None:
    store = _store(
        ttl_seconds=100.0,
        is_terminal=lambda s: s.status == "done",
        clock=lambda: 1000.0,
    )
    store.put("a", FakeState(status="running"))
    store._sweep_once(now=99999.0)
    assert store.get("a").state.status == "running"


def test_sweep_once_removes_only_expired_terminal_entries() -> None:
    now = 1000.0

    def clock() -> float:
        return now

    store = _store(
        ttl_seconds=500.0,
        is_terminal=lambda s: s.status == "done",
        clock=clock,
    )
    store.put("old_terminal", FakeState(status="done"))
    now = 1700.0
    store.put("fresh_terminal", FakeState(status="done"))
    now = 2000.0
    store.put("running", FakeState(status="running"))
    store._sweep_once(now=2000.0)
    with pytest.raises(KeyError):
        store.get("old_terminal")
    assert store.get("fresh_terminal").state.status == "done"
    assert store.get("running").state.status == "running"


async def test_start_sweeper_is_idempotent() -> None:
    store = _store(sweep_interval_seconds=0.01)
    store.start_sweeper()
    first_task = store._sweeper
    assert first_task is not None
    store.start_sweeper()
    assert store._sweeper is first_task
    await store.stop_sweeper()


async def test_stop_sweeper_clears_task_and_is_safe_when_unstarted() -> None:
    store = _store()
    await store.stop_sweeper()
    assert store._sweeper is None


async def test_stop_sweeper_cancels_running_task() -> None:
    store = _store(sweep_interval_seconds=0.01)
    store.start_sweeper()
    task = store._sweeper
    assert task is not None
    await store.stop_sweeper()
    assert store._sweeper is None
    assert task.cancelled() or task.done()


async def test_sweeper_loop_runs_sweep() -> None:
    store = _store(
        ttl_seconds=0.0,
        sweep_interval_seconds=0.01,
        is_terminal=lambda s: s.status == "done",
    )
    store.start_sweeper()
    store.put("a", FakeState(status="done"))
    for _ in range(50):
        await asyncio.sleep(0.01)
        if "a" not in store._jobs:
            break
    assert "a" not in store._jobs
    await store.stop_sweeper()
