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
