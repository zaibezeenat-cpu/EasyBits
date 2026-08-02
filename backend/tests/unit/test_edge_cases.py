"""
Locks the four discovery/corroboration edge cases raised 2026-07-23.

1. Copycat retailers agreeing on a wrong value must not beat the official site.
2. IPRA/IPGA model-suffix confusion must be rejected by page identity.
3. (cache invalidation is covered by test_source_scope / template re-learning.)
4. Cross-unit capacity (Cu Ft vs Litres) must fold to one value.
"""
from app.builders.fact_corroboration import normalize_value, resolve_field
from app.scraping.source_discovery import model_matches_identity


class _Cite:
    def __init__(self, field, value, url, source_type="trusted_secondary"):
        self.field_name = field
        self.value = value
        self.source_url = url
        self.source_type = source_type
        self.confidence = "confirmed"


# --- Edge 1: official overrides copycat retailer consensus -------------------

def test_official_beats_a_copycat_retailer_consensus():
    cites = [
        _Cite("capacity", "12 Cu Ft", "https://a.pk/x"),
        _Cite("capacity", "12 Cu Ft", "https://b.pk/x"),
        _Cite("capacity", "12 Cu Ft", "https://c.pk/x"),
        _Cite("capacity", "9 Cu Ft", "https://haier.com/pk/x", "official"),
    ]
    r = resolve_field("capacity", cites)
    assert r.status == "confirmed"
    assert normalize_value(r.value) == normalize_value("9 Cu Ft"), "official must win"


def test_retailer_consensus_used_when_official_is_silent():
    cites = [
        _Cite("capacity", "9 Cu Ft", "https://a.pk/x"),
        _Cite("capacity", "9 cubic feet", "https://b.pk/x"),
    ]
    r = resolve_field("capacity", cites)
    assert r.status == "corroborated"


# --- Edge 2: model-suffix (IPRA vs IPGA) -------------------------------------

def test_wrong_variant_page_is_rejected_by_identity():
    # IPRA page that cross-links IPGA in the body -- identity is IPRA.
    assert model_matches_identity(
        "HRF-316 IPGA",
        "https://x.pk/product/haier-hrf-316-ipra-red",
        ["Haier HRF-316 IPRA Red Glass Door"],
    ) is False


def test_correct_variant_page_is_accepted():
    assert model_matches_identity(
        "HRF-316 IPGA",
        "https://x.pk/product/haier-hrf-316-ipga-green",
        ["Haier HRF-316 IPGA Green"],
    ) is True


def test_title_dropping_the_family_prefix_still_matches():
    """'316 IPGA' (no HRF) must still match, but IPRA must not."""
    assert model_matches_identity("HRF-316 IPGA", "https://x.pk/p/1", ["Haier 316 IPGA Fridge"]) is True
    assert model_matches_identity("HRF-316 IPGA", "https://x.pk/p/1", ["Haier 316 IPRA Fridge"]) is False


def test_single_token_model_is_matched_whole():
    assert model_matches_identity("KLU-12B03S", "https://x.pk/product/kenwood-klu-12b03s", []) is True
    assert model_matches_identity("KLU-12B03S", "https://x.pk/product/kenwood-klu-99z00x", []) is False


# --- Edge 4: cross-unit capacity --------------------------------------------

def test_cubic_feet_and_litres_fold_together():
    assert normalize_value("12 Cu Ft") == normalize_value("340 Liters")
    assert normalize_value("9 Cu Ft") == normalize_value("246 Liters")  # Haier HRF-246


def test_two_sellers_using_different_units_corroborate():
    cites = [
        _Cite("capacity", "9 Cu Ft", "https://a.pk/x"),
        _Cite("capacity", "246 Liters", "https://b.pk/x"),
    ]
    r = resolve_field("capacity", cites)
    assert r.status == "corroborated", "same fridge in different units must agree, not conflict"


def test_genuinely_different_capacities_still_differ():
    assert normalize_value("9 Cu Ft") != normalize_value("12 Cu Ft")
    assert normalize_value("340 Liters") != normalize_value("246 Liters")
