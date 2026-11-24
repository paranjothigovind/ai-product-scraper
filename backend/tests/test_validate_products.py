from scraper.schemas.product import Product
from scraper.tools.validate_products import validate_products

BASE = "https://shop.test/list/"


def item(**kw: object) -> dict[str, object]:
    return {"name": "Widget", "url": "/p/1", "price": "$10.00", "source": "selector"} | kw


def test_resolves_urls_normalizes_price_and_infers_currency() -> None:
    result = validate_products([item(image="../img/a.png")], BASE)
    (p,) = result.valid
    assert (str(p.url), p.price, p.currency) == ("https://shop.test/p/1", 10.0, "USD")
    assert str(p.image) == "https://shop.test/img/a.png"


def test_explicit_currency_wins_and_is_uppercased() -> None:
    (p,) = validate_products([item(price="£5", currency="gbp")], BASE).valid
    assert p.currency == "GBP"


def test_drops_items_and_keeps_pydantic_style_messages() -> None:
    result = validate_products(
        [
            item(name="   "),
            item(url="javascript:x"),
            item(url=None),
            item(source="guess"),
            item(),
        ],
        BASE,
    )
    assert len(result.valid) == 1
    assert [e.errors for e in result.invalid] == [
        ["name: missing"],
        ["url: missing or not a valid http(s) URL"],
        ["url: missing or not a valid http(s) URL"],
        ["source: missing or unknown"],
    ]
    assert result.invalid[0].input["name"] == "   "


def test_collects_every_problem_on_an_item() -> None:
    (bad,) = validate_products([{"price": 1}], BASE).invalid
    assert len(bad.errors) == 3


def test_clamps_rating_normalizes_availability_and_counts() -> None:
    result = validate_products(
        [
            item(rating=9, review_count="1,234 reviews"),
            item(url="/p/2", name="B", rating="-1", availability="https://schema.org/OutOfStock"),
        ],
        BASE,
    )
    a, b = result.valid
    assert (a.rating, a.review_count) == (5.0, 1234)
    assert (b.rating, b.availability) == (0.0, "out_of_stock")


def test_dedupes_by_canonical_url_then_name_and_price() -> None:
    result = validate_products(
        [
            item(),
            item(url="/p/1?utm_source=x#frag"),  # same canonical URL
            item(url="/p/other", name="widget"),  # same name+price, different URL
            item(url="/p/3", price="$11"),  # different price: kept
        ],
        BASE,
    )
    assert [str(p.url) for p in result.valid] == ["https://shop.test/p/1", "https://shop.test/p/3"]
    assert result.duplicates == 2


def test_ids_are_derived_from_the_url_not_trusted_from_the_source() -> None:
    a = validate_products([item(id="attacker-chosen")], BASE).valid[0]
    b = validate_products([item(id="other")], BASE).valid[0]
    assert a.id == b.id != "attacker-chosen"


def test_unknown_and_malformed_fields_are_harmless() -> None:
    (p,) = validate_products(
        [item(price="free", rating=[1], brand=5, image={"x": 1}, description=None, extra="x")], BASE
    ).valid
    assert (p.price, p.rating, p.brand, p.image) == (None, None, None, None)


def test_accepts_already_valid_product_models() -> None:
    first = validate_products([item()], BASE).valid[0]
    again = validate_products([first, first])
    assert isinstance(again.valid[0], Product)
    assert len(again.valid) == 1 and again.duplicates == 1


def test_negative_and_non_finite_prices_become_none() -> None:
    result = validate_products(
        [item(price=-5), item(url="/p/2", name="B", price=float("inf"))], BASE
    )
    assert [p.price for p in result.valid] == [None, None]
