from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bahlily_storage.models import Base

if TYPE_CHECKING:
    from alembic.config import Config

_DEFAULT_DB = str(Path.home() / ".bahlily" / "storage.db")


def resolve_db_url() -> str:
    """Compute the sqlite+aiosqlite URL from BAHLILY_STORAGE_DB (or the default path).

    Recomputed fresh on every call (rather than cached) so callers that need the
    *current* env var value at call time — e.g. the Alembic migration environment,
    which may run after this module was already imported with a different value —
    get an up-to-date result instead of a value frozen at import time.
    """
    url = f"sqlite+aiosqlite:///{os.environ.get('BAHLILY_STORAGE_DB', _DEFAULT_DB)}"
    db_path_str = url.split("///", 1)[1]
    if db_path_str != ":memory:":
        Path(db_path_str).parent.mkdir(parents=True, exist_ok=True)
    return url


_DB_URL = resolve_db_url()


BUSY_TIMEOUT_MS = 5000


def _make_engine(url: str) -> AsyncEngine:
    eng = create_async_engine(url, echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def _set_pragma(dbapi_conn: Any, _: Any) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        # Two write paths share this file in one process (HTTP handlers and the
        # background gRPC subscriber). WAL lets readers proceed during a write,
        # and busy_timeout makes a contended writer wait instead of failing
        # immediately with "database is locked".
        # `PRAGMA journal_mode` returns a row, so it must be fetched or the
        # sqlite3 driver leaves the statement unread.
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.fetchall()
        cursor.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        cursor.fetchall()
        cursor.close()

    return eng


engine: AsyncEngine = _make_engine(_DB_URL)
async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    """Create the schema directly from the ORM metadata.

    Convenient for tests that want a schema without the Alembic machinery. It
    does NOT stamp `alembic_version`, so it must not be used as the production
    startup path — use `upgrade_to_head()` for that.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def find_alembic_ini() -> Path:
    """Locate `alembic.ini` by walking up from this package.

    The ini lives at the service root (`services/storage/alembic.ini`) next to
    the `migrations/` directory, which is outside the importable package, so it
    cannot be resolved as package data. Walking up from `__file__` works for
    both a source checkout and an editable install.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "alembic.ini"
        if candidate.is_file() and (parent / "migrations" / "versions").is_dir():
            return candidate
    raise FileNotFoundError("could not locate alembic.ini relative to bahlily_storage")


def alembic_config() -> Config:
    from alembic.config import Config

    ini = find_alembic_ini()
    cfg = Config(str(ini))
    cfg.set_main_option("sqlalchemy.url", resolve_db_url())
    return cfg


def upgrade_to_head_sync() -> None:
    """Run `alembic upgrade head` synchronously. Blocks; call off the event loop."""
    from alembic import command

    command.upgrade(alembic_config(), "head")


async def upgrade_to_head() -> None:
    """Bring the database to the latest migration revision.

    `alembic.command.upgrade` is synchronous and our `migrations/env.py` spins
    up its own event loop via `asyncio.run`, so it must run on a worker thread
    rather than on the running loop.
    """
    await asyncio.to_thread(upgrade_to_head_sync)
