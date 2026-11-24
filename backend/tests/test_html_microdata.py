from scraper.html import extract_microdata, parse_html

BASE = "https://shop.test/list/"

CARD = """
<div itemscope itemtype="https://schema.org/Product">
  <a itemprop="url" href="/p/1"><span itemprop="name">Widget</span></a>
  <img itemprop="image" src="/img/1.jpg" alt="">
  <span itemprop="brand" itemscope itemtype="https://schema.org/Brand"><meta itemprop="name" content="Acme"></span>
  <div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
    <span itemprop="price" content="19.99">$19.99</span>
    <meta itemprop="priceCurrency" content="USD">
    <link itemprop="availability" href="https://schema.org/OutOfStock">
  </div>
  <div itemprop="aggregateRating" itemscope itemtype="https://schema.org/AggregateRating">
    <span itemprop="ratingValue">4.2</span> from <span itemprop="reviewCount">17</span> reviews
  </div>
  <span itemprop="description">  Sturdy   widget </span>
</div>
"""


def run(html: str):  # type: ignore[no-untyped-def]
    return extract_microdata(parse_html(html).root, BASE)


def test_extracts_a_product_with_nested_items() -> None:
    (p,) = run(CARD).products
    assert (p.name, str(p.url), p.brand) == ("Widget", "https://shop.test/p/1", "Acme")
    assert (p.price, p.currency, p.availability) == (19.99, "USD", "out_of_stock")
    assert (p.rating, p.review_count) == (4.2, 17)
    assert str(p.image) == "https://shop.test/img/1.jpg"
    assert p.description == "Sturdy widget"
    assert p.source == "microdata"


def test_multiple_products_on_a_listing_page() -> None:
    html = CARD + CARD.replace("/p/1", "/p/2").replace("Widget", "Gadget")
    assert [p.name for p in run(html).products] == ["Widget", "Gadget"]


def test_nested_item_properties_do_not_leak_into_the_parent() -> None:
    # The Brand's "name" must not overwrite the Product's name.
    html = """<div itemscope itemtype="http://schema.org/Product"><meta itemprop="url" content="/p">
      <span itemprop="brand" itemscope itemtype="http://schema.org/Brand"><span itemprop="name">Acme</span></span>
      <span itemprop="name">Real Name</span></div>"""
    (p,) = run(html).products
    assert (p.name, p.brand) == ("Real Name", "Acme")


def test_itemscope_without_product_type_is_ignored() -> None:
    html = '<div itemscope itemtype="https://schema.org/Organization"><span itemprop="name">Org</span></div>'
    assert run(html).products == []


def test_hidden_property_text_is_not_extracted() -> None:
    html = """<div itemscope itemtype="https://schema.org/Product"><meta itemprop="url" content="/p">
      <span itemprop="name" style="display:none">Injected</span></div>"""
    assert run(html).products == []


def test_unclosed_markup_still_parses() -> None:
    html = '<ul><li itemscope itemtype="https://schema.org/Product"><a itemprop="url" href="/a"><b itemprop="name">A<li itemscope itemtype="https://schema.org/Product"><a itemprop="url" href="/b"><b itemprop="name">B</ul>'
    assert [p.name for p in run(html).products] == ["A", "B"]


def test_microdata_breadcrumbs() -> None:
    html = """<ol itemscope itemtype="https://schema.org/BreadcrumbList">
      <li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">
        <a itemprop="item" href="/"><span itemprop="name">Home</span></a><meta itemprop="position" content="1"></li>
      <li itemprop="itemListElement" itemscope itemtype="https://schema.org/ListItem">
        <a itemprop="item" href="/books/"><span itemprop="name">Books</span></a><meta itemprop="position" content="2"></li>
    </ol>"""
    assert [c.name for c in run(html).categories] == ["Books"]
