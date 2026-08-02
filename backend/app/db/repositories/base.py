import typing
from typing import List, Any, Type
from uuid import UUID
from pydantic import BaseModel
from app.db.supabase_client import get_supabase

T = typing.TypeVar("T", bound=BaseModel)

class BaseRepository(typing.Generic[T]):
    def __init__(self, model: Type[T], table_name: str):
        self.model = model
        self.table_name = table_name

    async def get(self, id: UUID) -> T | None:
        db = await get_supabase()
        response = await db.table(self.table_name).select("*").eq("id", str(id)).execute()
        if response.data:
            return self.model.model_validate(response.data[0])
        return None

    async def list(self, filters: dict[str, Any] = {}) -> List[T]:
        db = await get_supabase()
        query = db.table(self.table_name).select("*")
        for key, value in filters.items():
            query = query.eq(key, value)
        response = await query.execute()
        return [self.model.model_validate(item) for item in response.data]

    async def create(self, data: dict[str, Any]) -> T:
        db = await get_supabase()
        response = await db.table(self.table_name).insert(data).execute()
        return self.model.model_validate(response.data[0])

    async def create_many(self, rows: List[dict[str, Any]]) -> List[T]:
        """
        Inserts many rows in a single round-trip. Used by bulk import so a batch of
        50-100 products costs one DB call instead of one per row. An empty list is a
        no-op (PostgREST rejects an empty insert), so callers need not special-case it.
        """
        if not rows:
            return []
        db = await get_supabase()
        response = await db.table(self.table_name).insert(rows).execute()
        return [self.model.model_validate(item) for item in response.data]

    async def update(self, id: UUID, data: dict[str, Any]) -> T:
        db = await get_supabase()
        response = await db.table(self.table_name).update(data).eq("id", str(id)).execute()
        return self.model.model_validate(response.data[0])

    async def delete(self, id: UUID) -> bool:
        db = await get_supabase()
        response = await db.table(self.table_name).delete().eq("id", str(id)).execute()
        return len(response.data) > 0
