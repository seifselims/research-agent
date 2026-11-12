"""Alembic environment: tells Alembic which database to use and what the models look like.

Run from apps/api:
    uv run alembic revision --autogenerate -m "describe the change"   # create a migration
    uv run alembic upgrade head                                       # apply all migrations
    uv run alembic downgrade -1                                       # undo the last one
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from api.config import get_settings
from api.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate compares this (the models) against the real database to find differences.
target_metadata = Base.metadata

# The same DATABASE_URL the app uses, from .env locally or Render's environment in production.
# Kept out of alembic.ini so credentials never end up in a committed file.
DATABASE_URL = get_settings().database_url


def run_migrations_offline() -> None:
    """Print the migration SQL instead of running it (uv run alembic upgrade head --sql)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    # NullPool: a migration is a one-off command, so open a single connection and close it.
    engine = create_async_engine(DATABASE_URL, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())
