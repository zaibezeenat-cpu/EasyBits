"""
Price handling when the input sheet supplies only one price.

The sheet often carries a single price. `bulk_run` used to manufacture the other
one: `reg = sale * 1.20`, producing a "regular price" the product was never sold
at, purely so the storefront would show a discount.

That is a fabricated fact of exactly the kind the rest of this pipeline refuses
to publish -- and unlike an invented wattage it carries legal and commercial
exposure. Fake "was" pricing is prohibited by consumer-protection rules, and
Google Merchant Center and Facebook Catalog both disapprove listings for it.

The truthful handling is already implemented in
`input_adapter.assign_prices()`: the higher value is the regular price, the
lower is the sale price, and equal values mean no discount (`sale_price=None`).
One price in therefore means one price out, with no discount shown.
"""
from decimal import Decimal

import pytest

from app.builders.input_adapter import assign_prices


def test_a_single_price_is_never_marked_up_into_a_fake_discount():
    """
    THE REGRESSION. 4260 in must not become "was 5112, now 4260".
    """
    regular, sale = assign_prices(Decimal("4260"), Decimal("4260"))

    assert regular == Decimal("4260")
    assert sale is None, "a discount was invented out of a single price"


@pytest.mark.parametrize("multiplier", ["1.20", "1.2", "1.10", "1.15"])
def test_no_markup_multiplier_survives_in_bulk_run(multiplier):
    """
    Guards the source directly: the fabrication was a literal in bulk_run, so a
    behavioural test alone would not stop someone reintroducing it.
    """
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "scripts" / "bulk_run.py"
    text = source.read_text(encoding="utf-8")

    assert f'Decimal("{multiplier}")' not in text, (
        f"bulk_run.py multiplies a price by {multiplier} -- this invents a "
        f"regular price the product was never sold at"
    )


def test_a_single_price_row_builds_without_crashing():
    """
    THE ACTUAL CRASH. assign_prices() correctly returns sale_price=None for a
    single-price row -- but RawProductInput.sale_price was typed as a required
    Decimal, so building the model from that output raised a ValidationError
    before the product was ever queued. This is the shape a Manual Chopper test
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
