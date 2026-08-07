"""
Price handling in bulk_run's CSV path.

Two rules, both explicit operator decisions (kiachahiye.pk), not system
defaults:

1. HEADERS ARE TRUSTED HERE. Unlike the UI paste-flow (`input_adapter.
   assign_prices`, still value-based because that flow never sees a header),
   bulk_run reads a CSV with named "Regular"/"Sale" columns, so the operator's
   label is authoritative. A sheet where Sale > Regular is the operator's
   mistake to fix, not the system's to silently correct by swapping -- it is
   rejected with a clear message instead.

2. A SINGLE PRICE GETS A 20% MARKUP ANCHOR. This reverses an earlier fix in
   this same file that deleted a `reg = sale * 1.20` markup as a fabricated
   "was" price. The operator confirmed this is deliberate marketing/business
   policy, not a system-invented number, and asked for it back -- so a
   single-price row still shows a discount, in whichever direction the missing
   price falls.
"""
from decimal import Decimal

import pytest

from app.builders.input_adapter import assign_prices
from scripts.bulk_run import _resolve_prices


# --- _resolve_prices: bulk_run's header-aware, business-rule price resolution ---

def test_sale_higher_than_regular_is_rejected_not_auto_swapped():
    """
    THE HEADER-TRUST RULE. bulk_run knows which column is which -- unlike the UI
    paste-flow, it read the value from a column literally named "Sale". A sheet
    saying Regular=4000, Sale=5000 is a mistake in the sheet, and the operator
    asked for an error here, not a silent correction.
    """
    with pytest.raises(ValueError, match="Sale price.*higher than Regular"):
        _resolve_prices(Decimal("4000"), Decimal("5000"))


def test_two_valid_prices_pass_through_unchanged():
    regular, sale = _resolve_prices(Decimal("9700"), Decimal("6400"))
    assert regular == Decimal("9700")
    assert sale == Decimal("6400")


def test_equal_prices_still_mean_no_discount():
    regular, sale = _resolve_prices(Decimal("4260"), Decimal("4260"))
    assert regular == Decimal("4260")
    assert sale is None


def test_sale_only_manufactures_regular_at_20_percent_markup():
    """
    THE OPERATOR'S MARKETING RULE. Only "Sale" filled -> "Regular" is the anchor
    price, 20% above it, so the storefront always shows a discount. This is the
    exact shape of the chopper test sheet that crashed: only a Sale column.
    """
    regular, sale = _resolve_prices(None, Decimal("5000"))
    assert regular == Decimal("6000")
    assert sale == Decimal("5000")


def test_regular_only_manufactures_sale_at_20_percent_markup():
    """The mirror case: only "Regular" filled -> Sale is 20% below it."""
    regular, sale = _resolve_prices(Decimal("6000"), None)
    assert regular == Decimal("6000")
    assert sale == Decimal("5000")


def test_neither_price_resolves_to_none():
    """The caller's existing 'missing name or a price' skip depends on this."""
    assert _resolve_prices(None, None) is None


def test_a_single_price_row_builds_without_crashing():
    """
    THE ACTUAL CRASH. assign_prices() correctly returns sale_price=None for a
    single-price row -- but RawProductInput.sale_price was typed as a required
    Decimal, so building the model from that output raised a ValidationError
    before the product was ever queued. This is the shape a Hand Chopper test
    sheet with only one price column hits.
    """
    from app.models.raw_input import RawProductInput

    regular, sale = assign_prices(Decimal("4260"), Decimal("4260"))
    raw = RawProductInput(
        sku="CHOP-1", model_number="CHOP-1", brand_name="Anex",
        category_name="Chopper", product_type="Chopper",
        regular_price=regular, sale_price=sale,
    )
    assert raw.regular_price == Decimal("4260")
    assert raw.sale_price is None


def test_build_product_row_handles_no_discount():
    """The DB row (and the API route it's shared with) must not crash on None either."""
    from uuid import uuid4

    from app.api.routes.products import build_product_row
    from app.models.raw_input import RawProductInput

    raw = RawProductInput(
        sku="CHOP-1", model_number="CHOP-1", brand_name="Anex",
        category_name="Chopper", product_type="Chopper",
        regular_price=Decimal("4260"), sale_price=None,
    )
    row = build_product_row(uuid4(), raw)
    assert row["regular_price"] == 4260.0
    assert row["sale_price"] is None


def test_two_real_prices_still_produce_a_real_discount():
    """The ordinary case must be untouched: higher is regular, lower is sale."""
    regular, sale = assign_prices(Decimal("9700"), Decimal("6400"))
    assert regular == Decimal("9700")
    assert sale == Decimal("6400")


def test_column_order_is_ignored_in_favour_of_the_values():
    """
    The real sheet puts the SELLING price under "Regular Price", so the roles are
    derived from the values. Swapping the arguments must not swap the meaning.
    """
    assert assign_prices(Decimal("6400"), Decimal("9700")) == (Decimal("9700"), Decimal("6400"))


# ---------------------------------------------------------------------------
# THE INFERRED-VALUES REPORT.
#
# Deduced values ship in the CSV unmarked, because a "(based on features)" suffix
# on a live storefront reads badly to customers. With no usable admin UI, this
# terminal report is the ONLY place a human sees a deduction before upload -- so
# if it is silent, a guess ships unseen.
# ---------------------------------------------------------------------------
from types import SimpleNamespace

from scripts.bulk_run import _print_inferred_report


def _product(sku: str, citations: list[dict]):
    return SimpleNamespace(sku=sku, extraction_result={"citations": citations})


def test_a_deduced_value_is_reported_with_its_evidence(capsys):
    quote = "flexible hose, extension tube, big dust bag"
    _print_inferred_report([_product("VC-100", [
        {"field_name": "vacuum_type", "value": "Canister",
         "confidence": "inferred", "exact_quote": quote},
    ])])

    out = capsys.readouterr().out
    assert "VC-100" in out
    assert "vacuum_type" in out
    assert "Canister" in out
    assert quote in out, "the evidence must be shown, or the value cannot be judged"


def test_read_values_are_not_reported_as_guesses(capsys):
    """Only deductions belong here; listing confirmed facts would bury them."""
    _print_inferred_report([_product("VC-100", [
        {"field_name": "wattage", "value": "1200 W", "confidence": "confirmed"},
    ])])
    assert capsys.readouterr().out == ""


def test_nothing_is_printed_when_nothing_was_deduced(capsys):
    _print_inferred_report([_product("VC-100", [])])
    assert capsys.readouterr().out == ""


def test_a_product_with_no_extraction_does_not_crash_the_run(capsys):
    """The report runs at the very end -- it must never take the run down with it."""
    _print_inferred_report([SimpleNamespace(sku="VC-100", extraction_result=None)])
    assert capsys.readouterr().out == ""
