from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.graph.nodes import duplicate_sku_guard_node, extractor_node
from app.graph.state import PipelineState
from app.models.extraction import ExtractionResult
from app.models.failure import FailureInfo
from app.models.raw_input import RawProductInput
from app.models.taxonomy import CategorySpecSchema, SpecField


@pytest.mark.asyncio
async def test_duplicate_sku_guard_node_new():
    # Mock repository
    mock_repo = MagicMock()
    mock_repo.exists = AsyncMock(return_value=False)

    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="NEW-SKU",
            model_number="M1",
            brand_name="B1",
            category_name="C1",
            product_type="T1",
            regular_price=Decimal(100),
            sale_price=Decimal(90)
        )
    )

    with patch("app.builders.sku_guard.sku_snapshot_repo", mock_repo):
        result = await duplicate_sku_guard_node(state)

    assert not result.get("manual_review_required", False)

@pytest.mark.asyncio
async def test_duplicate_sku_guard_node_duplicate():
    mock_repo = MagicMock()
    mock_repo.exists = AsyncMock(return_value=True)

    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="EXISTING-SKU",
            model_number="M1",
            brand_name="B1",
            category_name="C1",
            product_type="T1",
            regular_price=Decimal(100),
            sale_price=Decimal(90)
        )
    )

    with patch("app.builders.sku_guard.sku_snapshot_repo", mock_repo):
        result = await duplicate_sku_guard_node(state)

    assert result["manual_review_required"] is True

@pytest.mark.asyncio
async def test_extractor_node_no_urls_proceeds_with_zero_grounding():
    """
    2026-08-09 (owner-directed): finding no source at all (nothing discovered,
    nothing operator-provided) no longer escalates -- it proceeds with an
    empty source list, and the Extractor is expected to return every field
    UNKNOWN rather than invent one. Downstream this renders "Not Available",
    it does not block the product.
    """
    now = datetime.now(UTC)
    schema = CategorySpecSchema(
        id=uuid4(), category_id=uuid4(),
        fields=[SpecField(key="capacity", label="Capacity", required=True)],
        created_at=now, updated_at=now,
    )
    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="SKU1",
            model_number="M1",
            brand_name="B1",
            category_name="C1",
            product_type="T1",
            regular_price=Decimal(100),
            sale_price=Decimal(90)
        ),
        category_schema=schema,
    )

    empty_extraction = ExtractionResult(product_id="p1", category_key="c1", citations=[])

    with patch("app.graph.nodes.scrape_product", AsyncMock(return_value={"failure": FailureInfo(category="no_reliable_source_found", detail="No reliable source found")})), \
         patch("app.graph.nodes.settings_repo.get_setting", AsyncMock(return_value=None)), \
         patch("app.graph.nodes.llm_provider.call", AsyncMock(return_value=empty_extraction)):
        result = await extractor_node(state)

    assert not result.get("manual_review_required", False)
    assert "failure" not in result
    assert result["extraction"].confirmed_value("capacity") is None


@pytest.mark.asyncio
async def test_extractor_node_routes_trusted_secondary_titles_into_the_trusted_bucket():
    """
    2026-08-10 (owner-reported, review-flagged): the actual root-cause line
    for the "Handy"/"Deluxe" missing-title bug is this filter condition --
    it was `source_type == "official"` only; widened to also include
    `trusted_secondary`. Asserted directly against extractor_node's output
    (not just against a hand-built PipelineState downstream) so a future
    accidental revert of this one-line condition is actually caught.
    """
    now = datetime.now(UTC)
    schema = CategorySpecSchema(
        id=uuid4(), category_id=uuid4(),
        fields=[SpecField(key="capacity", label="Capacity", required=True)],
        created_at=now, updated_at=now,
    )
    state = PipelineState(
        product_id=uuid4(), batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="AG-12", model_number="AG-12", brand_name="Anex",
            category_name="Food Processor", product_type="Food Processor",
            regular_price=Decimal(5000), sale_price=Decimal(4500),
        ),
        category_schema=schema,
    )
    empty_extraction = ExtractionResult(product_id="p1", category_key="c1", citations=[])
    scraped = {"scraped_data": [
        {"url": "https://anex.pk/ag-12", "source_type": "official",
         "content": "x", "candidate_titles": ["Anex AG-12 Food Processor"]},
        {"url": "https://surmawala.pk/ag-12", "source_type": "trusted_secondary",
         "content": "x", "candidate_titles": ["Anex AG-12 Handy Food Processor"]},
        {"url": "https://someblog.pk/ag-12", "source_type": "web",
         "content": "x", "candidate_titles": ["Anex AG-12 Turbo Food Processor"]},
    ]}

    with patch("app.graph.nodes.scrape_product", AsyncMock(return_value=scraped)), \
         patch("app.graph.nodes.settings_repo.get_setting", AsyncMock(return_value=None)), \
         patch("app.graph.nodes.llm_provider.call", AsyncMock(return_value=empty_extraction)):
        result = await extractor_node(state)

    assert "Anex AG-12 Handy Food Processor" in result["trusted_titles"]
    assert "Anex AG-12 Turbo Food Processor" not in result["trusted_titles"], (
        "a web source must never enter the trusted bucket"
    )
    # competitor_titles is unchanged: ALL sources, trusted or not.
    assert "Anex AG-12 Turbo Food Processor" in result["competitor_titles"]
