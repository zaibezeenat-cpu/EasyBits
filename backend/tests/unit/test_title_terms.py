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
    MAX_MARKETING_WORDS,
    TitleTerm,
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


# --- The marketing-word safeguard (2026-08-11, owner-directed) -------------
#
# Owner: "some keywords real combination should be perfect ... but it must be
# under safeguards as wrong should not be or we will be in trouble ... if add
# it should add relevant perfect like I add, or just skip, because wrong
# combination makes title worse for SEO."
#
# The count cap was removed so feature-rich FACT-BACKED titles can be built
# (his own "TCL ... 2 Ton T3 WiFi Smart DC Inverter Heat & Cool Split Air
# Conditioner" needs far more than two). But a trusted source's wording is
# auto-verified WITHOUT any fact check -- so lifting the cap on those too
# would let one padded retailer title dump "Deluxe Best Quality Heavy Duty
# Powerful ..." straight into the title. The two kinds of term are therefore
# capped separately: unlimited fact-backed specs, few marketing words.


def _marketing_heavy_terms():
    """A single retailer title stuffed with unverifiable marketing padding."""
    harvested = harvest_title_terms(
        titles=[],
        trusted_titles=["Anex AG-2098 Deluxe Heavy Duty Powerful Turbo Vacuum Cleaner"],
        brand="Anex", model="AG-2098", product_type="Vacuum Cleaner",
    )
    return verify_terms(harvested, {"body_material": "Plastic"})


def test_marketing_only_words_are_capped_even_with_no_overall_limit():
    selected = select_title_features(_marketing_heavy_terms(), max_terms=None)
    assert len(selected) <= 2, (
        f"a padded retailer title must not flood the product title, got {selected}"
    )


def test_fact_backed_terms_are_not_limited_by_the_marketing_cap():
    """
    The owner's feature-rich reference titles are all REAL specs, so they
    must not be squeezed out by a cap meant for marketing padding. Terms are
    built directly here (rather than harvested) so this measures ONLY the
    marketing cap -- harvesting's own overlapping-phrase dedup would
    otherwise be what limits the count, testing the wrong thing.
    """
    fact_backed = [
        TitleTerm(term=t, frequency=1, corroborated=True, verified=True, fact_backed=True)
        for t in ("DC Inverter", "Heat Cool", "Split", "WiFi Smart", "Tropical T3")
    ]
    selected = select_title_features(fact_backed, max_terms=None)
    assert len(selected) == 5, (
        f"fact-backed spec words must not be capped at the marketing limit, got {selected}"
    )


def test_marketing_words_are_capped_while_fact_backed_ones_flow_freely():
    """Both kinds in one list: every spec word survives, marketing stops at
    MAX_MARKETING_TERMS -- the exact mix a real product produces."""
    terms = [
        TitleTerm(term="Deluxe", frequency=1, corroborated=True, verified=True, fact_backed=False),
        TitleTerm(term="Heavy Duty", frequency=1, corroborated=True, verified=True, fact_backed=False),
        TitleTerm(term="Powerful Turbo", frequency=1, corroborated=True, verified=True, fact_backed=False),
        TitleTerm(term="DC Inverter", frequency=1, corroborated=True, verified=True, fact_backed=True),
        TitleTerm(term="Glass Door", frequency=1, corroborated=True, verified=True, fact_backed=True),
        TitleTerm(term="Bottom Load", frequency=1, corroborated=True, verified=True, fact_backed=True),
    ]
    selected = select_title_features(terms, max_terms=None)
    assert "Powerful Turbo" not in selected, "the 3rd marketing word must be dropped"
    for spec_word in ("DC Inverter", "Glass Door", "Bottom Load"):
        assert spec_word in selected, f"{spec_word} is a confirmed spec and must survive"


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
        trusted_titles=["Anex Deluxe Chopper AG-3001"],
        brand="Anex", model="AG-3001", product_type="Chopper",
    )
    terms = {t.term.lower(): t for t in verify_terms(harvested, facts)}
    assert "deluxe" in terms
    assert terms["deluxe"].from_trusted_source
    assert terms["deluxe"].corroborated
    assert terms["deluxe"].verified

    selected = select_title_features(list(terms.values()))
    assert "Deluxe" in selected


