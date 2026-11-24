import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

RUN_STATUSES = ("queued", "running", "succeeded", "failed", "low_confidence", "cancelled")


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))


def _run_fk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, ForeignKey("runs.id", ondelete="CASCADE"), nullable=False)


# Every query must filter by runs.user_id; child tables are reached through run_id.
# TODO(next): separate api/worker DB roles and grants (auth phase).
class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in RUN_STATUSES) + ")", name="ck_runs_status"
        ),
        CheckConstraint("input_type IN ('url', 'html')", name="ck_runs_input_type"),
        Index("runs_user_created_idx", "user_id", "created_at"),
        # NULL keys never collide, so runs without an idempotency key are unaffected.
        UniqueConstraint("user_id", "idempotency_key", name="runs_user_idem_key"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    input_type: Mapped[str] = mapped_column(String(8), nullable=False)
    input_hash: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    requested: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[str | None] = mapped_column(String(8))
    pages_fetched: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(32))
    incomplete_reason: Mapped[str | None] = mapped_column(Text)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunPage(Base):
    __tablename__ = "run_pages"
    __table_args__ = (CheckConstraint("fetch_tier IN ('static', 'render')", name="ck_pages_tier"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    page_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    fetch_tier: Mapped[str] = mapped_column(String(8), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer)
    bytes: Mapped[int | None] = mapped_column(Integer)
    html_ref: Mapped[str | None] = mapped_column(Text)  # S3 key, 7-day TTL
    duration_ms: Mapped[int | None] = mapped_column(Integer)


class ProductRow(Base):
    __tablename__ = "products"
    __table_args__ = (
        # Idempotency key: a resumed node upserts instead of duplicating.
        UniqueConstraint("run_id", "canonical_url", name="products_run_url_key"),
        CheckConstraint(
            "availability IN ('in_stock', 'out_of_stock', 'unknown')",
            name="ck_products_availability",
        ),
        CheckConstraint(
            "source IN ('jsonld', 'microdata', 'selector', 'llm')", name="ck_products_source"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = _run_fk()
    rank: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str | None] = mapped_column(String(8))
    image: Mapped[str | None] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[float | None] = mapped_column(Float)
    review_count: Mapped[int | None] = mapped_column(Integer)
    availability: Mapped[str] = mapped_column(String(16), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), nullable=False)


class CategoryRow(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("run_id", "slug", name="categories_run_slug_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = _run_fk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    parent: Mapped[str | None] = mapped_column(Text)
    product_count: Mapped[int | None] = mapped_column(Integer)


class EvalReportRow(Base):
    __tablename__ = "eval_reports"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('accept', 'retry', 'low_confidence')", name="ck_eval_decision"
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    issues_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    feedback: Mapped[str | None] = mapped_column(Text)


class TraceEvent(Base):
    __tablename__ = "trace_events"

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    node: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    in_count: Mapped[int | None] = mapped_column(Integer)
    out_count: Mapped[int | None] = mapped_column(Integer)
    meta_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
