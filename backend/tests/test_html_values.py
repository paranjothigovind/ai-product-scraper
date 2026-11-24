import pytest

from scraper.html.values import parse_availability, parse_price, slugify, to_float, to_int


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("$1,299.00", (1299.0, "USD")),
        ("£12.50", (12.5, "GBP")),
        ("1.299,00 €", (1299.0, "EUR")),
        ("12,50", (12.5, None)),
        ("1,299", (1299.0, None)),
        ("1.299.000", (1299000.0, None)),
        (49, (49.0, None)),
        ("call us", (None, None)),
        (None, (None, None)),
        (True, (None, None)),
        (float("inf"), (None, None)),
    ],
)
def test_parse_price(raw: object, expected: tuple[float | None, str | None]) -> None:
    assert parse_price(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://schema.org/InStock", "in_stock"),
        ("http://schema.org/OutOfStock", "out_of_stock"),
        ("Sold out", "out_of_stock"),
        ("Limited Availability", "in_stock"),
        ("backorder", "unknown"),
        (None, "unknown"),
    ],
)
def test_parse_availability(raw: object, expected: str) -> None:
    assert parse_availability(raw) == expected


def test_misc_helpers() -> None:
    assert slugify("Science Fiction & Fantasy!") == "science-fiction-fantasy"
    assert to_int("1,234 reviews") == 1234
    assert to_int("n/a") is None
    assert to_float("-1") == -1.0  # the sign must survive so callers can clamp
