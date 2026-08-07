"""
LLM category classifier -- the Tier-2 fallback used only when deterministic
name-matching finds nothing. It MUST pick verbatim from the owner's real category
list and never invent one: a wrong/invented category places the product wrongly in
live WooCommerce, so anything outside the list resolves to None (-> Manual Review).
"""
from unittest.mock import AsyncMock

import pytest

from app.builders import category_classifier as cc
from app.builders.category_classifier import CategoryChoice, llm_pick_category

CATS = ["Beauty", "Air conditioner", "Refrigerator", "Microwave Oven"]


@pytest.mark.asyncio
async def test_picks_a_valid_category_from_the_list(monkeypatch):
    monkeypatch.setattr(cc.llm_provider, "call", AsyncMock(return_value=CategoryChoice(category="Beauty")))
    result = await llm_pick_category("Deluxe Hair Straightener WF-6807", CATS)
    assert result == "Beauty"


@pytest.mark.asyncio
async def test_unknown_resolves_to_none(monkeypatch):
    monkeypatch.setattr(cc.llm_provider, "call", AsyncMock(return_value=CategoryChoice(category="UNKNOWN")))
    assert await llm_pick_category("Some mystery gadget XYZ", CATS) is None


@pytest.mark.asyncio
async def test_hallucinated_category_not_in_list_resolves_to_none(monkeypatch):
    # The model returns a plausible-but-not-allowed category -> must be rejected.
    monkeypatch.setattr(cc.llm_provider, "call", AsyncMock(return_value=CategoryChoice(category="Hair Straightener")))
    assert await llm_pick_category("Deluxe Hair Straightener WF-6807", CATS) is None


@pytest.mark.asyncio
async def test_casing_is_canonicalised_to_the_list_value(monkeypatch):
    # LLM returns "beauty"; the stored value is "Beauty" and must be returned exactly
    # (WooCommerce casing lock is byte-exact downstream).
    monkeypatch.setattr(cc.llm_provider, "call", AsyncMock(return_value=CategoryChoice(category="beauty")))
    assert await llm_pick_category("Hair Straightener", CATS) == "Beauty"


@pytest.mark.asyncio
async def test_empty_category_list_returns_none_without_calling_llm(monkeypatch):
    spy = AsyncMock()
    monkeypatch.setattr(cc.llm_provider, "call", spy)
    assert await llm_pick_category("anything", []) is None
    spy.assert_not_called()
