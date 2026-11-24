from pathlib import Path

from scraper.html import parse_html, select
from scraper.html.dom import Node

FIXTURES = Path(__file__).parent / "fixtures"


def tags(node: Node) -> list[str]:
    return [c.tag for c in node.children if c.is_element]


def test_builds_tree_and_attrs() -> None:
    doc = parse_html('<div id="a" class="x y" data-k><span>hi</span></div>')
    div = next(doc.root.elements("div"))
    assert div.attrs == {"id": "a", "class": "x y", "data-k": ""}
    assert div.classes == {"x", "y"}
    assert next(doc.root.elements("span")).text_content() == "hi"


def test_first_duplicate_attribute_wins() -> None:
    doc = parse_html('<a href="/first" href="/second">x</a>')
    assert next(doc.root.elements("a")).attrs["href"] == "/first"


def test_void_elements_have_no_children() -> None:
    doc = parse_html("<p>a<br>b<img src=x>c<input name=q></p>")
    p = next(doc.root.elements("p"))
    assert tags(p) == ["br", "img", "input"]
    assert p.text_content() == "abc"


def test_self_closing_non_void_is_treated_as_empty() -> None:
    doc = parse_html("<div/><p>after</p>")
    assert tags(doc.root) == ["div", "p"]


def test_unclosed_list_items_become_siblings() -> None:
    doc = parse_html("<ul><li>one<li>two<li>three</ul>")
    ul = next(doc.root.elements("ul"))
    assert tags(ul) == ["li", "li", "li"]


def test_unclosed_paragraphs_and_blocks() -> None:
    doc = parse_html("<div><p>a<p>b<div>c</div></div>")
    div = next(doc.root.elements("div"))
    assert tags(div) == ["p", "p", "div"]


def test_table_cells_and_rows_without_end_tags() -> None:
    doc = parse_html("<table><tr><td>1<td>2<tr><td>3</table>")
    rows = list(doc.root.elements("tr"))
    assert len(rows) == 2
    assert tags(rows[0]) == ["td", "td"]


def test_nested_lists_keep_their_own_items() -> None:
    doc = parse_html("<ul><li>a<ul><li>a1<li>a2</ul><li>b</ul>")
    outer = next(doc.root.elements("ul"))
    assert tags(outer) == ["li", "li"]
    inner = next(outer.children[0].elements("ul"))
    assert tags(inner) == ["li", "li"]


def test_stray_end_tags_are_ignored_and_misnesting_recovers() -> None:
    doc = parse_html("</div><b><i>x</b>y</i><p>ok</p></span>")
    assert "ok" in next(doc.root.elements("p")).text_content()
    assert not doc.truncated


def test_end_tag_closes_unclosed_children() -> None:
    doc = parse_html("<div><span><b>x</div><p>after</p>")
    assert tags(doc.root) == ["div", "p"]


def test_comments_are_not_in_the_tree() -> None:
    doc = parse_html("<p>a<!-- secret instructions -->b</p>")
    assert "secret" not in doc.root.text_content()


def test_script_content_is_text_not_markup() -> None:
    doc = parse_html('<script>var s = "</div><b>x</b>";</script><p>after</p>')
    assert next(doc.root.elements("script")).text_content() == 'var s = "</div><b>x</b>";'
    assert [n.tag for n in doc.root.elements()] == ["script", "p"]


def test_real_world_messy_page() -> None:
    doc = parse_html((FIXTURES / "books_page.html").read_text(encoding="utf-8"))
    cards = select(doc.root, "article.product_pod")
    assert len(cards) == 2
    # Unclosed <p> and <li> tags did not swallow the second card into the first.
    assert all(len(select(c, "h3 > a")) == 1 for c in cards)
    assert not doc.truncated


def test_node_cap_truncates_instead_of_failing() -> None:
    doc = parse_html("<p>x</p>" * 1000, max_nodes=50)
    assert doc.truncated
    assert len(list(doc.root.descendants())) <= 50


def test_depth_cap_flattens_without_recursion_errors() -> None:
    doc = parse_html("<div>" * 50_000 + "deep" + "</div>" * 50_000 + "<p>tail</p>", max_depth=100)
    assert not doc.truncated
    # Descendant traversal and text extraction are iterative, so depth never blows the stack.
    assert "deep" in doc.root.text_content()
    assert next(doc.root.elements("p")).text_content() == "tail"


def test_overflowed_end_tags_do_not_close_real_ancestors() -> None:
    doc = parse_html(
        "<div id=outer>" + "<section>" * 10 + "<span>x</span></section>" * 10 + "<p>y</p>",
        max_depth=5,
    )
    outer = next(doc.root.elements("div"))
    assert next(outer.elements("p")).text_content() == "y"
