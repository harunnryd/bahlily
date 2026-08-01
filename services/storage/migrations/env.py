from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from bahlily_storage.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Mirrors bahlily_storage.db's URL resolution, but recomputed here (rather
# than importing db._DB_URL) so that BAHLILY_STORAGE_DB changes made *after*
# bahlily_storage.db has already been imported elsewhere in the process
# (e.g. by another test module) are still honored.
_DEFAULT_DB = str(Path.home() / ".bahlily" / "storage.db")
_URL = f"sqlite+aiosqlite:///{os.environ.get('BAHLILY_STORAGE_DB', _DEFAULT_DB)}"
_DB_PATH_STR = _URL.split("///", 1)[1]
if _DB_PATH_STR != ":memory:":
    Path(_DB_PATH_STR).parent.mkdir(parents=True, exist_ok=True)


def run_migrations_offline() -> None:
    context.configure(url=_URL, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _URL
    connectable = async_engine_from_config(cfg, prefix="sqlalchemy.", poolclass=NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online_sync() -> None:
    asyncio.run(run_migrations_online())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online_sync()
