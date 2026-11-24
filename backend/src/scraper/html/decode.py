import codecs
import re

_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.I)
_BOMS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def _known(label: str | None) -> str | None:
    if not label:
        return None
    try:
        return codecs.lookup(label.strip()).name
    except LookupError:
        return None


def decode_html(raw: bytes, header_charset: str | None = None) -> str:
    """BOM first, then the HTTP header, then <meta charset>, then UTF-8. Never raises:
    undecodable bytes become U+FFFD and an unknown charset label is ignored."""
    for bom, bom_encoding in _BOMS:
        if raw.startswith(bom):
            return raw.decode(bom_encoding, errors="replace")
    meta = _META_CHARSET.search(raw[:4096])
    encoding = _known(header_charset) or _known(meta.group(1).decode("ascii") if meta else None)
    return raw.decode(encoding or "utf-8", errors="replace")
