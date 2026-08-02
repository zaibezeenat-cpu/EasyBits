from typing import List, Dict
from app.db.supabase_client import get_supabase

class SourcesRepository:
    async def get_brand_aliases(self, brand_name: str) -> List[str]:
        db = await get_supabase()
        # First find brand_id
        brand_resp = await db.table("brands").select("id").eq("name", brand_name).execute()
        if not brand_resp.data:
            return []

        brand_id = brand_resp.data[0]["id"]
        alias_resp = await db.table("brand_domain_aliases").select("official_domain").eq("brand_id", brand_id).eq("is_active", True).execute()
        return [row["official_domain"].lower() for row in alias_resp.data]

    async def list_brand_domains(self) -> Dict[str, str]:
        """
        Every brand's official domain, keyed by brand_id.

        Returned as a map rather than a list so the Taxonomy Manager can render
        one row per brand -- including brands that have no domain yet, which is
        the state that matters: with no official domain, tier 2 of source
        discovery is skipped for that brand entirely.
        """
        db = await get_supabase()
        response = await db.table("brand_domain_aliases").select(
            "brand_id, official_domain"
        ).eq("is_active", True).execute()
        return {row["brand_id"]: row["official_domain"] for row in response.data}

    async def set_brand_domain(self, brand_id: str, official_domain: str) -> Dict:
        """
        Sets (or replaces) a brand's official domain.

        Upsert on `brand_id`, which the schema declares UNIQUE: a brand has
        exactly one official site, and inserting a second row would leave
        discovery picking between them non-deterministically.
        """
        db = await get_supabase()
        response = await db.table("brand_domain_aliases").upsert(
            {"brand_id": brand_id, "official_domain": official_domain, "is_active": True},
            on_conflict="brand_id",
        ).execute()
        return response.data[0]

    async def clear_brand_domain(self, brand_id: str) -> None:
        db = await get_supabase()
        await db.table("brand_domain_aliases").delete().eq("brand_id", brand_id).execute()

    async def set_trusted_secondary_source_priority(self, source_id: str, priority: int) -> Dict:
        db = await get_supabase()
        response = await db.table("trusted_secondary_sources").update(
            {"priority": priority}
        ).eq("id", source_id).execute()
        if not response.data:
            raise ValueError("Source not found")
        return response.data[0]

    async def get_active_trusted_secondary_sources(self) -> List[Dict]:
        db = await get_supabase()
        response = await db.table("trusted_secondary_sources").select("*").eq("is_active", True).order("priority").execute()
        return response.data

    async def list_all_trusted_secondary_sources(self) -> List[Dict]:
        db = await get_supabase()
        response = await db.table("trusted_secondary_sources").select("*").order("priority").execute()
        return response.data

    async def create_trusted_secondary_source(self, domain: str, label: str, priority: int = 0) -> Dict:
        db = await get_supabase()
        response = await db.table("trusted_secondary_sources").insert(
            {"domain": domain, "label": label, "priority": priority}
        ).execute()
        return response.data[0]

    async def set_trusted_secondary_source_active(self, source_id: str, is_active: bool) -> Dict:
        db = await get_supabase()
        response = await db.table("trusted_secondary_sources").update(
            {"is_active": is_active}
        ).eq("id", source_id).execute()
        return response.data[0]

sources_repo = SourcesRepository()
