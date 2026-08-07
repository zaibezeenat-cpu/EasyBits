"""
Validation of the operator-supplied fields on RawProductInput.

existing_id lands in the CSV `ID` column, which WooCommerce reads as a numeric
product id. Two risks make strict validation non-negotiable:
  * a non-numeric / formula value ("=1+1", "abc") is CSV-formula-injection bait
    and would break the import, and
  * a malformed id that was MEANT to update a product would, if silently dropped,
    create a DUPLICATE instead -- the opposite of the operator's intent.
So a present-but-invalid existing_id must be rejected loudly, while a blank cell
normalises to "create new".
"""
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.raw_input import RawProductInput


def _raw(**overrides) -> RawProductInput:
    base = {
        "sku": "WF-6807", "model_number": "WF-6807", "brand_name": "Westpoint",
        "category_name": "AC", "product_type": "Hair Straightener",
        "regular_price": Decimal(6400), "sale_price": Decimal(6400),
    }
    base.update(overrides)
    return RawProductInput(**base)


def test_numeric_existing_id_is_accepted():
    assert _raw(existing_id="10874").existing_id == "10874"


def test_existing_id_is_stripped():
    assert _raw(existing_id="  10874 ").existing_id == "10874"


def test_blank_existing_id_becomes_none_create_new():
    assert _raw(existing_id="").existing_id is None
    assert _raw(existing_id="   ").existing_id is None
    assert _raw().existing_id is None


@pytest.mark.parametrize("bad", ["=1+1", "abc", "10,874", "-5", "0", "12a", "1.5"])
def test_malformed_existing_id_is_rejected(bad):
    with pytest.raises(ValidationError):
        _raw(existing_id=bad)
