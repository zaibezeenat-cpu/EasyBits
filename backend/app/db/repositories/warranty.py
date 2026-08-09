from uuid import UUID

from app.db.supabase_client import get_supabase
from app.db.repositories._ttl_cache import TTLCache


class WarrantyRepository:
    def __init__(self):
        # See _ttl_cache.py. get_phrase runs once per Writer/Reviewer attempt
        # in writer_node -- up to 3x per product on the same brand/category
        # pair. No write path is exposed via the API today (app/api/routes/
        # warranty.py only has GET /), so the 30s TTL alone keeps this current.
        self._phrase_cache = TTLCache()

    async def list_all(self) -> list[dict]:
        db = await get_supabase()
        response = await db.table("warranty_matrix").select("*").eq("is_active", True).execute()
        return response.data

    async def get_phrase(self, brand_id: UUID, category_id: UUID | None) -> str | None:
        key = (str(brand_id), str(category_id) if category_id else None)
        hit, cached = self._phrase_cache.get(key)
        if hit:
            return cached

        phrase = await self._fetch_phrase(brand_id, category_id)
        self._phrase_cache.set(key, phrase)
        return phrase

    async def _fetch_phrase(self, brand_id: UUID, category_id: UUID | None) -> str | None:
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
