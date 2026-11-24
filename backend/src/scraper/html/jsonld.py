import json
import re

from scraper.html.dom import Node
from scraper.html.schemaorg import SchemaOrgResult, map_nodes

MAX_SCRIPTS = 100
MAX_SCRIPT_CHARS = 1_000_000
_LD_TYPE = re.compile(r"application/ld\+json", re.I)
_WRAPPERS = re.compile(r"^\s*(?:<!--|//\s*<!\[CDATA\[|<!\[CDATA\[)|(?:-->|//\s*\]\]>|\]\]>)\s*$")


def jsonld_nodes(root: Node) -> list[object]:
    """Parsed top-level JSON values from every ld+json script. Bad blocks are skipped."""
    values: list[object] = []
    scripts = (n for n in root.elements("script") if _LD_TYPE.search(n.attrs.get("type", "")))
    for count, script in enumerate(scripts):
        if count >= MAX_SCRIPTS:
            break
        text = script.text_content()
        if len(text) > MAX_SCRIPT_CHARS:
            continue
        cleaned = _WRAPPERS.sub("", text).strip()
        try:
            # strict=False tolerates raw newlines inside strings, which sites emit often.
            values.append(json.loads(cleaned, strict=False))
        except (ValueError, RecursionError):
            continue  # malformed or hostile JSON: skip the block, keep the page
    return values


def extract_jsonld(root: Node, base_url: str | None = None) -> SchemaOrgResult:
    return map_nodes(jsonld_nodes(root), base_url=base_url, source="jsonld")
