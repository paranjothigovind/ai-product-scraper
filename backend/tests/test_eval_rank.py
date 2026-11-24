from typing import Any

from scraper.eval.config import EvalConfig
from scraper.eval.metrics import build_report, field_coverage, plausibility, volume
from scraper.ranking.score import rank_products
from scraper.schemas.product import Product
from scraper.tools.urls import same_site


def product(i: int = 1, **kw: Any) -> Product:
    base: dict[str, Any] = {
        "id": str(i),
        "name": f"Product {i}",
        "url": f"https://shop.test/p/{i}",
        "price": 10.0,
        "image": f"https://shop.test/i/{i}.jpg",
        "source": "jsonld",
    }
    return Product.model_validate(base | kw)


def report(products: list[Product], **kw: Any):  # type: ignore[no-untyped-def]
    args: dict[str, Any] = {
        "valid_items": len(products),
        "invalid_items": 0,
        "limit": max(len(products), 1),
        "allowed_host": "shop.test",
        "min_quality": 0.75,
        "can_retry": False,
    }
    return build_report(products, **(args | kw))


def test_perfect_products_score_at_the_ungrounded_ceiling_and_are_accepted() -> None:
    r = report([product(i) for i in range(5)])
    assert r.score == 0.9 and r.decision == "accept" and r.issues == []
    assert r.metrics.groundedness is None


def test_a_grounded_perfect_run_can_reach_one() -> None:
    assert report([product(i) for i in range(5)], groundedness=1.0).score == 1.0


def test_zero_products_scores_zero_with_nothing_to_retry() -> None:
    r = report([], limit=5)
    assert r.score == 0 and r.metrics.volume == 0 and r.decision == "low_confidence"
    assert "no products found" in r.issues


def test_feedback_is_concrete_and_only_present_on_retry() -> None:
    products = [product(i, price=None) for i in range(14)] + [product(i + 20) for i in range(6)]
    r = report(products, can_retry=True, min_quality=0.99)
    assert r.decision == "retry"
    assert "price missing on 14/20 items" in r.feedback and "price blocks" in r.feedback
    assert report(products, can_retry=False, min_quality=0.99).feedback == ""


def test_schema_validity_reflects_invalid_items() -> None:
    r = report([product(i) for i in range(4)], valid_items=4, invalid_items=4)
    assert r.metrics.schema_validity == 0.5
    assert any("schema validity" in i for i in r.issues)


def test_field_coverage_counts_key_fields() -> None:
    cfg = EvalConfig()
    assert field_coverage([product(1), product(2, price=None, image=None)], cfg.key_fields) == 0.75
    assert field_coverage([], cfg.key_fields) == 0


def test_plausibility_rules() -> None:
    cfg = EvalConfig()
    assert plausibility([product(1)], "shop.test", cfg) == 1
    bad = [
        product(1, price=0),  # price must be > 0 when present
        product(2, name="ab"),  # name too short
        product(3, url="https://elsewhere.test/p"),  # off-site
        product(4, name="Product 1"),  # duplicate of the first
    ]
    assert plausibility(bad, "shop.test", cfg) == 12 / 16
    assert plausibility([product(1)], None, cfg) == 1  # no known host: rule does not apply


def test_volume_against_the_page_size_heuristic() -> None:
    cfg = EvalConfig(page_size_heuristic=20)
    assert volume(0, 50, cfg) == 0
    assert volume(10, 50, cfg) == 0.5
    assert volume(3, 3, cfg) == 1  # asked for 3, got 3
    assert volume(50, 50, cfg) == 1


def test_same_site() -> None:
    assert same_site("www.shop.test", "shop.test") and same_site("SHOP.test", "shop.test")
    assert not same_site("evil.test", "shop.test") and not same_site(None, "shop.test")


# --- ranking ----------------------------------------------------------------------------------


def test_a_five_star_with_one_review_does_not_beat_4_7_with_800() -> None:
    a = product(1, rating=5.0, review_count=1)
    b = product(2, rating=4.7, review_count=800)
    ranked = rank_products([a, b])
    assert [p.name for p in ranked] == ["Product 2", "Product 1"]
    assert [p.rank for p in ranked] == [1, 2]


def test_missing_signals_lower_the_score_and_never_crash() -> None:
    full = product(
        1,
        rating=4.5,
        review_count=100,
        brand="B",
        category="C",
        description="D",
        availability="in_stock",
    )
    bare = Product(id="x", name="Bare", url="https://shop.test/bare", source="llm")
    ranked = rank_products([bare, full])
    assert ranked[0].name == "Product 1" and ranked[0].score > ranked[1].score
    assert 0 <= ranked[1].score <= 1


def test_availability_and_price_matter_but_ties_are_stable() -> None:
    cheap = product(1, price=5.0, availability="in_stock")
    pricey = product(2, price=50.0, availability="in_stock")
    gone = product(3, price=5.0, availability="out_of_stock")
    assert [p.name for p in rank_products([pricey, gone, cheap])] == [
        "Product 1",
        "Product 2",
        "Product 3",
    ]
    twin_a, twin_b = product(1, name="Same"), product(2, name="Same")
    first = [str(p.url) for p in rank_products([twin_a, twin_b])]
    assert first == [str(p.url) for p in rank_products([twin_b, twin_a])]


def test_empty_and_single_pools() -> None:
    assert rank_products([]) == []
    (only,) = rank_products([product(1)])
    assert only.rank == 1 and 0 <= only.score <= 1
