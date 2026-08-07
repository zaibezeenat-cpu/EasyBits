from uuid import UUID

from app.db.supabase_client import get_supabase


class WarrantyRepository:
    async def list_all(self) -> list[dict]:
        db = await get_supabase()
        response = await db.table("warranty_matrix").select("*").eq("is_active", True).execute()
        return response.data

    async def get_phrase(self, brand_id: UUID, category_id: UUID | None) -> str | None:
        db = await get_supabase()
        query = db.table("warranty_matrix").select("warranty_phrase").eq("brand_id", str(brand_id))

        if category_id:
            # Try specific category first
            cat_resp = await query.eq("category_id", str(category_id)).eq("is_active", True).execute()
            if cat_resp.data:
                return cat_resp.data[0]["warranty_phrase"]

        # Fallback to brand-wide default (where category_id is null)
        brand_resp = await db.table("warranty_matrix").select("warranty_phrase")\
            .eq("brand_id", str(brand_id))\
            .is_("category_id", "null")\
            .eq("is_active", True).execute()

        if brand_resp.data:
            return brand_resp.data[0]["warranty_phrase"]

        return None

warranty_repo = WarrantyRepository()
