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
_DB_URL = f"sqlite+aiosqlite:///{os.environ.get('BAHLILY_STORAGE_DB', _DEFAULT_DB)}"


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