# --- Terms derived from the product's OWN confirmed specs (2026-08-11) -----
#
# Owner-clarified: his real title "Anex AG-2098 Deluxe 2 in 1 Vacuum Cleaner
# - 1500W" mixes two DIFFERENT kinds of word:
#   * "Deluxe"  -- found by searching how others title this model (already
#                  handled: harvested from trusted_titles).
#   * "2 in 1"  -- NOT in anyone's title. He derived it from the product's own
#                  specifications and features ("thinking and understanding
#                  the product").
# The specs are already CONFIRMED FACTS, so reading a phrase out of them is
# not invention -- it is the same no-hallucination contract the rest of the
# system runs on. Two independent gaps had to be closed for this to work.


def test_a_feature_pattern_in_the_confirmed_specs_can_reach_the_title():
    """Gap 1: harvesting only ever looked at TITLES, never at the product's
    own confirmed spec text -- so a real feature described only in the specs
    could never become a title term, however well-verified it was."""
    harvested = harvest_title_terms(
        titles=[], brand="Anex", model="AG-2098", product_type="Vacuum Cleaner",
        spec_text="2 in 1 vacuum and blower function. Plastic body.",
    )
    terms = {t.term.lower() for t in harvested}
    assert "2 in 1" in terms


def test_spec_harvesting_does_not_pull_in_arbitrary_prose():
    """
    The narrow-by-design guard: spec text is prose and its phrases arrive
    auto-verified (the specs ARE the facts), so generic n-gram harvesting
    here would let any stray fragment of a spec paragraph into a title.
    Only recognised feature patterns are taken.
    """
    harvested = harvest_title_terms(
        titles=[], brand="Anex", model="AG-2098", product_type="Vacuum Cleaner",
        spec_text="2 in 1 vacuum and blower function. Durable plastic body with copper motor.",
    )
    terms = {t.term.lower() for t in harvested}
    assert terms == {"2 in 1"}, f"only the recognised pattern may be taken, got {terms}"


def test_n_in_1_is_recognised_in_every_common_spelling():
    """"3-IN-1", "3 In 1" and "3 in 1" are the same feature and must all
    normalise to one canonical title form, so it can never reach a title
    written two different ways."""
    for spelling in ("3 in 1", "3-in-1", "3 IN 1", "3In1", "3 - in - 1"):
        harvested = harvest_title_terms(
            titles=[], brand="Anex", model="AG-2098", product_type="Vacuum Cleaner",
            spec_text=f"{spelling} multifunction unit",
        )
        assert any(t.term == "3 in 1" for t in harvested), f"{spelling!r} must be recognised"


def test_a_spec_derived_term_is_verified_without_needing_a_seller_to_repeat_it():
    """It came from this product's own confirmed facts -- requiring a seller
    to also have written it down would reject it for a reason unrelated to
    whether it is true."""
    harvested = harvest_title_terms(
        titles=[], brand="Anex", model="AG-2098", product_type="Vacuum Cleaner",
        spec_text="2 in 1 vacuum and blower function",
    )
    verified = verify_terms(harvested, {"features": "2 in 1 vacuum and blower function"})
    two_in_one = [t for t in verified if t.term.lower() == "2 in 1"]
    assert two_in_one and two_in_one[0].verified


def test_bare_digits_are_still_dropped_as_noise():
    """The narrow "N in 1" allowance must not reopen the general digit gate --
    prices, years and stray quantities must still be discarded."""
    harvested = harvest_title_terms(
        titles=[], brand="Anex", model="AG-2098", product_type="Vacuum Cleaner",
        spec_text="Rs 15000 price 2024 model 220 volts",
    )
    terms = {t.term.lower() for t in harvested}
    for noise in ("15000", "2024", "220"):
        assert noise not in terms


# --- Wattage parity with capacity (2026-08-10, review-flagged) -------------
#
# capacity is already passed into harvest_title_terms so its own words are
# stripped from harvested phrases (_tokens_to_drop) -- otherwise a
# competitor title's own capacity wording would be harvested as a bogus
# "feature". Wattage now has the identical dedicated slot in build_name(),
# so it needs the identical drop-token treatment: without this, a
# differently-formatted wattage mention on a competitor title ("700 Watts"
# vs. the confirmed "700W") survives harvesting as an ordinary feature and
# is NOT caught by build_name()'s exact-match dedup (which only catches a
# byte-identical repeat) -- reproducing the exact duplicate-title problem
# this fix exists to prevent.

def test_wattage_words_are_dropped_from_harvested_phrases_like_capacity():
    harvested = harvest_title_terms(
        titles=["Anex AG-3151 700W Deluxe Kitchen Robot"],
        brand="Anex", model="AG-3151", product_type="Kitchen Robot",
        wattage="700W",
    )
    assert all("700w" not in t.term.lower() for t in harvested)


