from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from scraper.schemas.error_code import ErrorCode


class PageRecord(BaseModel):
    page_no: int
    url: str
    fetch_tier: Literal["static", "render"] = "static"
    http_status: int | None = None
    bytes: int | None = None
    duration_ms: int | None = None


class TraceRecord(BaseModel):
    node: str
    started_at: datetime
    duration_ms: int
    in_count: int | None = None
    out_count: int | None = None
    meta: dict[str, object] = Field(default_factory=dict)


class RunOutcome(BaseModel):
    status: Literal["succeeded", "failed", "low_confidence", "cancelled"]
    error_code: ErrorCode | None
    confidence: Literal["high", "medium", "low"]
    score: float
    pages_fetched: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    incomplete: bool
    incomplete_reason: str | None
