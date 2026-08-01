from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bahlily_storage.models import Base

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


def _make_engine(url: str) -> AsyncEngine:
    eng = create_async_engine(url, echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def _set_pragma(dbapi_conn: Any, _: Any) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
