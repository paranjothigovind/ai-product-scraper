from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from scraper.schemas.product import BoundedHttpUrl

MAX_HTML_BYTES = 1_000_000


class ScrapeRequest(BaseModel):
    """Validate with `model_validate(data, context={"plan_cap": settings.plan_cap_products})`
    so max_products is checked against the plan cap."""

    model_config = ConfigDict(extra="forbid")

    url: BoundedHttpUrl | None = None
    html: str | None = Field(default=None, min_length=1)
    max_products: int = Field(ge=1)
    scope: Literal["category", "site"] = "site"
    max_pages: int | None = Field(default=None, ge=1)
    max_depth: int = Field(default=2, ge=0, le=5)

    @field_validator("html")
    @classmethod
    def _html_within_limit(cls, value: str | None) -> str | None:
        # Bytes, not characters: multi-byte text must not slip past the 1MB limit.
        if value is not None and len(value.encode("utf-8")) > MAX_HTML_BYTES:
            raise ValueError("html exceeds 1MB")
        return value

    @model_validator(mode="after")
    def _exactly_one_input(self) -> Self:
        if (self.url is None) == (self.html is None):
            raise ValueError("provide exactly one of url or html")
        return self

    @model_validator(mode="after")
    def _within_plan_cap(self, info: ValidationInfo) -> Self:
        cap = info.context.get("plan_cap") if isinstance(info.context, dict) else None
        if isinstance(cap, int) and self.max_products > cap:
            raise ValueError(f"max_products exceeds plan cap of {cap}")
        return self
