from uuid import UUID

from app.db.supabase_client import get_supabase
from app.db.repositories._ttl_cache import TTLCache
from app.models.taxonomy import CategorySpecSchema


class TaxonomyRepository:
    def __init__(self):
        # See _ttl_cache.py. Read once at intake_triage and again in
        # extractor_node's prompt-building per product; no write path is
        # exposed via the API today, so the 30s TTL alone keeps this current.
        self._schema_cache = TTLCache()

    async def get_schema_by_category(self, category_id: UUID) -> CategorySpecSchema | None:
        key = str(category_id)
        hit, cached = self._schema_cache.get(key)
        if hit:
            return cached

        db = await get_supabase()
        response = await db.table("category_spec_schemas")\
            .select("*")\
            .eq("category_id", key)\
            .execute()

        schema = CategorySpecSchema.model_validate(response.data[0]) if response.data else None
        self._schema_cache.set(key, schema)
        return schema

taxonomy_repo = TaxonomyRepository()
