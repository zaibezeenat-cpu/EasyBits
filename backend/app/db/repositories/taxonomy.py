from uuid import UUID

from app.db.supabase_client import get_supabase
from app.models.taxonomy import CategorySpecSchema


class TaxonomyRepository:
    async def get_schema_by_category(self, category_id: UUID) -> CategorySpecSchema | None:
        db = await get_supabase()
        response = await db.table("category_spec_schemas")\
            .select("*")\
            .eq("category_id", str(category_id))\
            .execute()
            
        if response.data:
            return CategorySpecSchema.model_validate(response.data[0])
        return None

taxonomy_repo = TaxonomyRepository()
