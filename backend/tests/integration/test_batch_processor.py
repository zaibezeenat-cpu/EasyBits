import pytest
from app.graph.batch_processor import BatchProcessor
from uuid import uuid4
from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_batch_processor_sequential_delay():
    batch_id = uuid4()
    mock_batch = MagicMock(id=batch_id)
    
    mock_products = [MagicMock(id=uuid4(), raw_input={}) for _ in range(2)]
    
    with patch("app.graph.batch_processor.batches_repo", AsyncMock(get=AsyncMock(return_value=mock_batch))), \
         patch("app.graph.batch_processor.products_repo", AsyncMock(get_by_batch=AsyncMock(return_value=mock_products))), \
         patch("app.graph.batch_processor.check_budget_ok", AsyncMock(return_value=True)), \
         patch("app.graph.batch_processor.pipeline.ainvoke", AsyncMock(return_value={})), \
         patch("app.graph.batch_processor.asyncio.sleep", AsyncMock()) as mock_sleep:
        
        await BatchProcessor.run_batch(batch_id)
        
        # Should sleep for each product
        assert mock_sleep.call_count == 2

@pytest.mark.asyncio
async def test_batch_processor_budget_guard_stop():
    batch_id = uuid4()
    mock_products = [MagicMock(id=uuid4(), raw_input={})]
    
    with patch("app.graph.batch_processor.batches_repo", AsyncMock()), \
         patch("app.graph.batch_processor.products_repo", AsyncMock(get_by_batch=AsyncMock(return_value=mock_products))), \
         patch("app.graph.batch_processor.check_budget_ok", AsyncMock(return_value=False)), \
         patch("app.graph.batch_processor.sse_manager.notify") as mock_notify:
        
        await BatchProcessor.run_batch(batch_id)
        
        mock_notify.assert_any_call(str(batch_id), {"event": "batch_paused", "reason": "budget_exceeded"})
