from decimal import Decimal
from uuid import uuid4

import pytest

from app.graph.nodes import image_fallback_node
from app.graph.state import PipelineState
from app.models.extraction import ExtractionResult
from app.models.raw_input import RawProductInput


def get_dummy_raw_input():
    return RawProductInput(
        sku="SKU1",
        model_number="M1",
        brand_name="B1",
        category_name="C1",
        product_type="T1",
        regular_price=Decimal(100),
        sale_price=Decimal(90)
    )

@pytest.mark.asyncio
async def test_image_fallback_less_than_3():
    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=get_dummy_raw_input(),
        extraction=ExtractionResult(
            product_id="123",
            category_key="CAT1",
            citations=[],
            image_urls=["img1.jpg", "img2.jpg"]
        )
    )
    result = await image_fallback_node(state)
    assert result["selected_template_type"] == "B"

@pytest.mark.asyncio
async def test_image_fallback_3_or_more():
    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=get_dummy_raw_input(),
        extraction=ExtractionResult(
            product_id="123",
            category_key="CAT1",
            citations=[],
            image_urls=["img1.jpg", "img2.jpg", "img3.jpg"]
        )
    )
    result = await image_fallback_node(state)
    assert result["selected_template_type"] == "A"

@pytest.mark.asyncio
async def test_image_fallback_zero():
    state = PipelineState(
        product_id=uuid4(),
        batch_id=uuid4(),
        raw_input=get_dummy_raw_input(),
        extraction=None
    )
    result = await image_fallback_node(state)
    assert result["selected_template_type"] == "B"
