import math
from collections.abc import Sequence

from pydantic import BaseModel

from scraper.schemas.product import Product, RankedProduct


class RankWeights(BaseModel):
    rating: float = 0.35
    reviews: float = 0.25
    completeness: float = 0.20
    availability: float = 0.10
    price_value: float = 0.10
    # Bayesian prior strength: how many "average" reviews every product starts with.
    prior_weight: float = 10.0
    default_mean_rating: float = 3.5


_AVAILABILITY = {"in_stock": 1.0, "unknown": 0.5, "out_of_stock": 0.0}
_COMPLETENESS_FIELDS = (
    "price",
    "image",
    "brand",
    "category",
    "rating",
    "review_count",
    "description",
)


def rank_products(
    products: Sequence[Product], weights: RankWeights | None = None
) -> list[RankedProduct]:
    """Deterministic ranking. Missing signals lower a product's score; none can raise."""
    w = weights or RankWeights()
    if not products:
        return []

    rated = [p.rating for p in products if p.rating is not None]
    mean_rating = sum(rated) / len(rated) if rated else w.default_mean_rating
    max_reviews = max((p.review_count or 0 for p in products), default=0)
    prices = [p.price for p in products if p.price is not None]
    lo, hi = (min(prices), max(prices)) if prices else (0.0, 0.0)

    scored: list[tuple[float, Product]] = []
    for p in products:
        if p.rating is None:
            rating_bayes = 0.0
        else:
            n = p.review_count or 0
            bayes = (w.prior_weight * mean_rating + n * p.rating) / (w.prior_weight + n)
            rating_bayes = bayes / 5.0
        reviews = (
            math.log1p(p.review_count) / math.log1p(max_reviews)
            if p.review_count and max_reviews
            else 0.0
        )
        completeness = sum(getattr(p, f) is not None for f in _COMPLETENESS_FIELDS) / len(
            _COMPLETENESS_FIELDS
        )
        if p.price is None:
            price_value = 0.0
        else:
            # TODO(next): rating-per-price instead of "cheaper is better within this pool".
            price_value = 1.0 if hi == lo else 1.0 - (p.price - lo) / (hi - lo)
        score = (
            w.rating * rating_bayes
            + w.reviews * reviews
            + w.completeness * completeness
            + w.availability * _AVAILABILITY[p.availability]
            + w.price_value * price_value
        )
        scored.append((max(0.0, min(1.0, score)), p))

    # Ties break on name then URL so the order is reproducible.
    scored.sort(key=lambda t: (-t[0], t[1].name.lower(), str(t[1].url)))
    return [
        RankedProduct(**p.model_dump(), rank=i, score=round(s, 6))
        for i, (s, p) in enumerate(scored, start=1)
    ]
