from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.graph.nodes import intake_triage
from app.graph.state import PipelineState
from app.models.raw_input import RawProductInput


def _mock_brand(name: str) -> MagicMock:
    # NOTE: MagicMock(name=...) sets the mock's internal repr name, NOT the
    # .name attribute — it must be assigned separately after construction.
    brand = MagicMock(id=uuid4())
    brand.name = name
    return brand


@pytest.mark.asyncio
async def test_intake_triage_simple_product():
    raw_input = RawProductInput(
        sku="SKU1",
        model_number="M1",
        brand_name="B1",
        category_name="Microwave Oven",
        product_type="Microwave",
        regular_price=Decimal(100),
        sale_price=Decimal(90)
    )
    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=raw_input
    )

    mock_brand_repo = MagicMock()
    # V8.0 Production Lock: brand casing must exactly match live taxonomy, so
    # the mocked brand's .name must equal raw_input.brand_name here.
    mock_brand_repo.get_by_name_ci = AsyncMock(return_value=_mock_brand("B1"))

    mock_cat_repo = MagicMock()
    mock_cat_repo.get_by_name = AsyncMock(return_value=MagicMock(id=uuid4()))

    mock_tax_repo = MagicMock()
    mock_tax_repo.get_schema_by_category = AsyncMock(return_value=MagicMock(fields=[]))

    # We must patch where intake_triage imports them from
    with patch("app.graph.nodes.brands_repo", mock_brand_repo), \
         patch("app.graph.nodes.categories_repo", mock_cat_repo), \
         patch("app.graph.nodes.taxonomy_repo", mock_tax_repo):
        result = await intake_triage(state)

    assert result.get("manual_review_required") is False
    assert "category_schema" in result

@pytest.mark.asyncio
async def test_intake_triage_variant_detection():
    raw_input = RawProductInput(
        sku="SKU-VAR",
        model_number="Model A / Model B",
        brand_name="B1",
        category_name="Microwave Oven",
        product_type="Microwave",
        regular_price=Decimal(100),
        sale_price=Decimal(90)
    )
    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=raw_input
    )

    # Patch repos to return valid mocks so it doesn't fail on lookup
    mock_brand_repo = MagicMock()
    mock_brand_repo.get_by_name_ci = AsyncMock(return_value=_mock_brand("B1"))

    mock_cat_repo = MagicMock()
    mock_cat_repo.get_by_name = AsyncMock(return_value=MagicMock(id=uuid4()))

    mock_tax_repo = MagicMock()
    mock_tax_repo.get_schema_by_category = AsyncMock(return_value=MagicMock(fields=[]))

    with patch("app.graph.nodes.brands_repo", mock_brand_repo), \
         patch("app.graph.nodes.categories_repo", mock_cat_repo), \
         patch("app.graph.nodes.taxonomy_repo", mock_tax_repo):
        result = await intake_triage(state)

    assert result["manual_review_required"] is True
    assert result["failure"].category == "variant_shaped"

@pytest.mark.asyncio
async def test_intake_triage_brand_casing_mismatch_blocks():
    """V8.0 Production Lock: a brand casing mismatch (e.g. 'dawlance' vs the
    live taxonomy's 'DAWLANCE') must route straight to Manual Review, never
    a cosmetic auto-normalization."""
    raw_input = RawProductInput(
        sku="SKU2",
        model_number="M2",
        brand_name="dawlance",
        category_name="Microwave Oven",
        product_type="Microwave",
        regular_price=Decimal(100),
        sale_price=Decimal(90)
    )
    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=raw_input
    )

    mock_brand_repo = MagicMock()
    mock_brand_repo.get_by_name_ci = AsyncMock(return_value=_mock_brand("DAWLANCE"))

    mock_cat_repo = MagicMock()
    mock_cat_repo.get_by_name = AsyncMock(return_value=MagicMock(id=uuid4()))

    mock_tax_repo = MagicMock()
    mock_tax_repo.get_schema_by_category = AsyncMock(return_value=MagicMock(fields=[]))

    with patch("app.graph.nodes.brands_repo", mock_brand_repo), \
         patch("app.graph.nodes.categories_repo", mock_cat_repo), \
         patch("app.graph.nodes.taxonomy_repo", mock_tax_repo):
        result = await intake_triage(state)

    assert result["manual_review_required"] is True
    assert result["failure"].category == "brand_casing_mismatch"
