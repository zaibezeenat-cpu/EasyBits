"""
Tests for harvesting series/feature terms from competitor product titles.

A term that reaches the product title is a public claim about the hardware, so
these tests are weighted toward REJECTION: the dangerous failure is a confident
title asserting a feature the product does not have.

The catalogue spans 26 categories, so the verification rule is deliberately
category-agnostic -- every word of a term must appear in the facts extraction
confirmed for that product. These tests exercise an air conditioner, a juicer,
a water dispenser and an oven to prove no category is special-cased.
"""
from app.builders.title_terms import (
    harvest_title_terms,
    select_title_features,
    verify_terms,
)

# --- Air conditioner --------------------------------------------------------

AC_TITLES = [
    "Kenwood KLU-12B03S 1 Ton Luxury Ultra Inverter Split Air Conditioner",
    "Kenwood 1.0 Ton KLU-12B03S Luxury Ultra DC Inverter AC - Best Price in Pakistan",
    "Buy Kenwood KLU-12B03S Luxury Ultra 1 Ton Inverter Air Conditioner Online",
    "Kenwood KLU-12B03S Super Deluxe Mega Offer",  # one seller's marketing only
]
AC_FACTS = {
    "capacity": "1 Ton",
    "compressor_technology": "DC Inverter T3",
    "ac_type": "Inverter Split",
    "smart_features": "UNKNOWN",
}


def _ac_terms(titles=None, facts=None, series="Luxury Ultra"):
    harvested = harvest_title_terms(
        titles if titles is not None else AC_TITLES,
        "Kenwood", "KLU-12B03S", "1 Ton", "Air Conditioner",
    )
    return verify_terms(harvested, AC_FACTS if facts is None else facts, series=series)


def test_series_name_is_harvested_and_verified():
    terms = {t.term.lower(): t for t in _ac_terms()}
    assert "luxury ultra" in terms
    assert terms["luxury ultra"].corroborated
    assert terms["luxury ultra"].verified


def test_single_seller_marketing_is_rejected_by_the_facts_gate():
    """
    2026-08-09 (owner-directed): min_frequency dropped to 1 -- one seller's
    title IS now enough to corroborate a term (`corroborated` no longer
    implies safety on its own). What still stops an unrelated retailer
    adjective from reaching the title is the UNCHANGED fact-matching gate in
    verify_terms(): "Super Deluxe"/"Mega Offer" are not confirmed specs for
    this product, so they fail verification regardless of corroboration.
    """
    for term in _ac_terms():
        if "super deluxe" in term.term.lower() or "mega offer" in term.term.lower():
            assert not term.verified


def test_listing_boilerplate_is_stripped():
    harvested = " ".join(t.term.lower() for t in _ac_terms())
    for noise in ("best price", "pakistan", "buy", "online"):
        assert noise not in harvested


def test_brand_capacity_model_and_type_are_not_returned_as_features():
    """They already occupy their own slots in the Boss Rule formula."""
    terms = {t.term.lower() for t in _ac_terms()}
    for duplicate in ("kenwood", "1 ton", "klu-12b03s", "air conditioner"):
        assert duplicate not in terms


def test_titles_for_a_different_model_are_ignored():
    terms = _ac_terms(titles=[
        "Kenwood KGP-18C01S Glory Pro 1.5 Ton Inverter Air Conditioner",
        "Kenwood KGP-18C01S Glory Pro Heat & Cool",
    ])
    assert all("glory" not in t.term.lower() for t in terms)


def test_capability_contradicting_extraction_is_rejected():
    """
    The decisive case: every seller says "Inverter", but extraction confirms a
    fixed-speed compressor. The title must NOT claim inverter.
    """
    non_inverter = {
        "capacity": "1 Ton",
        "compressor_technology": "Fixed Speed Rotary",
        "ac_type": "Split",
        "smart_features": "UNKNOWN",
    }
    inverter_terms = [t for t in _ac_terms(facts=non_inverter) if "inverter" in t.term.lower()]
    assert inverter_terms, "sellers do use the word, so it must have been harvested"

    # Not one may reach the title, whichever gate stopped it.
    assert all(not t.verified for t in inverter_terms)

    # And at least one must have been stopped specifically by the FACTS gate,
    # proving contradiction is caught rather than only low frequency.
    corroborated = [t for t in inverter_terms if t.corroborated]
    assert corroborated, "the term is common enough to clear the corroboration gate"
    assert all("not confirmed by extracted facts" in t.reason for t in corroborated)


def test_unknown_fact_cannot_justify_a_claim():
    """smart_features is UNKNOWN, so "WiFi" must be rejected however popular."""
    titles = [
        "Kenwood KLU-12B03S 1 Ton Luxury Ultra WiFi Air Conditioner",
        "Kenwood KLU-12B03S Luxury Ultra WiFi Smart Air Conditioner",
    ]
    for term in _ac_terms(titles=titles):
        if "wifi" in term.term.lower():
            assert not term.verified


# --- Other categories: the SAME rule, no special-casing ---------------------

