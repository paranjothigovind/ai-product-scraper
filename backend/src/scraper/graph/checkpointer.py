from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


def to_psycopg_conninfo(database_url: str) -> str:
    """Our DATABASE_URL names the SQLAlchemy driver; psycopg wants a plain libpq URL."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@asynccontextmanager
async def postgres_checkpointer(database_url: str) -> AsyncIterator[AsyncPostgresSaver]:
    """thread_id = run_id. The library owns its checkpoint tables and creates them itself in
    `setup()` (idempotent), outside Alembic. Use MemorySaver only in unit tests."""
    async with AsyncPostgresSaver.from_conn_string(to_psycopg_conninfo(database_url)) as saver:
        await saver.setup()
        yield saver
