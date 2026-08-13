"""
Tests for domain normalisation.

The failure this guards against is silent: a stored value that is not a bare
hostname never matches a scraped host, so the brand's official site is skipped
and the product escalates looking like it simply had no data available.
"""

import pytest
from app.core.domain_utils import InvalidDomainError, normalize_domain


@pytest.mark.parametrize(
    "raw,expected",
    [
        # The owner's brand list is a list of URLs -- this is the normal input.
        ("https://www.kenwood.com.pk/", "kenwood.com.pk"),
        ("https://kenwood.com.pk", "kenwood.com.pk"),
        ("  Haier.com.pk  ", "haier.com.pk"),
        ("WWW.GREE.COM.PK", "gree.com.pk"),
        ("orient.com.pk:443", "orient.com.pk"),
        ("https://user:pass@anex.com.pk", "anex.com.pk"),
        # Tracking params and anchors are not part of a source's identity.
        ("https://eshop.pel.com.pk/?utm_source=x", "eshop.pel.com.pk"),
        ("https://homage.pk/#top", "homage.pk"),
    ],
)
def test_operator_input_reduces_to_a_bare_host(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # DWP Home distributes both brands; the path is the only thing that
        # tells them apart. Discarding it was a real bug in an earlier version.
        ("https://dwphome.pk/ecostar", "dwphome.pk/ecostar"),
        ("https://dwphome.pk/gree", "dwphome.pk/gree"),
        # Haier's official Pakistan site is a subdirectory of the global site,
        # which carries a different lineup and different warranty terms.
        ("https://www.haier.com/pk/", "haier.com/pk"),
        ("haier.com/pk", "haier.com/pk"),
        # Trailing slash must not create a second, separately-cached scope.
        ("https://dwphome.pk/ecostar/", "dwphome.pk/ecostar"),
        ("https://dwphome.pk/ecostar/?utm_source=fb", "dwphome.pk/ecostar"),
    ],
)
def test_brand_section_path_is_preserved(raw, expected):
    assert normalize_domain(raw) == expected


def test_two_brands_on_one_host_stay_distinct():
    """The failure this guards: both collapsing to 'dwphome.pk'."""
    assert normalize_domain("https://dwphome.pk/ecostar") != normalize_domain(
        "https://dwphome.pk/gree"
    )


def test_a_path_long_enough_to_be_a_product_link_is_rejected():
    """
    A source is a brand's section, not one product. Storing a single product
    URL would pin discovery to that one item for every future product.
    """
    with pytest.raises(InvalidDomainError):
        normalize_domain("https://dwphome.pk/product/" + "x" * 130)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "not a domain",
        "kenwood",  # no TLD -- cannot match any scraped host
        "http://",
        "...",
        "-bad.com",
        "bad-.com",
        "a" * 300 + ".com",
    ],
)
def test_unusable_input_is_rejected_not_guessed(raw):
    """
    Storing a best guess would disable discovery for that brand with no visible
    symptom. Failing at entry is the only point the operator can act on it.
    """
    with pytest.raises(InvalidDomainError):
        normalize_domain(raw)


def test_long_and_multi_part_tlds_are_accepted():
    """Pakistani brands use '.com.pk'; rejecting multi-part TLDs would break most of the list."""
    assert normalize_domain("https://sub.brand.com.pk") == "sub.brand.com.pk"
