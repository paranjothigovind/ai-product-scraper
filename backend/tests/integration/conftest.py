import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from scraper.db.repo import SessionFactory
from scraper.db.session import create_engine, create_session_factory

BACKEND = Path(__file__).resolve().parents[2]


def _alembic_upgrade(url: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        check=True,
        capture_output=True,
    )


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """A real Postgres: TEST_DATABASE_URL if set, otherwise a throwaway container.
    The schema is built by running the real Alembic migrations."""
    url = os.environ.get("TEST_DATABASE_URL")
    container = None
    if not url:
        try:
            from testcontainers.postgres import PostgresContainer

            container = PostgresContainer("postgres:16-alpine", driver="asyncpg")
            container.start()
            url = container.get_connection_url()
        except Exception as exc:  # Docker missing or unreachable: skip, do not fail
            pytest.skip(f"no Postgres available (set TEST_DATABASE_URL or start Docker): {exc}")
    _alembic_upgrade(url)
    try:
        yield url
    finally:
        if container is not None:
            container.stop()


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_engine(database_url)
    yield eng
    await eng.dispose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> SessionFactory:
    return create_session_factory(engine)
