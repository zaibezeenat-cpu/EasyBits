"""
Step-1 raw-capture script: the row-assembly rules that decide what the
owner actually sees in the CSV.

The scraper itself is mocked -- these prove the SELECTION and FORMATTING
logic (one source per row, never merged; trust before length; UNKNOWN
rather than blanks), which is where the earlier "messy multi-source
output" problem lived.
"""
import pytest

from scripts.scrape_raw import UNKNOWN, RawRow, _pick_best


def _doc(source_type, url, desc="", specs="", content="", images=None, price=None):
    return {
        "url": url, "source_type": source_type, "content": content,
        "candidate_titles": [], "raw_description_text": desc,
        "raw_specification_text": specs, "raw_images": images or [],
        "raw_description_images": [], "raw_price": price,
    }


def test_official_wins_over_a_longer_retailer_page():
    """Trust beats length ACROSS tiers -- a long retailer page must never
    displace the brand's own page."""
    docs = [
        _doc("trusted_secondary", "https://retailer.pk/x", desc="y" * 5000),
        _doc("official", "https://anex.pk/x", desc="short but official"),
    ]
    assert _pick_best(docs)["source_type"] == "official"


def test_an_empty_official_does_not_win_and_leave_the_row_blank():
    """The reported failure shape: official 404s/returns an empty shell.
    The next-best source that DID return something takes the row."""
    docs = [
        _doc("official", "https://anex.pk/x"),                       # nothing usable
        _doc("trusted_secondary", "https://retailer.pk/x", desc="real content here"),
    ]
    best = _pick_best(docs)
    assert best["source_type"] == "trusted_secondary"


def test_between_equal_tier_retailers_the_fuller_one_wins():
    docs = [
        _doc("trusted_secondary", "https://a.pk/x", desc="short"),
        _doc("trusted_secondary", "https://b.pk/x", desc="much longer description here"),
    ]
    assert _pick_best(docs)["url"] == "https://b.pk/x"


def test_no_usable_source_returns_none_rather_than_a_blank_winner():
    assert _pick_best([_doc("official", "https://anex.pk/x")]) is None
    assert _pick_best([]) is None


def test_specs_are_used_when_a_source_has_no_prose():
    """A page that is nothing but a spec table is still a usable source."""
    docs = [_doc("official", "https://anex.pk/x", specs="Wattage: 1500W")]
    assert _pick_best(docs) is not None


def test_missing_values_render_as_UNKNOWN_never_blank():
    """Blank cells look like a bug; UNKNOWN says the system looked and did
    not find it. Matches the sentinel specs_renderer.py already filters."""
    row = RawRow(sku="AG-1", brand="Anex", model_number="AG-1",
                 category="Vacuum Cleaner", warranty="")
    out = row.to_row(1)
    for column in ("Title", "Online Price", "Warranty", "Description Raw",
                   "Specification Raw", "Product Images", "Description Images"):
        assert out[column] == UNKNOWN, f"{column} must be UNKNOWN, not blank"


def test_images_are_pipe_joined_for_one_cell():
    row = RawRow(sku="AG-1", brand="Anex", model_number="AG-1", category="c",
                 warranty="", product_images=["https://a.pk/1.jpg", "https://a.pk/2.jpg"])
    assert out_images(row) == "https://a.pk/1.jpg | https://a.pk/2.jpg"


def out_images(row):
    return row.to_row(1)["Product Images"]


def test_every_declared_column_is_actually_written():
    """A column in the header with no value written is an empty column in
    the owner's spreadsheet."""
    from scripts.scrape_raw import COLUMNS
    row = RawRow(sku="AG-1", brand="Anex", model_number="AG-1", category="c", warranty="w")
    assert set(row.to_row(1).keys()) == set(COLUMNS)
