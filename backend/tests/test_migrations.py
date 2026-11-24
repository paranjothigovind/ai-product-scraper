"""Drift guard for environments without Postgres: render the migrations to SQL offline and check
every model table, column and idempotency constraint appears. The integration suite applies
them for real."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scraper.db.models import Base

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def migration_sql() -> str:
    env = {**os.environ, "DATABASE_URL": "postgresql+asyncpg://u:p@localhost/db"}
    out = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout


def test_every_model_table_and_column_is_in_the_migrations(migration_sql: str) -> None:
    for table in Base.metadata.sorted_tables:
        match = re.search(rf"CREATE TABLE {table.name} \((.*?)\n\)", migration_sql, re.S)
        assert match, f"table {table.name} missing from migrations"
        body = match.group(1)
        for column in table.columns:
            created = re.search(rf"^\s*{column.name} ", body, re.M)
            added = f"ALTER TABLE {table.name} ADD COLUMN {column.name} " in migration_sql
            assert created or added, f"{table.name}.{column.name}"


def test_idempotency_constraints_exist(migration_sql: str) -> None:
    assert "products_run_url_key UNIQUE (run_id, canonical_url)" in migration_sql
    assert "categories_run_slug_key UNIQUE (run_id, slug)" in migration_sql
    assert "runs_user_idem_key UNIQUE (user_id, idempotency_key)" in migration_sql