def test_juicer_terms_are_verified_by_its_own_facts():
    titles = [
        "Dawlance DWHJ-8002 600W Hard Fruit Juicer with Stainless Steel Blades",
        "Dawlance DWHJ-8002 Hard Fruit Juicer Stainless Steel 600W",
    ]
    facts = {"motor_power": "600 Watts", "blade_material": "Stainless Steel Double Blades",
             "appliance_type": "Hard Fruit Juicer"}
    terms = {t.term.lower(): t for t in
             verify_terms(harvest_title_terms(titles, "Dawlance", "DWHJ-8002", "", "Blender"), facts)}
    stainless = [t for k, t in terms.items() if "stainless" in k]
    assert stainless and any(t.verified for t in stainless), "confirmed by blade_material"


def test_water_dispenser_terms_are_verified_by_its_own_facts():
    titles = [
        "Dawlance DBD-1034 EZ Glass Door Bottom Load Water Dispenser",
        "Dawlance DBD-1034 Glass Door Bottom Load Water Dispenser 3 Tap",
    ]
    facts = {"exterior_finish": "Glass Door", "dispenser_type": "Bottom Load"}
    terms = {t.term.lower(): t for t in
             verify_terms(harvest_title_terms(titles, "Dawlance", "DBD-1034", "", "Water Dispenser"), facts)}
    bottom_load = [t for k, t in terms.items() if "bottom load" in k]
    assert bottom_load and any(t.verified for t in bottom_load)


def test_oven_claim_not_in_its_facts_is_rejected():
    """
    "Convection" is unconfirmed for this oven. No AC-specific vocabulary is
    involved -- the same rule rejects it.
    """
    titles = [
        "Dawlance DWOT-2515 25L Convection Oven Toaster",
        "Dawlance DWOT-2515 Convection Oven Toaster 25 Litre",
    ]
    facts = {"capacity": "25 Liters", "functions": "Bake, Toast, Grill"}
    for term in verify_terms(
        harvest_title_terms(titles, "Dawlance", "DWOT-2515", "25L", "Oven Toaster"), facts
    ):
        if "convection" in term.term.lower():
            assert not term.verified, "convection is not in the confirmed functions"


def test_no_category_vocabulary_is_hardcoded():
    """
    Guard against reintroducing a per-category term list: a brand-new category
    with unfamiliar wording must still verify from its own facts alone.
    """
    titles = [
        "Anex AG-3001 Rechargeable Emergency Fan with Solar Panel",
        "Anex AG-3001 Solar Panel Rechargeable Emergency Fan",
    ]
    facts = {"power_source": "Rechargeable Solar Panel", "appliance_type": "Emergency Fan"}
    terms = {t.term.lower(): t for t in
             verify_terms(harvest_title_terms(titles, "Anex", "AG-3001", "", "Fans"), facts)}
    solar = [t for k, t in terms.items() if "solar" in k]
    assert solar and any(t.verified for t in solar), "verified purely from its own facts"


# --- Selection --------------------------------------------------------------

def test_only_verified_terms_are_selected():
    selected = select_title_features(_ac_terms())
    assert selected
    assert all("super deluxe" not in s.lower() for s in selected)


def test_selection_is_capped_so_the_title_stays_a_headline():
    assert len(select_title_features(_ac_terms(), max_terms=2)) <= 2


def test_no_titles_yields_no_features_rather_than_guesses():
    assert select_title_features(_ac_terms(titles=[])) == []


# --- Official-source terms (2026-08-09) --------------------------------------

def test_a_brand_marketing_word_from_the_official_page_reaches_the_title():
    """
    The Anex/Deluxe case: the brand's own official page titles the product
    "Anex Deluxe Chopper AG-3001", but "Deluxe" is a marketing word, not a
    spec fact -- no source states a spec called "Deluxe", and only the brand
    itself (one source) ever writes it. Before 2026-08-09 this term could
    never pass BOTH gates (2-seller corroboration, and matching a confirmed
    spec fact) -- it would be silently dropped from every title. An official
    source is now trusted outright.
    """
    facts = {"capacity": "600W", "material": "Plastic"}  # "Deluxe" nowhere in here.
    harvested = harvest_title_terms(
        titles=[],
        official_titles=["Anex Deluxe Chopper AG-3001"],
        brand="Anex", model="AG-3001", product_type="Chopper",
    )
    terms = {t.term.lower(): t for t in verify_terms(harvested, facts)}
    assert "deluxe" in terms
    assert terms["deluxe"].from_official
    assert terms["deluxe"].corroborated
    assert terms["deluxe"].verified

    selected = select_title_features(list(terms.values()))
    assert "Deluxe" in selected


def test_a_retailer_only_word_still_needs_a_confirmed_fact():
    """
    The other half of the same fix: min_frequency dropped to 1, so a SINGLE
    retailer's word is now corroborated -- but retailer wording (not
    official) still has to match a confirmed spec fact to be verified. This
    is what stops a retailer's unverified capability claim from reaching the
    title on nothing but its own say-so.
    """
    facts = {"capacity": "600W", "material": "Plastic"}
    harvested = harvest_title_terms(
        titles=["Anex Turbo Chopper AG-3001"],  # only ONE seller, not official
        brand="Anex", model="AG-3001", product_type="Chopper",
    )
    terms = {t.term.lower(): t for t in verify_terms(harvested, facts)}
    assert "turbo" in terms
    assert terms["turbo"].corroborated, "single mention is now enough to corroborate"
    assert not terms["turbo"].verified, "but it still isn't a confirmed spec fact"