def test_a_differently_worded_wattage_mention_is_also_dropped():
    """The real risk: same wattage, different phrasing ('700 Watts' vs the
    confirmed '700W') -- must not survive as a spurious feature term."""
    harvested = harvest_title_terms(
        titles=["Anex AG-3151 700 Watts Deluxe Kitchen Robot"],
        brand="Anex", model="AG-3151", product_type="Kitchen Robot",
        wattage="700 Watts",
    )
    assert all("watt" not in t.term.lower() for t in harvested)


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


# --- Review-flagged safeguard defects (2026-08-11) --------------------------
# All three were found by an independent adversarial review and confirmed
# against the real code before being fixed.


def test_a_spec_derived_term_survives_when_a_title_also_contains_it():
    """
    DEFECT: the longest-wins redundancy filter deleted the standalone
    "2 in 1" whenever a scraped title also carried it inside a longer phrase
    ("Deluxe 2 in 1"), cancelling the spec-derived fix in exactly the common
    case it was written for -- and the surviving compound was then classified
    as MARKETING, so it consumed the marketing budget too.
    """
    harvested = harvest_title_terms(
        titles=[], trusted_titles=["Anex AG-2098 Deluxe 2 in 1 Vacuum Cleaner"],
        brand="Anex", model="AG-2098", product_type="Vacuum Cleaner",
        spec_text="2 in 1 vacuum and blower",
    )
    terms = {t.term.lower(): t for t in harvested}
    assert "2 in 1" in terms, f"the spec-derived term must survive, got {list(terms)}"


def test_a_spec_derived_term_is_fact_backed_not_marketing():
    """It came from the confirmed specs, so it must not eat the marketing
    budget meant for unverifiable seller padding -- including when the specs
    spell it with hyphens ("3-in-1") and the canonical form does not match
    the raw spec text by substring."""
    for spelling in ("2 in 1", "2-in-1"):
        harvested = harvest_title_terms(
            titles=[], brand="Anex", model="AG-2098", product_type="Vacuum Cleaner",
            spec_text=f"{spelling} vacuum and blower",
        )
        verified = {t.term.lower(): t for t in verify_terms(harvested, {"features": spelling})}
        assert verified["2 in 1"].fact_backed, f"{spelling!r} must count as fact-backed"


def test_marketing_padding_is_capped_by_WORDS_not_by_phrase_count():
    """
    DEFECT: the cap counted PHRASES, and harvesting emits phrases up to four
    words -- so "Deluxe Heavy Duty Powerful" was one phrase, passed a cap of
    two, and put four unverifiable marketing words in the title. The owner's
    concern is words in the title, not how they were grouped.
    """
    harvested = harvest_title_terms(
        titles=[],
        trusted_titles=["Anex AG-2098 Super Turbo Jumbo Mega Deluxe Heavy Duty Powerful Vacuum Cleaner"],
        brand="Anex", model="AG-2098", product_type="Vacuum Cleaner",
    )
    selected = select_title_features(verify_terms(harvested, {"body_material": "Plastic"}))
    marketing_words = sum(len(term.split()) for term in selected)
    assert marketing_words <= MAX_MARKETING_WORDS, (
        f"{marketing_words} marketing words reached the title via {selected}"
    )


def test_a_short_term_is_not_fact_backed_by_an_accidental_substring():
    """The short-phrase fallback matched the facts blob as a raw substring,
    so "5G" was "confirmed" by "has 5gb ram". Must match on word boundaries."""
    terms = [TitleTerm(term="5G", frequency=1, corroborated=True, verified=False)]
    verified = verify_terms(terms, {"memory": "has 5gb ram"})[0]
    assert not verified.fact_backed and not verified.verified


def test_harvested_phrases_never_keep_stray_leading_punctuation():
    """
    Owner-reported (2026-08-12, live): the title contained "-2 in 1", which
    reads as negative two. Source text like "Deluxe-2 in 1" left the hyphen
    attached to the phrase, because the noise filter only strips punctuation
    when deciding IF a word is noise -- it kept the original spelling.
    """
    harvested = harvest_title_terms(
        titles=[], trusted_titles=["Anex AG-2098 Deluxe-2 in 1 Vacuum Cleaner"],
        brand="Anex", model="AG-2098", product_type="Vacuum Cleaner",
    )
    for term in harvested:
        assert not term.term.startswith("-"), f"stray leading hyphen in {term.term!r}"
        assert "-2 in 1" not in term.term, f"reads as negative two: {term.term!r}"
