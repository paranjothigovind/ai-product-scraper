from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, UrlConstraints

# Stricter than pydantic's default 2083 so every URL fits the API's 2048 limit.
BoundedHttpUrl = Annotated[HttpUrl, UrlConstraints(max_length=2048)]

Availability = Literal["in_stock", "out_of_stock", "unknown"]
ProductSource = Literal["jsonld", "microdata", "selector", "llm"]


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    url: BoundedHttpUrl
    price: float | None = Field(default=None, ge=0)
    currency: str | None = None
    image: BoundedHttpUrl | None = None
    brand: str | None = None
    category: str | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int | None = Field(default=None, ge=0)
    availability: Availability = "unknown"
    description: str | None = None
    source: ProductSource


class RankedProduct(Product):
    rank: int = Field(ge=1)
    score: float = Field(ge=0, le=1)
    reason: str | None = None


class Category(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    url: BoundedHttpUrl | None = None
    parent: str | None = None
    product_count: int | None = Field(default=None, ge=0)
