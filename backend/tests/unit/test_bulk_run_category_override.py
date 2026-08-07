"""
The category override, mirroring the existing Brand override.

THE BUG THIS FIXES
-------------------
A real row: SKU "AG-01", Name "Handy Pull Chopper" (Anex's actual product page
title). The taxonomy has two separate categories -- "Chopper" (electric, wattage
required) and "Manual Chopper" (hand-operated, no wattage field at all) -- and
the title contains the word "chopper" but never "manual". Deterministic matching
(`input_adapter.infer_category`) finds exactly one pattern match ("Chopper") and
returns it confidently; the LLM fallback never runs because that path only
triggers on zero matches, not a wrong single match. The product is then
extracted against the electric Chopper schema, which requires a wattage a
hand-operated chopper does not have.

WHY THIS IS THE RIGHT FIX (not LLM disambiguation)
----------------------------------------------------
"Manual" is not present anywhere in the source title. No amount of pattern
matching, embedding search, or LLM reasoning over that string can recover
information that was never in it -- an LLM asked to guess would be relying on
its own memorized "knowledge" of a specific SKU ("AG-01"), which is exactly the
ungrounded, unverifiable guess this codebase's no-hallucination contract exists
to prevent everywhere else (see ExtractionResult.inferred_value and its
required exact_quote evidence). The operator, who can see the real product,
already has an equivalent override for Brand; Category gets the same one.
"""
from unittest.mock import AsyncMock, patch

import pytest

from scripts.bulk_run import _build_inputs

KNOWN_BRANDS = ["Anex"]
KNOWN_CATEGORIES = ["Chopper", "Manual Chopper"]
CATEGORY_PARENTS = {"Chopper": "Kitchen Appliances", "Manual Chopper": "Kitchen Appliances"}


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
async def test_without_an_override_the_bug_reproduces():
    """
    THE REGRESSION, pinned down. Without a Category column, "chopper" in the
    title deterministically (and wrongly) resolves to the electric category.
    If this ever stops reproducing, the override test below is not proving
    what it claims to.
    """
    inputs, skipped = await _run([_row()])
    assert not skipped
    assert inputs[0].category_name == "Chopper", (
        "the deterministic bug no longer reproduces -- the override test's "
        "premise has changed"
    )


@pytest.mark.asyncio
async def test_a_category_column_overrides_the_deterministic_guess():
    """THE FIX. The operator states the real category; the guess never runs."""
    inputs, skipped = await _run([_row(Category="Manual Chopper")])
    assert not skipped
    assert inputs[0].category_name == "Manual Chopper"


@pytest.mark.asyncio
async def test_the_override_is_case_insensitive_but_stores_exact_taxonomy_casing():
    """Same contract as the Brand override: match loosely, store canonically."""
    inputs, skipped = await _run([_row(Category="manual chopper")])
    assert not skipped
    assert inputs[0].category_name == "Manual Chopper"


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
    inputs, skipped = await _run([_row(Category="  ")])
    assert not skipped
    assert inputs[0].category_name == "Chopper"
