"""Async database engine, session factory, and the FastAPI session dependency."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from api.config import get_settings

# Render's free Postgres has a low connection limit and no managed pooler (like PgBouncer),
# so the app keeps its own small pool: at most pool_size + max_overflow = 5 connections.
engine = create_async_engine(
    get_settings().database_url,
    pool_size=3,
    max_overflow=2,
    pool_pre_ping=True,  # check a connection is alive before using it (Render drops idle ones)
    pool_recycle=300,  # replace connections older than 5 minutes
)

# expire_on_commit=False keeps loaded attributes usable after commit, which matters in async
# code where touching an expired attribute would trigger an implicit (and illegal) lazy load.
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield one session per request; it is closed (and its connection returned) afterwards."""
    async with SessionLocal() as session:
        yield session
