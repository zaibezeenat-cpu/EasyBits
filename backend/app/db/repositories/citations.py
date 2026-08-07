from app.db.supabase_client import get_supabase


class CitationsRepository:
    async def create_many(self, citations: list[dict]):
        if not citations:
            return
        db = await get_supabase()
        await db.table("source_citations").insert(citations).execute()

    async def get_by_product(self, product_id: str):
        db = await get_supabase()
        response = await db.table("source_citations").select("*").eq("product_id", product_id).execute()
        return response.data

citations_repo = CitationsRepository()
