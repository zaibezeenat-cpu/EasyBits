"""
Tests for finding the product-detail link on a search-results page.

A search listing proves the product exists but rarely carries its specs, so the
orchestrator follows through to the detail page. Getting this wrong is expensive
in both directions: following the wrong link supplies confident facts about the
wrong product, while following nothing leaves the Extractor reading a results
listing.
"""
from app.scraping.playwright_client import extract_product_links

BASE = "https://shop.example.pk/search?q=Kenwood+KLU-12B03S"


def test_same_page_anchor_is_never_followed():
    """
    Regression guard for a real bug: "#MainContent" was followed as if it were
    the product page. It matched only because the SEARCH URL itself contains the
    model number, so the anchor inherited it.
    """
    html = '<a href="#MainContent">Skip to content</a>'
    assert extract_product_links(html, BASE, "KLU-12B03S") == []


def test_link_naming_the_model_is_preferred():
    html = """
      <a href="/products/generic-fan">Some Fan</a>
      <a href="/products/kenwood-klu-12b03s-1-ton">Kenwood KLU-12B03S 1 Ton AC</a>
    """
    links = extract_product_links(html, BASE, "KLU-12B03S")
    assert links[0] == "https://shop.example.pk/products/kenwood-klu-12b03s-1-ton"


def test_generic_product_links_are_a_weaker_fallback():
    html = '<a href="/products/some-other-ac">Another AC</a>'
    links = extract_product_links(html, BASE, "KLU-12B03S")
    assert links == ["https://shop.example.pk/products/some-other-ac"]


def test_offsite_links_are_never_followed():
    """Scraping must stay on the domain the operator approved."""
    html = '<a href="https://evil.example.com/products/klu-12b03s">KLU-12B03S</a>'
    assert extract_product_links(html, BASE, "KLU-12B03S") == []


def test_cart_account_and_search_links_are_excluded():
    html = """
      <a href="/cart">Cart</a>
      <a href="/account/login">Log in</a>
      <a href="/search?q=KLU-12B03S">Search again</a>
      <a href="/pages/about">About</a>
    """
    assert extract_product_links(html, BASE, "KLU-12B03S") == []


def test_image_and_pdf_links_are_excluded():
    html = '<a href="/products/klu-12b03s.jpg">image</a><a href="/manual-klu-12b03s.pdf">manual</a>'
    assert extract_product_links(html, BASE, "KLU-12B03S") == []


def test_duplicate_links_are_collapsed():
    html = """
      <a href="/products/kenwood-klu-12b03s">image link</a>
      <a href="/products/kenwood-klu-12b03s">title link</a>
    """
    assert len(extract_product_links(html, BASE, "KLU-12B03S")) == 1


def test_query_string_echo_does_not_falsely_promote_a_link():
    """
    Storefronts append the search terms to every link. Matching on the query
    string would rank an unrelated product as a STRONG match, so matching
    considers only the path and anchor text. The URL itself is returned intact.
    """
    html = """
      <a href="/products/unrelated-blender?q=Kenwood+KLU-12B03S">Blender</a>
      <a href="/products/kenwood-klu-12b03s">Kenwood KLU-12B03S</a>
    """
    links = extract_product_links(html, BASE, "KLU-12B03S")
    # The genuinely-matching product must outrank the one that merely echoes
    # the search terms in its query string.
    assert links[0] == "https://shop.example.pk/products/kenwood-klu-12b03s"
    assert "unrelated-blender" in links[1]
