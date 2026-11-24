from scraper.tools.paginate import paginate
from scraper.tools.urls import canonical_url

B = "https://shop.test/catalog/"


def test_prefers_link_rel_next() -> None:
    html = '<head><link rel="next" href="?p=9"></head><a href="/other">next</a>'
    r = paginate(html, B)
    assert (r.next_url, r.strategy) == ("https://shop.test/catalog/?p=9", "rel_next")


def test_anchor_with_rel_next_counts() -> None:
    assert paginate('<a rel="next nofollow" href="/c?x=2">more</a>', B).strategy == "rel_next"


def test_next_anchor_books_toscrape_style() -> None:
    html = '<ul class="pager"><li class="next"><a href="page-2.html">next</a></ul>'
    r = paginate(html, "https://shop.test/catalogue/page-1.html")
    assert (r.next_url, r.strategy) == ("https://shop.test/catalogue/page-2.html", "next_anchor")


def test_glyphs_and_aria_labels() -> None:
    assert paginate('<a href="/c?x=2">›</a>', B).strategy == "next_anchor"
    assert paginate('<a href="/c?x=2">Next »</a>', B).strategy == "next_anchor"
    assert paginate('<a href="/c?x=2" aria-label="Next page">→ </a>', B).strategy == "next_anchor"


def test_disabled_next_buttons_are_ignored() -> None:
    assert paginate('<li class="disabled"><a href="/c?x=2">Next</a></li>', B).next_url is None
    assert paginate('<a aria-disabled="true" href="/c?x=2">Next</a>', B).next_url is None


def test_unrelated_links_containing_next_are_not_next() -> None:
    assert paginate('<a href="/nextgen">Next generation laptops</a>', B).next_url is None


def test_increments_page_param_and_path() -> None:
    r = paginate("<p/>", "https://shop.test/c?sort=new&page=3")
    assert (r.next_url, r.strategy) == ("https://shop.test/c?page=4&sort=new", "page_param")
    r = paginate("<p/>", "https://shop.test/c/page/2/")
    assert (r.next_url, r.strategy) == ("https://shop.test/c/page/3/", "page_path")


def test_does_not_guess_from_the_first_page_unless_a_link_shows_page_two() -> None:
    assert paginate("<p>one page</p>", "https://shop.test/c").next_url is None
    r = paginate('<a href="/c?page=2">2</a>', "https://shop.test/c")
    assert (r.next_url, r.strategy) == ("https://shop.test/c?page=2", "page_param")
    r = paginate('<a href="/c/page/2/">2</a>', "https://shop.test/c/")
    assert (r.next_url, r.strategy) == ("https://shop.test/c/page/2/", "page_path")


def test_visited_urls_return_none_instead_of_a_weaker_guess() -> None:
    visited = {"https://shop.test/c?page=2"}
    html = '<link rel="next" href="/c?page=2"><a href="/other">Next</a>'
    assert paginate(html, "https://shop.test/c?page=1", visited).next_url is None


def test_never_leaves_the_host_or_uses_unsafe_schemes() -> None:
    assert paginate('<link rel="next" href="https://evil.test/c?page=2">', B).next_url is None
    assert paginate('<a href="javascript:void(0)">Next</a>', B).next_url is None


def test_self_links_are_not_next() -> None:
    assert paginate('<a href="?" rel="next">x</a>', B).next_url is None
    assert paginate(f'<a rel="next" href="{B}">x</a>', B).next_url is None


def test_survives_garbage() -> None:
    assert paginate("<<<>>>&&&", B).next_url is None
    assert paginate("<p/>", "not a url").next_url is None


def test_canonical_url() -> None:
    assert (
        canonical_url("/p?b=2&utm_source=x&a=1#top", "https://S.test:443/")
        == "https://s.test/p?a=1&b=2"
    )
    assert canonical_url("http://s.test:8080/p;jsessionid=ABC?id=1") == "http://s.test:8080/p?id=1"
    assert canonical_url("http://s.test") == "http://s.test/"
    assert canonical_url("javascript:alert(1)") is None
    assert canonical_url("file:///etc/passwd") is None
    assert canonical_url("http://[bad") is None
