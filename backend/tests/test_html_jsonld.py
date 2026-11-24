import json

from scraper.html import extract_jsonld, parse_html

BASE = "https://shop.test/list/"


def run(*blocks: object, raw: list[str] | None = None, base: str | None = BASE):  # type: ignore[no-untyped-def]
    scripts = [f'<script type="application/ld+json">{json.dumps(b)}</script>' for b in blocks]
    scripts += [f'<script type="application/ld+json">{r}</script>' for r in raw or []]
    return extract_jsonld(parse_html("<body>" + "".join(scripts) + "</body>").root, base)


PRODUCT = {
    "@context": "https://schema.org",
    "@type": "Product",
    "name": "  Widget   Pro ",
    "url": "/p/widget",
    "image": ["/img/w.jpg", "/img/w2.jpg"],
    "brand": {"@type": "Brand", "name": "Acme"},
    "category": "Tools",
    "description": "<p>Great &amp; sturdy</p>",
    "offers": {
        "@type": "Offer",
        "price": "1,299.00",
        "priceCurrency": "usd",
        "availability": "https://schema.org/InStock",
    },
    "aggregateRating": {"@type": "AggregateRating", "ratingValue": "4.5", "reviewCount": "87"},
}


def test_maps_a_full_product() -> None:
    (p,) = run(PRODUCT).products
    assert str(p.url) == "https://shop.test/p/widget"
    assert (p.name, p.brand, p.category) == ("Widget Pro", "Acme", "Tools")
    assert (p.price, p.currency, p.availability) == (1299.0, "USD", "in_stock")
    assert (p.rating, p.review_count) == (4.5, 87)
    assert str(p.image) == "https://shop.test/img/w.jpg"
    assert p.description == "Great & sturdy"
    assert p.source == "jsonld"


def test_graph_arrays_and_ids() -> None:
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebSite", "name": "Shop"},
            {"@type": "Product", "name": "A", "url": "/a", "offers": {"@id": "#offer-a"}},
            {"@id": "#offer-a", "@type": "Offer", "price": 5, "priceCurrency": "EUR"},
            {"@type": ["Product", "Thing"], "name": "B", "url": "/b"},
        ],
    }
    result = run(graph, [{"@type": "Product", "name": "C", "url": "/c"}])
    by_name = {p.name: p for p in result.products}
    assert set(by_name) == {"A", "B", "C"}
    assert (by_name["A"].price, by_name["A"].currency) == (5.0, "EUR")


def test_itemlist_with_embedded_products_and_bare_urls() -> None:
    lst = {
        "@type": "ItemList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 2,
                "item": {"@type": "Product", "name": "Two", "url": "/2"},
            },
            {
                "@type": "ListItem",
                "position": 1,
                "item": {"@type": "Product", "name": "One", "url": "/1"},
            },
            {"@type": "ListItem", "position": 3, "url": "/3"},
            {"@type": "ListItem", "position": 4, "item": "/4"},
            {"@type": "ListItem", "position": 5, "name": "Five", "url": "/5"},
        ],
    }
    result = run(lst)
    assert {p.name for p in result.products} == {"One", "Two", "Five"}
    assert result.item_urls == ["https://shop.test/3", "https://shop.test/4"]


def test_offers_list_aggregate_offer_and_price_specification() -> None:
    agg = {
        "@type": "Product",
        "name": "A",
        "url": "/a",
        "offers": {"@type": "AggregateOffer", "lowPrice": "9.5", "priceCurrency": "GBP"},
    }
    spec = {
        "@type": "Product",
        "name": "B",
        "url": "/b",
        "offers": [{"@type": "Offer"}, {"priceSpecification": {"price": "7"}}],
    }
    by_name = {p.name: p for p in run(agg, spec).products}
    assert by_name["A"].price == 9.5
    assert by_name["B"].price == 7.0


def test_rating_is_rescaled_and_clamped() -> None:
    p = {
        "@type": "Product",
        "name": "A",
        "url": "/a",
        "aggregateRating": {"ratingValue": 8, "bestRating": 10, "ratingCount": 3},
    }
    (prod,) = run(p).products
    assert (prod.rating, prod.review_count) == (4.0, 3)
    p["aggregateRating"] = {"ratingValue": 99}
    assert run(p).products[0].rating == 5.0


