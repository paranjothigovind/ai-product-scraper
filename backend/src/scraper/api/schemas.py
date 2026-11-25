import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from scraper.db.models import CategoryRow, ProductRow, Run

TERMINAL = ("succeeded", "failed", "low_confidence", "cancelled")


class ProductOut(BaseModel):
    id: str
    rank: int | None
    score: float | None
    reason: str | None
    name: str
    url: str
    price: float | None
    currency: str | None
    image: str | None
    brand: str | None
    category: str | None
    rating: float | None
    review_count: int | None
    availability: str
    description: str | None
    source: str

    @classmethod
    def from_row(cls, row: ProductRow) -> "ProductOut":
        return cls(
            id=str(row.id),
            rank=row.rank,
            score=row.score,
            reason=row.reason,
            name=row.name,
            url=row.canonical_url,
            price=float(row.price) if row.price is not None else None,
            currency=row.currency,
            image=row.image,
            brand=row.brand,
            category=row.category,
            rating=row.rating,
            review_count=row.review_count,
            availability=row.availability,
            description=row.description,
            source=row.source,
        )


class CategoryOut(BaseModel):
    name: str
    slug: str
    url: str | None
    parent: str | None
    product_count: int | None

    @classmethod
    def from_row(cls, row: CategoryRow) -> "CategoryOut":
        return cls(
            name=row.name,
            slug=row.slug,
            url=row.url,
            parent=row.parent,
            product_count=row.product_count,
        )


class RunOut(BaseModel):
    id: uuid.UUID
    status: Literal["queued", "running", "succeeded", "failed", "low_confidence", "cancelled"]
    input_type: str
    source_url: str | None
    requested: int
    score: float | None
    confidence: str | None
    pages_fetched: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    error_code: str | None
    incomplete_reason: str | None
    cancel_requested: bool
    created_at: datetime
    finished_at: datetime | None
    # Present once the run has finished; None while it is queued or running.
    products: list[ProductOut] | None = None
    categories: list[CategoryOut] | None = None

    @classmethod
    def from_row(
        cls,
        run: Run,
        products: list[ProductRow] | None = None,
        categories: list[CategoryRow] | None = None,
    ) -> "RunOut":
        return cls(
            id=run.id,
            status=run.status,
            input_type=run.input_type,
            source_url=run.source_url,
            requested=run.requested,
            score=run.score,
            confidence=run.confidence,
            pages_fetched=run.pages_fetched,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=float(run.cost_usd),
            error_code=run.error_code,
            incomplete_reason=run.incomplete_reason,
            cancel_requested=run.cancel_requested,
            created_at=run.created_at,
            finished_at=run.finished_at,
            products=[ProductOut.from_row(p) for p in products] if products is not None else None,
            categories=(
                [CategoryOut.from_row(c) for c in categories] if categories is not None else None
            ),
        )


class Accepted(BaseModel):
    id: uuid.UUID
    status: str
    created: bool
