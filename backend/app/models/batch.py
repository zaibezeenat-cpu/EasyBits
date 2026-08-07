from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BatchStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_FAILURES = "completed_with_failures"
    PAUSED_BUDGET_EXCEEDED = "paused_budget_exceeded"

class Batch(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    label: str
    status: BatchStatus = BatchStatus.PENDING
    total_products: int = 0
    succeeded_count: int = 0
    failed_count: int = 0
    manual_review_count: int = 0
    created_at: datetime
    updated_at: datetime
