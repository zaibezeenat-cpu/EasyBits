"""
The category override, mirroring the existing Brand override.

WHAT IT IS FOR
--------------
The taxonomy holds "Chopper" (electric, wattage required) and "Hand Chopper"
(hand-operated, no wattage field). Most titles now resolve themselves: the
hand-operated aliases read words like "Handy" or "Pull" that are actually in
the text, and the specificity resolver picks the narrower category.

This override covers what reading cannot. A title such as "Anex AG-01 Chopper"
contains no signal at all about how the product is operated, and no pattern
match, embedding search, or LLM reasoning can recover information that was
never in the string -- an LLM asked to decide would be relying on memorised
"knowledge" of a SKU, which is exactly the ungrounded guess this codebase
refuses everywhere else (see ExtractionResult.inferred_value and its required
exact_quote evidence).

So the operator, who can see the real product, states it: the same contract as
the existing Brand override, matched case-insensitively against live taxonomy
and rejected outright if it names a category that does not exist.
"""
from unittest.mock import AsyncMock, patch

import pytest

from scripts.bulk_run import _build_inputs

KNOWN_BRANDS = ["Anex"]
KNOWN_CATEGORIES = ["Chopper", "Hand Chopper"]
CATEGORY_PARENTS = {"Chopper": "Kitchen Appliances", "Hand Chopper": "Kitchen Appliances"}


def _row(**overrides) -> dict:
    row = {
        "SKU": "AG-01", "Name": "Handy Pull Chopper", "Brand": "Anex",
        "Sale Price": "1550", "Warranty": "2 Year Official Brand Warranty",
        "Status": "No Image Template",
    }
    row.update(overrides)
    return row


async def _run(rows: list[dict]):
    with (
        patch("scripts.bulk_run.brands_repo.get_active_names", AsyncMock(return_value=KNOWN_BRANDS)),
        patch(
            "scripts.bulk_run.categories_repo.get_active_names_and_parents",
            AsyncMock(return_value=(KNOWN_CATEGORIES, CATEGORY_PARENTS)),
        ),
    ):
        return await _build_inputs(rows)


@pytest.mark.asyncio
async def test_the_real_anex_title_now_resolves_without_any_override():
    """
    The original bug, now fixed upstream. "Handy Pull Chopper" used to resolve
    to the electric "Chopper" (wattage required -> Manual Review). The
    hand-operated aliases read "Handy"/"Pull" -- words actually in the title --
    and the specificity resolver picks the narrower category.

    The override below is now the correction path for titles that carry no such
    word at all, not the only way to get this row right.
    """
    inputs, skipped = await _run([_row()])
    assert not skipped
    assert inputs[0].category_name == "Hand Chopper"


@pytest.mark.asyncio
async def test_a_title_with_no_hand_signal_still_needs_the_override():
    """
    The override's real remit: nothing in "Anex AG-01 Chopper" says
    hand-operated, so no amount of reading can tell. It resolves to the
    electric category and only the operator can correct it.
    """
    inputs, skipped = await _run([_row(Name="Anex AG-01 Chopper")])
    assert not skipped
    assert inputs[0].category_name == "Chopper"


@pytest.mark.asyncio
async def test_a_category_column_overrides_the_deterministic_guess():
    """THE FIX. The operator states the real category; the guess never runs."""
    inputs, skipped = await _run([_row(Category="Hand Chopper")])
    assert not skipped
    assert inputs[0].category_name == "Hand Chopper"


@pytest.mark.asyncio
async def test_the_override_is_case_insensitive_but_stores_exact_taxonomy_casing():
    """Same contract as the Brand override: match loosely, store canonically."""
    inputs, skipped = await _run([_row(Category="hand chopper")])
    assert not skipped
    assert inputs[0].category_name == "Hand Chopper"


@pytest.mark.asyncio
async def test_an_unknown_category_is_rejected_not_passed_through():
    """
    vibe-proof allowlist rule: a typo'd or invented category must not reach the
    row unverified -- CategoryCasingMismatchError further downstream is a worse
    failure mode than skipping the row here with a clear reason.
    """
    inputs, skipped = await _run([_row(Category="Blender Deluxe 9000")])
    assert not inputs
    assert len(skipped) == 1
    assert "Blender Deluxe 9000" in skipped[0]
    assert "not in taxonomy" in skipped[0]


@pytest.mark.asyncio
async def test_a_blank_category_column_falls_back_to_the_deterministic_guess():
    """An empty cell is not an override -- same rule as Brand's blank handling."""
    inputs, skipped = await _run([_row(Name="Anex AG-01 Chopper", Category="  ")])
    assert not skipped
    assert inputs[0].category_name == "Chopper"
