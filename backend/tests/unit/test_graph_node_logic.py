"""
Tests for the LangGraph node logic in app/graph/nodes.py.

This module was the least-covered file in the backend (38%) despite containing
the decision logic that every product passes through. The tests below focus on
the branches that decide whether a product is published or held back, because
those are the ones that can put wrong data on the live store.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from app.graph import nodes, router
from app.graph.state import PipelineState
from app.models.extraction import ExtractionResult, SourceCitation
from app.models.failure import FailureInfo
from app.models.raw_input import RawProductInput
from app.models.taxonomy import CategorySpecSchema, SpecField
from datetime import datetime, timezone


# --- Fixtures ---------------------------------------------------------------

def _raw_input(**overrides) -> RawProductInput:
    base = dict(
        sku="KLU-12B03S",
        model_number="KLU-12B03S",
        brand_name="Kenwood",
        category_name="Air conditioner",
        product_type="Air conditioner",
        regular_price=Decimal("150000"),
        sale_price=Decimal("139999"),
        warranty_override="1 Year Warranty",
    )
    base.update(overrides)
    return RawProductInput(**base)


def _schema() -> CategorySpecSchema:
    now = datetime.now(timezone.utc)
    return CategorySpecSchema(
        id=uuid4(), category_id=uuid4(), created_at=now, updated_at=now,
        fields=[
            SpecField(key="capacity", label="Capacity", required=True),
            SpecField(key="features", label="Features", required=False),
        ],
    )


def _extraction(capacity_value="1 Ton", confidence="confirmed") -> ExtractionResult:
    now = datetime.now(timezone.utc)
    return ExtractionResult(
        product_id=str(uuid4()), category_key="air_conditioner",
        citations=[
            SourceCitation(field_name="capacity", value=capacity_value,
                           source_url="https://s.pk/p", source_type="official",
                           confidence=confidence, fetched_at=now),
        ],
        image_urls=[],
    )


def _state(**overrides) -> PipelineState:
    base = dict(product_id=uuid4(), batch_id=uuid4(), raw_input=_raw_input())
    base.update(overrides)
    return PipelineState(**base)


# --- intake_triage ----------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_brand_escalates_and_never_invents_one(monkeypatch):
    """An unrecognised brand would CREATE a new WooCommerce term on import."""
    async def no_brand(_n):
        return None

    # Mock BOTH lookups: intake_triage resolves the category before the brand
    # check, so leaving categories_repo live would hit the real DB (and fail in
    # CI). The assertion is purely about the unknown brand.
    monkeypatch.setattr(nodes.brands_repo, "get_by_name", no_brand)
    monkeypatch.setattr(nodes.categories_repo, "get_by_name", no_brand)
    result = await nodes.intake_triage(_state())
    assert result["manual_review_required"] is True
    assert result["failure"].category == "missing_taxonomy_match"


@pytest.mark.asyncio
async def test_brand_casing_mismatch_is_rejected(monkeypatch):
    """
    "kenwood" vs stored "Kenwood" must not silently pass: the CSV Brands value
    has to be byte-identical to the live taxonomy.
    """
    class _Brand:
        id, name = uuid4(), "Kenwood"

    class _Cat:
        id, name, parent_id = uuid4(), "Air conditioner", None

    async def brand(_n):
        return _Brand()

    async def cat(_n):
        return _Cat()

    monkeypatch.setattr(nodes.brands_repo, "get_by_name", brand)
    monkeypatch.setattr(nodes.categories_repo, "get_by_name", cat)

    result = await nodes.intake_triage(_state(raw_input=_raw_input(brand_name="kenwood")))
    assert result["failure"].category == "brand_casing_mismatch"


@pytest.mark.asyncio
async def test_missing_category_schema_escalates(monkeypatch):
    """Without a spec schema the Extractor would have to improvise fields."""
    class _Obj:
        id, name, parent_id = uuid4(), "Air conditioner", None

    class _Brand:
        id, name = uuid4(), "Kenwood"

    async def brand(_n):
        return _Brand()

    async def cat(_n):
        return _Obj()

    async def no_schema(_id):
        return None

    monkeypatch.setattr(nodes.brands_repo, "get_by_name", brand)
    monkeypatch.setattr(nodes.categories_repo, "get_by_name", cat)
    monkeypatch.setattr(nodes.taxonomy_repo, "get_schema_by_category", no_schema)

    result = await nodes.intake_triage(_state())
    assert result["failure"].category == "missing_category_schema"


# --- image_fallback ---------------------------------------------------------

@pytest.mark.asyncio
async def test_fewer_than_three_images_selects_text_template():
    """Template A has 3 image slots; fewer images must fall back to B."""
    state = _state(extraction=_extraction())
    assert (await nodes.image_fallback_node(state))["selected_template_type"] == "B"


@pytest.mark.asyncio
async def test_three_images_selects_image_template():
    extraction = _extraction()
    extraction.image_urls = ["a.jpg", "b.jpg", "c.jpg"]
    state = _state(extraction=extraction)
    assert (await nodes.image_fallback_node(state))["selected_template_type"] == "A"


# --- duplicate SKU guard ----------------------------------------------------

@pytest.mark.asyncio
async def test_duplicate_sku_is_blocked(monkeypatch):
    """
    Re-importing an existing SKU overwrites a live product. This is the single
    most destructive failure mode in the system.
    """
    async def collision(_sku):
        return True

    monkeypatch.setattr(nodes, "check_sku_collision", collision)
    result = await nodes.duplicate_sku_guard_node(_state())
    assert result["failure"].category == "sku_collision"
    assert result["manual_review_required"] is True


@pytest.mark.asyncio
async def test_unique_sku_passes(monkeypatch):
    async def no_collision(_sku):
        return False

    monkeypatch.setattr(nodes, "check_sku_collision", no_collision)
    assert await nodes.duplicate_sku_guard_node(_state()) == {}


# --- escalation -------------------------------------------------------------

@pytest.mark.asyncio
async def test_escalation_records_the_real_reason(monkeypatch):
    """A blank "Unknown error" in the queue makes review impossible."""
    captured = {}

    async def add(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(nodes.manual_review_repo, "add", add)

    state = _state(failure=FailureInfo(category="spec_conflict", detail="missing capacity"))
    result = await nodes.escalation_handler(state)

    assert result["manual_review_required"] is True
    assert captured["reason_code"] == "spec_conflict"
    assert captured["reason_detail"] == "missing capacity"


@pytest.mark.asyncio
async def test_escalation_without_a_failure_still_records_something(monkeypatch):
    captured = {}

    async def add(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(nodes.manual_review_repo, "add", add)
    await nodes.escalation_handler(_state())
    assert captured["reason_code"] == "other"


# --- routers ----------------------------------------------------------------

def test_intake_router_blocks_extraction_without_a_schema():
    """
    extractor_node dereferences category_schema.fields, so routing there without
    one crashed the whole graph and silently lost the product.
    """
    assert router.after_intake_router(_state()) == "escalation"


def test_intake_router_proceeds_when_schema_present():
    assert router.after_intake_router(_state(category_schema=_schema())) == "extractor"


def test_extractor_router_escalates_on_missing_required_field():
    state = _state(category_schema=_schema(),
                   extraction=_extraction(capacity_value="UNKNOWN", confidence="unreachable"))
    assert router.after_extractor_router(state) == "escalation"


def test_extractor_router_proceeds_when_required_fields_present():
    state = _state(category_schema=_schema(), extraction=_extraction())
    assert router.after_extractor_router(state) == "image_fallback"


@pytest.mark.parametrize("retry_count,expected", [(1, "writer"), (2, "writer"), (3, "escalation")])
def test_review_router_allows_exactly_three_attempts(retry_count, expected):
    """
    The locked spec is 3 total Writer/Reviewer attempts. An off-by-one here
    previously capped it at 2.
    """
    from app.models.review_result import ReviewResult

    state = _state(
        retry_count=retry_count,
        review_result=ReviewResult(
            passed=False, preflight_score=50, checks=[], warranty_consistent=True,
            fact_cross_check_passed=True, fact_cross_check_notes=[],
        ),
    )
    assert router.after_review_router(state) == expected


def test_review_router_proceeds_when_review_passes():
    from app.models.review_result import ReviewResult

    state = _state(
        retry_count=1,
        review_result=ReviewResult(
            passed=True, preflight_score=95, checks=[], warranty_consistent=True,
            fact_cross_check_passed=True, fact_cross_check_notes=[],
        ),
    )
    assert router.after_review_router(state) == "builders"
