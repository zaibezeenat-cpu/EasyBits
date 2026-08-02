"""
Tests for the internal/external link block appended to product descriptions.

These links close three Rank Math tests (Internal Links, External Links,
DoFollow External Links). URL patterns are the live site's, confirmed by the
owner -- a wrong pattern produces a 404 on every product, so they are asserted
literally rather than approximately.
"""
from app.builders.internal_links import (
    brand_url,
    build_link_block,
    category_url,
    slugify,
)


# --- URL construction -------------------------------------------------------

def test_slugify_matches_wordpress_style():
    assert slugify("Home Appliance") == "home-appliance"
    assert slugify("Air conditioner") == "air-conditioner"
    assert slugify("Kitchen Appliances") == "kitchen-appliances"
    assert slugify("Gaba National") == "gaba-national"


def test_subcategory_nests_under_its_parent():
    """Live pattern: /product-category/home-appliance/refrigerator/"""
    assert category_url("Refrigerator", "Home Appliance") == \
        "https://kiachahiye.com/product-category/home-appliance/refrigerator/"
    assert category_url("Blender", "Kitchen Appliances") == \
        "https://kiachahiye.com/product-category/kitchen-appliances/blender/"


def test_top_level_category_has_no_parent_segment():
    assert category_url("Home Appliance") == \
        "https://kiachahiye.com/product-category/home-appliance/"


def test_brand_url_matches_live_pattern():
    """Live pattern: /brand/anex/"""
    assert brand_url("Anex") == "https://kiachahiye.com/brand/anex/"
    assert brand_url("Gaba National") == "https://kiachahiye.com/brand/gaba-national/"


# --- Link block -------------------------------------------------------------

def test_block_contains_internal_and_external_links():
    html = build_link_block("Kenwood", "Air conditioner", "Home Appliance",
                            "https://kenwoodpakistan.pk")
    assert "kiachahiye.com/product-category/home-appliance/air-conditioner/" in html
    assert "kiachahiye.com/brand/kenwood/" in html
    assert "kenwoodpakistan.pk" in html


def test_external_link_is_dofollow():
    """Rank Math tests specifically for a DOFOLLOW outbound link."""
    html = build_link_block("Kenwood", "Air conditioner", "Home Appliance",
                            "https://kenwoodpakistan.pk")
    assert "nofollow" not in html


def test_official_url_path_is_preserved():
    """
    DWP hosts EcoStar and GREE as sections of one site. Stripping to the bare
    host would send every EcoStar product to GREE's landing page.
    """
    html = build_link_block("EcoStar", "Refrigerator", "Home Appliance",
                            "https://dwphome.pk/ecostar")
    assert "dwphome.pk/ecostar" in html


def test_bare_host_gets_a_scheme():
    html = build_link_block("Hanco", "Blender", "Kitchen Appliances", "hanco.pk")
    assert "https://hanco.pk" in html


def test_brand_without_an_official_site_still_gets_internal_links():
    """
    Hotline has no official site on record. It must lose only the external
    link, not the internal ones.
    """
    html = build_link_block("Hotline", "Fans", "Home Appliance", None)
    assert "kiachahiye.com/brand/hotline/" in html
    assert "kiachahiye.com/product-category/home-appliance/fans/" in html
    assert "Official brand site" not in html


def test_markup_uses_single_quotes_only():
    """CSV data-integrity rule: no double quotes anywhere in generated HTML."""
    html = build_link_block("Kenwood", "Air conditioner", "Home Appliance",
                            "https://kenwoodpakistan.pk")
    assert '"' not in html


def test_no_links_yields_empty_string_not_broken_markup():
    assert build_link_block("", "", None, None) == ""
