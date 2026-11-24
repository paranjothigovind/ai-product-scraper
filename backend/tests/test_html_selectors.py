import pytest

from scraper.html import SelectorError, parse_html, select, select_one

HTML = """
<div id="main" class="wrap">
  <ul class="list">
    <li class="item a" data-sku="1"><span class="price">$1</span><a href="/1">one</a></li>
    <li class="item b" data-sku="2"><span class="price">$2</span><div><span class="price">$9</span></div></li>
  </ul>
  <span class="price">outside</span>
</div>
"""


def names(selector: str) -> list[str]:
    return [n.text_content() for n in select(parse_html(HTML).root, selector)]


def test_tag_class_id_attr() -> None:
    assert len(select(parse_html(HTML).root, "li")) == 2
    assert names("li.a .price") == ["$1"]
    assert len(select(parse_html(HTML).root, "#main")) == 1
    assert len(select(parse_html(HTML).root, "[data-sku]")) == 2
    assert names("li[data-sku=2] > span") == ["$2"]
    assert names('li[data-sku="1"] span') == ["$1"]
    assert names("[data-sku='1'] span") == ["$1"]


def test_compound_requires_all_parts() -> None:
    assert len(select(parse_html(HTML).root, "li.item.a")) == 1
    assert len(select(parse_html(HTML).root, "li.item.zzz")) == 0
    assert len(select(parse_html(HTML).root, "span#main")) == 0


def test_child_vs_descendant() -> None:
    assert names("li.b > .price") == ["$2"]  # the nested $9 is not a direct child
    assert names("li.b .price") == ["$2", "$9"]
    assert names("ul.list > li > span") == ["$1", "$2"]


def test_descendant_chain_with_backtracking() -> None:
    assert names("div.wrap ul li.b div span") == ["$9"]
    assert names("div div span") == ["$9"]


def test_select_one_and_scoped_selection() -> None:
    doc = parse_html(HTML)
    card = select_one(doc.root, "li.b")
    assert card is not None
    assert [n.text_content() for n in select(card, ".price")] == ["$2", "$9"]
    assert select_one(doc.root, "table") is None


def test_tag_matching_is_case_insensitive() -> None:
    assert len(select(parse_html(HTML).root, "LI")) == 2


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "a, b",
        "a + b",
        "a ~ b",
        "a:hover",
        "*",
        "li:nth-child(2)",
        "a >",
        "> a",
        "a[",
        "[=x]",
        "a#",
        "a.",
        "x" * 501,
        " ".join(["a"] * 11),
    ],
)
def test_unsupported_or_malformed_selectors_raise(bad: str) -> None:
    with pytest.raises(SelectorError):
        select(parse_html(HTML).root, bad)


def test_deep_descendant_chains_stay_fast() -> None:
    doc = parse_html("<div>" * 200 + "<span class=t>x</span>" + "</div>" * 200)
    assert len(select(doc.root, "div div div div div div div div div span.t")) == 1
