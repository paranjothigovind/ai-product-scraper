import re

from scraper.html.dom import Node
from scraper.html.schemaorg import SchemaOrgResult, map_nodes
from scraper.html.text import render_text

MAX_ITEM_DEPTH = 16
_URL_ATTR = {
    "a": "href",
    "area": "href",
    "link": "href",
    "img": "src",
    "audio": "src",
    "video": "src",
    "source": "src",
    "embed": "src",
    "iframe": "src",
    "track": "src",
    "object": "data",
    "time": "datetime",
    "data": "value",
    "meter": "value",
}


def _value(node: Node) -> str:
    # `content` is honored on any element: it is the standard way to give a machine value
    # next to display text (e.g. price="10.00" beside "$10").
    if (content := node.attrs.get("content")) is not None:
        return content.strip()
    if node.tag == "meta":
        return ""
    attr = _URL_ATTR.get(node.tag)
    if attr and (value := node.attrs.get(attr)) is not None:
        return value.strip()
    return " ".join(render_text(node, include_links=False).split())


def _type_name(node: Node) -> str | None:
    itemtype = node.attrs.get("itemtype", "").split()
    return re.split(r"[/#]", itemtype[0])[-1] if itemtype else None


def _build_item(item: Node, depth: int) -> dict[str, object]:
    out: dict[str, object] = {}
    if (type_name := _type_name(item)) is not None:
        out["@type"] = type_name
    if item_id := item.attrs.get("itemid"):
        out["@id"] = item_id
    if depth > MAX_ITEM_DEPTH:
        return out
    props: dict[str, list[object]] = {}
    stack = list(reversed(item.children))
    while stack:
        node = stack.pop()
        if not node.is_element:
            continue
        names = node.attrs.get("itemprop", "").split()
        scoped = "itemscope" in node.attrs
        if names and scoped:
            value: object = _build_item(node, depth + 1)
            for name in names:
                props.setdefault(name, []).append(value)
            continue  # the nested item owns its own descendants
        if scoped:
            continue  # a separate item that is not a property of this one
        for name in names:
            props.setdefault(name, []).append(_value(node))
        stack.extend(reversed(node.children))
    for name, values in props.items():
        out[name] = values[0] if len(values) == 1 else values
    return out


def microdata_nodes(root: Node) -> list[object]:
    """Top-level items only (those that are not another item's property); nested items are
    reachable through their parents."""
    return [
        _build_item(n, 0)
        for n in root.elements()
        if "itemscope" in n.attrs and "itemprop" not in n.attrs
    ]


def extract_microdata(root: Node, base_url: str | None = None) -> SchemaOrgResult:
    return map_nodes(microdata_nodes(root), base_url=base_url, source="microdata")
