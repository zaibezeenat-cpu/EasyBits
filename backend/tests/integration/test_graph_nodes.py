import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.graph.nodes import duplicate_sku_guard_node, extractor_node
from uuid import uuid4

from app.graph.state import PipelineState
from app.models.raw_input import RawProductInput
from decimal import Decimal

from app.models.failure import FailureInfo

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
            regular_price=Decimal("100"),
            sale_price=Decimal("90")
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
            regular_price=Decimal("100"),
            sale_price=Decimal("90")
        )
    )
    
    with patch("app.builders.sku_guard.sku_snapshot_repo", mock_repo):
        result = await duplicate_sku_guard_node(state)
        
    assert result["manual_review_required"] is True

@pytest.mark.asyncio
async def test_extractor_node_no_urls():
    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=RawProductInput(
            sku="SKU1",
            model_number="M1",
            brand_name="B1",
            category_name="C1",
            product_type="T1",
            regular_price=Decimal("100"),
            sale_price=Decimal("90")
        )
    )
    
    with patch("app.graph.nodes.scrape_product", AsyncMock(return_value={"failure": FailureInfo(category="no_reliable_source_found", detail="No reliable source found")})):
        result = await extractor_node(state)
        assert result["manual_review_required"] is True
        assert result["failure"].category == "no_reliable_source_found"