def test_breadcrumbs_become_a_category_chain() -> None:
    bc = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://shop.test/"},
            {
                "@type": "ListItem",
                "position": 2,
                "name": "Books",
                "item": "https://shop.test/books/",
            },
            {
                "@type": "ListItem",
                "position": 3,
                "name": "Fiction",
                "item": "https://shop.test/books/fiction/",
            },
        ],
    }
    cats = run(bc).categories
    assert [(c.name, c.slug, c.parent) for c in cats] == [
        ("Books", "books", None),
        ("Fiction", "fiction", "Books"),
    ]


def test_product_page_breadcrumb_drops_the_product_itself() -> None:
    bc = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": "/"},
            {"@type": "ListItem", "position": 2, "name": "Tools", "item": "/tools/"},
            {"@type": "ListItem", "position": 3, "name": "Widget Pro"},
        ],
    }
    result = run(PRODUCT, bc)
    assert [c.name for c in result.categories] == ["Tools"]


def test_lone_product_without_url_uses_the_page_url() -> None:
    (p,) = run({"@type": "Product", "name": "Solo"}, base="https://shop.test/p/solo").products
    assert str(p.url) == "https://shop.test/p/solo"


def test_products_without_url_are_dropped_when_ambiguous() -> None:
    result = run({"@type": "Product", "name": "A"}, {"@type": "Product", "name": "B"})
    assert result.products == []
    assert result.dropped == 2


def test_related_products_and_reviews_are_not_extracted() -> None:
    p = {
        **PRODUCT,
        "isRelatedTo": {"@type": "Product", "name": "Other", "url": "/o"},
        "review": {
            "@type": "Review",
            "itemReviewed": {"@type": "Product", "name": "Self", "url": "/s"},
        },
    }
    assert [x.name for x in run(p).products] == ["Widget Pro"]


def test_product_group_is_represented_by_its_variants() -> None:
    group = {
        "@type": "ProductGroup",
        "name": "Shirt",
        "url": "/shirt",
        "hasVariant": [
            {"@type": "Product", "name": "Shirt S", "url": "/shirt?s", "offers": {"price": 10}},
            {"@type": "Product", "name": "Shirt M", "url": "/shirt?m", "offers": {"price": 11}},
        ],
    }
    assert [p.name for p in run(group).products] == ["Shirt S", "Shirt M"]


def test_tolerates_broken_and_hostile_json() -> None:
    result = run(
        PRODUCT,
        raw=[
            "{not json",
            "",
            "[" * 50_000,  # would blow json's recursion limit
            '{"@type":"Product","name":"Raw\nNewline","url":"/n"}',
            "<!-- " + json.dumps({"@type": "Product", "name": "Commented", "url": "/c"}) + " -->",
            "//<![CDATA[\n"
            + json.dumps({"@type": "Product", "name": "Cdata", "url": "/d"})
            + "\n//]]>",
        ],
    )
    assert {p.name for p in result.products} == {"Widget Pro", "Raw Newline", "Commented", "Cdata"}


def test_invalid_values_never_crash() -> None:
    weird = {
        "@type": "Product",
        "name": ["A"],
        "url": "javascript:alert(1)",
        "offers": {"price": "free", "priceCurrency": 5},
        "aggregateRating": {"ratingValue": "n/a"},
        "image": {"url": "data:image/png;base64,AAA"},
    }
    ok = {
        "@type": "Product",
        "name": "OK",
        "url": "/ok",
        "offers": {"price": -5},
        "brand": 12,
        "image": 7,
    }
    result = run(weird, ok)
    assert [p.name for p in result.products] == ["OK"]
    assert result.products[0].price is None


def test_other_script_types_are_ignored() -> None:
    html = '<script type="text/javascript">{"@type":"Product","name":"X","url":"/x"}</script>'
    assert extract_jsonld(parse_html(html).root, BASE).products == []


def test_ld_json_type_with_parameters_and_case() -> None:
    body = json.dumps({"@type": "Product", "name": "Cased", "url": "/c"})
    html = f'<script type="Application/LD+JSON; charset=utf-8">{body}</script>'
    assert [p.name for p in extract_jsonld(parse_html(html).root, BASE).products] == ["Cased"]
