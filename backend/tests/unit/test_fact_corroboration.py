"""
Tests for cross-source corroboration.

Two things these lock:
1. The owner's request -- agreement across independent sources CONFIRMS a value.
2. The latent bug it fixes -- two sources stating the same value used to cancel
   out and the field was treated as missing.
"""
from app.builders.fact_corroboration import (
    FieldResolution,
    normalize_value,
    resolve_field,
)


class Cite:
    """Minimal duck-typed citation."""
    def __init__(self, field_name, value, source_url=None, source_type="trusted_secondary", confidence="confirmed"):
        self.field_name = field_name
        self.value = value
        self.source_url = source_url
        self.source_type = source_type
        self.confidence = confidence


# --- Normalisation ----------------------------------------------------------

def test_unit_wordings_fold_to_one_form():
    assert normalize_value("9 Cu Ft") == normalize_value("9 cubic feet")
    assert normalize_value("9 Cu Ft") == normalize_value("9 cu. ft.")
    assert normalize_value("246 Liters") == normalize_value("246 L")
    assert normalize_value("246 litres") == normalize_value("246 l")
    assert normalize_value("1.0 Ton") == normalize_value("1 ton")


def test_different_values_do_not_fold():
    assert normalize_value("9 Cu Ft") != normalize_value("12 Cu Ft")
    assert normalize_value("246 L") != normalize_value("312 L")


# --- The latent bug: agreement must CONFIRM ---------------------------------

def test_two_independent_sources_agreeing_are_corroborated_not_missing():
    """
    THE LATENT BUG. Before corroboration, two confirmed citations with the same
    value made confirmed_value() return None -> field treated as missing. Now it
    is the strongest signal.
    """
    citations = [
        Cite("capacity", "9 Cu Ft", "https://japanelectronics.pk/x"),
        Cite("capacity", "9 cubic feet", "https://surmawala.pk/y"),
    ]
    r = resolve_field("capacity", citations)
    assert r.status == "corroborated"
    assert r.is_confirmed is True
    assert r.value in ("9 Cu Ft", "9 cubic feet")
    assert len(r.supporting_domains) == 2


def test_two_pages_from_one_domain_are_not_independent():
    """Independence is per-domain: one seller repeating itself is one source."""
    citations = [
        Cite("capacity", "9 Cu Ft", "https://surmawala.pk/a"),
        Cite("capacity", "9 Cu Ft", "https://surmawala.pk/b"),
    ]
    r = resolve_field("capacity", citations)
    assert r.status == "single_source"
    assert r.is_confirmed is False


# --- Trust tiers ------------------------------------------------------------

def test_single_official_source_confirms():
    r = resolve_field("capacity", [Cite("capacity", "9 Cu Ft", "https://haier.com/pk/x", "official")])
    assert r.status == "confirmed"
    assert r.is_confirmed is True


def test_single_retailer_is_weak():
    r = resolve_field("capacity", [Cite("capacity", "9 Cu Ft", "https://surmawala.pk/x")])
    assert r.status == "single_source"
    assert r.is_confirmed is False


def test_official_outranks_a_disagreeing_retailer():
    citations = [
        Cite("capacity", "9 Cu Ft", "https://haier.com/pk/x", "official"),
        Cite("capacity", "10 Cu Ft", "https://surmawala.pk/y"),
    ]
    r = resolve_field("capacity", citations)
    assert r.status == "confirmed"
    assert normalize_value(r.value) == normalize_value("9 Cu Ft")


def test_corroborated_outranks_single_source_disagreement():
    """Two retailers agree (corroborated) vs one lone retailer -> the pair wins, no conflict."""
    citations = [
        Cite("capacity", "9 Cu Ft", "https://japanelectronics.pk/x"),
        Cite("capacity", "9 Cu Ft", "https://surmawala.pk/y"),
        Cite("capacity", "10 Cu Ft", "https://randomstore.pk/z"),
    ]
    r = resolve_field("capacity", citations)
    assert r.status == "corroborated"
    assert normalize_value(r.value) == normalize_value("9 Cu Ft")


# --- Conflicts must escalate, never guess -----------------------------------

def test_two_officials_disagreeing_is_a_conflict():
    citations = [
        Cite("capacity", "9 Cu Ft", "https://haier.com/pk/x", "official"),
        Cite("capacity", "10 Cu Ft", "https://haier.com/global/y", "official"),
    ]
    r = resolve_field("capacity", citations)
    assert r.status == "conflict"
    assert r.value is None
    assert len(r.conflicting_values) == 2


def test_two_lone_retailers_disagreeing_is_a_conflict():
    citations = [
        Cite("capacity", "9 Cu Ft", "https://a.pk/x"),
        Cite("capacity", "10 Cu Ft", "https://b.pk/y"),
    ]
    r = resolve_field("capacity", citations)
    assert r.status == "conflict"
    assert r.value is None


# --- Absence and UNKNOWN ----------------------------------------------------

def test_no_citations_is_unknown():
    assert resolve_field("capacity", []).status == "unknown"


def test_unknown_valued_citations_are_ignored():
    r = resolve_field("capacity", [Cite("capacity", "UNKNOWN", None, "official", "unreachable")])
    assert r.status == "unknown"
    assert r.value is None


def test_real_pilot_case_haier_246():
    """The exact pilot data: two retailers agree on capacity -> corroborated."""
    citations = [
        Cite("capacity", "9 Cubic Feet", "https://japanelectronics.pk/products/haier-ref-hrf-246-ipga"),
        Cite("capacity", "9 Cu Ft", "https://surmawala.pk/products/haier-hrf-246-ipga"),
        Cite("size", "246 Liters", "https://japanelectronics.pk/products/haier-ref-hrf-246-ipga"),
        Cite("size", "246 L", "https://surmawala.pk/products/haier-hrf-246-ipga"),
    ]
    cap = resolve_field("capacity", citations)
    size = resolve_field("size", citations)
    assert cap.is_confirmed and size.is_confirmed
    assert isinstance(cap, FieldResolution)
