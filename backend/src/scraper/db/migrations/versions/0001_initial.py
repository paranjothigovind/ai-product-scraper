"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID_PK = sa.text("gen_random_uuid()")


def _run_fk() -> sa.Column[object]:
    return sa.Column(
        "run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_UUID_PK),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text()),
        sa.Column("input_type", sa.String(8), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("requested", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float()),
        sa.Column("confidence", sa.String(8)),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(32)),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'low_confidence', 'cancelled')",
            name="ck_runs_status",
        ),
        sa.CheckConstraint("input_type IN ('url', 'html')", name="ck_runs_input_type"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="runs_user_idem_key"),
    )
    op.create_index("runs_user_created_idx", "runs", ["user_id", "created_at"])

    op.create_table(
        "run_pages",
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("page_no", sa.Integer(), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("fetch_tier", sa.String(8), nullable=False),
        sa.Column("http_status", sa.Integer()),
        sa.Column("bytes", sa.Integer()),
        sa.Column("html_ref", sa.Text()),
        sa.Column("duration_ms", sa.Integer()),
        sa.CheckConstraint("fetch_tier IN ('static', 'render')", name="ck_pages_tier"),
    )

    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=_UUID_PK),
        _run_fk(),
        sa.Column("rank", sa.Integer()),
        sa.Column("score", sa.Float()),
        sa.Column("reason", sa.Text()),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("price", sa.Numeric(14, 2)),
        sa.Column("currency", sa.String(8)),
        sa.Column("image", sa.Text()),
        sa.Column("brand", sa.Text()),
        sa.Column("category", sa.Text()),
        sa.Column("rating", sa.Float()),
        sa.Column("review_count", sa.Integer()),
        sa.Column("availability", sa.String(16), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("source", sa.String(16), nullable=False),
        sa.UniqueConstraint("run_id", "canonical_url", name="products_run_url_key"),
        sa.CheckConstraint(
            "availability IN ('in_stock', 'out_of_stock', 'unknown')",
            name="ck_products_availability",
        ),
        sa.CheckConstraint(
            "source IN ('jsonld', 'microdata', 'selector', 'llm')", name="ck_products_source"
        ),
    )

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        _run_fk(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("parent", sa.Text()),
        sa.Column("product_count", sa.Integer()),
        sa.UniqueConstraint("run_id", "slug", name="categories_run_slug_key"),
    )

    op.create_table(
        "eval_reports",
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("attempt", sa.Integer(), primary_key=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(), nullable=False),
        sa.Column("issues_json", postgresql.JSONB(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("feedback", sa.Text()),
        sa.CheckConstraint(
            "decision IN ('accept', 'retry', 'low_confidence')", name="ck_eval_decision"
        ),
    )

    op.create_table(
        "trace_events",
        sa.Column(
            "run_id", sa.Uuid(), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("seq", sa.Integer(), primary_key=True),
        sa.Column("node", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("in_count", sa.Integer()),
        sa.Column("out_count", sa.Integer()),
        sa.Column("meta_json", postgresql.JSONB()),
    )
