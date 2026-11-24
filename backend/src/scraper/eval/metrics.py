from collections import Counter
from collections.abc import Sequence
from urllib.parse import urlsplit

from scraper.eval.config import EvalConfig
from scraper.schemas.eval import EvalMetrics, EvalReport
from scraper.schemas.product import Product
from scraper.tools.urls import same_site

_FIELD_HINTS = {
    "price": "look near price blocks",
    "image": "look for <img> inside each product card",
    "name": "look at the card's heading or link title",
    "url": "look at the card's main link",
}


def _field_present(p: Product, field: str) -> bool:
    value = getattr(p, field)
    return value is not None and value != ""


def field_coverage(products: Sequence[Product], fields: Sequence[str]) -> float:
    if not products or not fields:
        return 0.0
    present = sum(_field_present(p, f) for p in products for f in fields)
    return present / (len(products) * len(fields))


def plausibility(products: Sequence[Product], allowed_host: str | None, cfg: EvalConfig) -> float:
    """Mean pass rate over: price > 0 when present, URL on the crawled site, unique name,
    sane name length. Rules that cannot apply (no known host) pass."""
    if not products:
        return 0.0
    lo, hi = cfg.name_length
    seen: Counter[str] = Counter()
    passed = 0
    for p in products:
        seen[p.name.lower()] += 1
        passed += p.price is None or p.price > 0
        passed += allowed_host is None or same_site(urlsplit(str(p.url)).hostname, allowed_host)
        passed += seen[p.name.lower()] == 1
        passed += lo <= len(p.name) <= hi
    return passed / (len(products) * 4)


def volume(found: int, limit: int, cfg: EvalConfig) -> float:
    if found == 0:
        return 0.0
    return min(1.0, found / min(limit, cfg.page_size_heuristic))


def _issues(products: Sequence[Product], cfg: EvalConfig, metrics: EvalMetrics) -> list[str]:
    issues: list[str] = []
    n = len(products)
    for field in cfg.key_fields:
        missing = sum(not _field_present(p, field) for p in products)
        if missing:
            issues.append(f"{field} missing on {missing}/{n} items; {_FIELD_HINTS.get(field, '')}")
    if metrics.schema_validity < 1:
        issues.append(
            f"schema validity {metrics.schema_validity:.0%}: some extracted items were invalid"
        )
    if metrics.plausibility < 1:
        issues.append(
            f"plausibility {metrics.plausibility:.0%}: duplicate names, odd prices or off-site URLs"
        )
    if n == 0:
        issues.append("no products found")
    return issues


def build_report(
    products: Sequence[Product],
    *,
    valid_items: int,
    invalid_items: int,
    limit: int,
    allowed_host: str | None,
    min_quality: float,
    can_retry: bool,
    groundedness: float | None = None,
    cfg: EvalConfig | None = None,
) -> EvalReport:
    cfg = cfg or EvalConfig()
    total = valid_items + invalid_items
    metrics = EvalMetrics(
        schema_validity=valid_items / total if total else 0.0,
        field_coverage=field_coverage(products, cfg.key_fields),
        plausibility=plausibility(products, allowed_host, cfg),
        volume=volume(len(products), limit, cfg),
        groundedness=groundedness,
    )
    values = metrics.model_dump()
    # Weights of unavailable metrics drop out instead of counting as zero.
    available = {k: w for k, w in cfg.weights.items() if values.get(k) is not None}
    weight_sum = sum(available.values())
    score = sum(w * values[k] for k, w in available.items()) / weight_sum if weight_sum else 0.0
    if groundedness is None:
        score = min(score, cfg.ungrounded_ceiling)
    score = max(0.0, min(1.0, score))

    issues = _issues(products, cfg, metrics)
    if not products:
        decision = "low_confidence"  # nothing to improve on by retrying deterministically
    elif score >= min_quality:
        decision = "accept"
    else:
        decision = "retry" if can_retry else "low_confidence"
    feedback = "; ".join(issues) if decision == "retry" else ""
    return EvalReport(
        score=score, metrics=metrics, issues=issues, decision=decision, feedback=feedback
    )
