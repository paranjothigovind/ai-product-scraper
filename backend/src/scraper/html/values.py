"""Small value normalizers shared by the extractors and, later, validate_products."""

import math
import re

_SYMBOLS = {"$": "USD", "£": "GBP", "€": "EUR", "₹": "INR"}
_DECIMAL_COMMA = re.compile(r",\d{1,2}$")


def collapse_ws(text: str) -> str:
    return " ".join(text.split())


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_price(value: object) -> tuple[float | None, str | None]:
    """'$1,299.00' -> (1299.0, 'USD'); '1.299,00 €' -> (1299.0, 'EUR'); '12,50' -> (12.5, None)."""
    if isinstance(value, bool):
        return None, None
    if isinstance(value, int | float):
        return (float(value) if math.isfinite(value) else None), None
    if not isinstance(value, str):
        return None, None
    currency = next((code for sym, code in _SYMBOLS.items() if sym in value), None)
    digits = re.sub(r"[^\d.,]", "", value)
    if not re.search(r"\d", digits):
        return None, None
    last_dot, last_comma = digits.rfind("."), digits.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        decimal, thousands = (".", ",") if last_dot > last_comma else (",", ".")
        normalized = digits.replace(thousands, "").replace(decimal, ".")
    elif last_comma >= 0:
        # "12,50" is a decimal comma; "1,299" is a thousands separator.
        is_decimal = digits.count(",") == 1 and _DECIMAL_COMMA.search(digits) is not None
        normalized = digits.replace(",", ".") if is_decimal else digits.replace(",", "")
    elif digits.count(".") > 1:
        normalized = digits.replace(".", "")
    else:
        normalized = digits
    try:
        price = float(normalized)
    except ValueError:
        return None, currency
    return (price if math.isfinite(price) else None), currency


def parse_availability(value: object) -> str:
    if not isinstance(value, str):
        return "unknown"
    v = re.sub(r"[^a-z]", "", value.lower())
    if re.search(r"outofstock|soldout|unavailable|discontinued", v):
        return "out_of_stock"
    if re.search(r"instock|available|limitedavailability|onlineonly", v):
        return "in_stock"
    return "unknown"


def to_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        return float(match.group()) if match else None
    return None


def to_int(value: object) -> int | None:
    number = to_float(value)
    return None if number is None else max(0, round(number))
