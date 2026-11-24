from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from scraper.schemas.error_code import ErrorCode
from scraper.schemas.eval import EvalReport
from scraper.schemas.product import Category, RankedProduct

SCHEMA_VERSION = "1"


class ScrapeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    # None for raw-HTML input, where there is no source URL.
    source_url: str | None
    scraped_at: datetime
    pages_fetched: int = Field(ge=0)
    requested: int = Field(ge=1)
    products: list[RankedProduct]
    categories: list[Category]
    evaluation: EvalReport
    confidence: Literal["high", "medium", "low"]
    incomplete: bool
    # Why fewer than `requested` products came back; None when complete.
    incomplete_reason: str | None = None
    invalid_count: int = Field(ge=0)
    error_code: ErrorCode | None = None
