from uuid import UUID
from app.db.repositories.base import BaseRepository
from app.models.batch import Batch, BatchStatus
from app.db.supabase_client import get_supabase

class BatchesRepository(BaseRepository[Batch]):
    def __init__(self):
        super().__init__(model=Batch, table_name="batches")

    async def update_status(self, batch_id: UUID, status: str):
        await self.update(batch_id, {"status": status})

    async def create_batch(self, label: str) -> UUID:
        batch = await self.create({"label": label, "status": BatchStatus.PENDING})
        return batch.id

    async def list_recent(self, limit: int = 20) -> list[Batch]:
        db = await get_supabase()
        response = await db.table(self.table_name).select("*").order(
            "created_at", desc=True
        ).limit(limit).execute()
        return [self.model.model_validate(item) for item in response.data]

batches_repo = BatchesRepository()
