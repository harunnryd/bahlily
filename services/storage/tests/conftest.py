from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bahlily_storage import db as db_module
from bahlily_storage.models import Base


@pytest.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _restore_db_module_config() -> AsyncGenerator[None, None]:
    """`db.upgrade_to_head()` calls `db._configure()`, which rebinds the
    module-level `db._DB_URL`/`db.engine`/`db.async_session_factory` to
    whatever `BAHLILY_STORAGE_DB` a test set for its own tmp_path. Without
    restoring these afterward, that binding leaks into later tests, which
    could then read/write through an engine pointed at a deleted temp file
    instead of the process's real configured database."""
    original_url = db_module._DB_URL
    original_engine = db_module.engine
    original_factory = db_module.async_session_factory
    yield
    if db_module.engine is not original_engine:
        await db_module.engine.dispose()
        db_module._DB_URL = original_url
        db_module.engine = original_engine
        db_module.async_session_factory = original_factory
