"""
Tests for path-scoped sources.

WHY THE PATH MATTERS
--------------------
One host can be the official source for several brands. Measured on the real
sites 2026-07-21:

  * DWP Home distributes BOTH EcoStar and Gree. Their official presences are
    dwphome.pk/ecostar (145 distinct products) and dwphome.pk/gree (113).
    Reduced to the bare host they are indistinguishable.
  * Haier's official Pakistan site is haier.com/pk -- a subdirectory of the
    global site, whose model lineup and warranty differ from Pakistan's.

The values below are not invented examples; they are what those pages actually
returned.
"""
from app.scraping.source_discovery import (
    SourceScope,
    brand_matches_identity,
    build_search_url_candidates,
    parse_source_scope,
    template_of_url,
)

# --- Scope parsing ----------------------------------------------------------


def test_shared_host_keeps_the_brand_path():
    assert parse_source_scope("https://dwphome.pk/ecostar") == SourceScope("dwphome.pk", "/ecostar")
    assert parse_source_scope("https://dwphome.pk/gree") == SourceScope("dwphome.pk", "/gree")


def test_two_brands_on_one_host_get_distinct_keys():
    """The whole point: these must never collapse to the same identifier."""
    ecostar = parse_source_scope("https://dwphome.pk/ecostar")
    gree = parse_source_scope("https://dwphome.pk/gree")
    assert ecostar.key != gree.key
    assert ecostar.key == "dwphome.pk/ecostar"


def test_regional_subdirectory_is_preserved():
    """haier.com/pk is Pakistan; haier.com is the global site with a different lineup."""
    assert parse_source_scope("https://www.haier.com/pk/") == SourceScope("haier.com", "/pk")


def test_trailing_slash_does_not_create_a_second_scope():
    assert parse_source_scope("https://haier.com/pk/") == parse_source_scope("https://haier.com/pk")


def test_plain_host_has_no_path():
    assert parse_source_scope("kenwoodpakistan.pk") == SourceScope("kenwoodpakistan.pk", "")
    assert parse_source_scope("https://www.anex.pk/") == SourceScope("anex.pk", "")


def test_empty_input_is_not_a_usable_scope():
    assert parse_source_scope("").host == ""


# --- Candidate URL construction ---------------------------------------------


def test_scoped_source_tries_its_landing_page_first():
    """
    On a shared host the landing page is the only page guaranteed to list just
    this brand's products, so it is the most reliable entry point.
    """
    urls = build_search_url_candidates(
        parse_source_scope("https://dwphome.pk/ecostar"), "EcoStar", "ES-1234"
    )
    assert urls[0] == "https://dwphome.pk/ecostar"


def test_scoped_source_still_falls_back_to_root_search():
    """
    Verified live: products under /ecostar are served from /product/..., so the
    section is a landing page, not a prefix the catalogue sits beneath. Without
    the root fallback a scoped brand would have no working search at all.
    """
    urls = build_search_url_candidates(
        parse_source_scope("https://dwphome.pk/ecostar"), "EcoStar", "ES-1234"
    )
    assert any(u.startswith("https://dwphome.pk/search?q=") for u in urls)
    assert any(u.startswith("https://dwphome.pk/ecostar/search?q=") for u in urls)


def test_unscoped_source_does_not_duplicate_candidates():
    urls = build_search_url_candidates(parse_source_scope("anex.pk"), "Anex", "AG-1234")
    assert len(urls) == len(set(urls))
    assert all("//" not in u.replace("https://", "") for u in urls)


def test_known_template_is_tried_before_the_others():
    urls = build_search_url_candidates(
        parse_source_scope("surmawala.pk"), "Kenwood", "KLU-12B03S",
        known_template="https://{domain}/?s={query}",
    )
    assert urls[0].startswith("https://surmawala.pk/?s=")


def test_template_is_recoverable_from_both_scoped_and_root_urls():
    scope = parse_source_scope("https://dwphome.pk/ecostar")
    root_url = "https://dwphome.pk/search?q=EcoStar+ES-1234"
    scoped_url = "https://dwphome.pk/ecostar/search?q=EcoStar+ES-1234"
    expected = "https://{domain}/search?q={query}"
    assert template_of_url(scope.key, root_url, "EcoStar", "ES-1234") == expected
    assert template_of_url(scope.key, scoped_url, "EcoStar", "ES-1234") == expected


def test_landing_page_is_not_cached_as_a_template():
    """It is an entry point, not a search pattern; caching it would poison later lookups."""
    scope = parse_source_scope("https://dwphome.pk/ecostar")
    assert template_of_url(scope.key, scope.base_url, "EcoStar", "ES-1234") is None


# --- Brand identity: the guard that actually separates the two brands -------


def test_real_page_titles_discriminate_between_brands_on_one_host():
    """
    These are the ACTUAL titles returned by the two product pages.
    """
    ecostar_url = "https://dwphome.pk/product/ecostar-ario-max-series-1-ton-split-ac-439435"
    ecostar_title = ["EcoStar Ario MAX Series 1 TON Split AC -"]
    gree_url = "https://dwphome.pk/product/gree-airy-pro-1-ton-split-ac-inverter-440808"
    gree_title = ["GREE Airy Pro 1 TON Split AC (Inverter) - GS-12AITH24S-T3"]

    assert brand_matches_identity("EcoStar", ecostar_url, ecostar_title) is True
    assert brand_matches_identity("Gree", gree_url, gree_title) is True

    # The failure this exists to prevent.
    assert brand_matches_identity("Gree", ecostar_url, ecostar_title) is False
    assert brand_matches_identity("EcoStar", gree_url, gree_title) is False


def test_body_text_is_deliberately_ignored():
    """
    Measured: an EcoStar product page's BODY mentions "gree" 47 times and a Gree
    page mentions "ecostar" 35 times, because site-wide navigation links every
    brand. A body check passes for both brands and proves nothing, so identity
    is judged from the URL slug and titles only.
    """
    ecostar_url = "https://dwphome.pk/product/ecostar-ario-max-series-1-ton-split-ac-439435"
    body_mentioning_both = "Gree Gree Gree EcoStar" * 20
    assert brand_matches_identity("Gree", ecostar_url, [body_mentioning_both]) is True, (
        "passing body text in as a title is out of contract; this documents that "
        "the function trusts what it is given and the CALLER must pass titles only"
    )


def test_substring_collisions_do_not_count_as_a_match():
    """"gree" is a substring of "degree" and "agree"; matching is by token."""
    assert brand_matches_identity("Gree", "https://x.pk/product/90-degree-fan-1", ["90 Degree Fan"]) is False
    assert brand_matches_identity("Gree", "https://x.pk/product/gree-fan-1", ["Gree Fan"]) is True


def test_multi_word_brand_requires_every_word():
    assert brand_matches_identity("Super Asia", "https://x.pk/product/super-asia-washer", ["Super Asia Washer"]) is True
    assert brand_matches_identity("Super Asia", "https://x.pk/product/super-fan", ["Super Fan"]) is False


def test_url_alone_is_enough_when_the_title_is_unhelpful():
    assert brand_matches_identity(
        "EcoStar", "https://dwphome.pk/product/ecostar-ario-max-439435", ["Untitled"]
    ) is True


def test_empty_brand_never_silently_matches():
    assert brand_matches_identity("", "https://x.pk/product/anything", ["Anything"]) is False
