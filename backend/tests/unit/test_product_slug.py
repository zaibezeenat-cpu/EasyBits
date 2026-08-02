"""
Product slug + canonical URL.

The product TITLE can be long (Boss Rule, up to 90 chars), but Rank Math flags an
over-long URL. The slug is decoupled and kept short (model + product type), and the
FULL canonical URL is held at/under 65 characters -- the owner's locked ceiling.
"""
from app.builders.internal_links import (
    MAX_URL_LENGTH,
    build_canonical_url,
    build_product_slug,
)


def test_slug_is_model_plus_type_lowercased_hyphenated():
    slug = build_product_slug("WF-6807", "Hair Straightener", brand="WestPoint Pakistan")
    assert slug == "wf-6807-hair-straightener"


def test_canonical_url_is_within_the_65_char_ceiling():
    slug = build_product_slug("WF-6807", "Hair Straightener")
    url = build_canonical_url(slug)
    assert url == "https://kiachahiye.com/product/wf-6807-hair-straightener/"
    assert len(url) <= MAX_URL_LENGTH


def test_long_type_is_trimmed_but_model_is_kept_and_url_fits():
    slug = build_product_slug(
        "HRF-246-EPR", "Double Door No Frost Inverter Refrigerator With Water Dispenser",
    )
    url = build_canonical_url(slug)
    assert len(url) <= MAX_URL_LENGTH, f"{url} is {len(url)} chars"
    assert slug.startswith("hrf-246-epr"), "the unique model must never be trimmed away"
    assert not slug.endswith("-"), "no dangling hyphen after trimming"


def test_empty_slug_yields_empty_canonical():
    assert build_canonical_url("") == ""
