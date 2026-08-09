
from app.db.supabase_client import get_supabase
from app.db.repositories._ttl_cache import TTLCache


class SourcesRepository:
    def __init__(self):
        # See _ttl_cache.py. get_brand_aliases costs 2 round-trips (brand
        # lookup + alias lookup) and runs once per product in
        # deterministic_builders_node. Invalidated wholesale (not by key) on
        # any brand-domain write below, since those writes are keyed by
        # brand_id, not brand_name, and are rare admin actions -- not worth a
        # second lookup just to invalidate precisely.
        self._brand_alias_cache = TTLCache()

    async def get_brand_aliases(self, brand_name: str) -> list[str]:
        hit, cached = self._brand_alias_cache.get(brand_name)
        if hit:
            return cached

        db = await get_supabase()
        # First find brand_id
        brand_resp = await db.table("brands").select("id").eq("name", brand_name).execute()
        if not brand_resp.data:
            self._brand_alias_cache.set(brand_name, [])
            return []

        brand_id = brand_resp.data[0]["id"]
        alias_resp = await db.table("brand_domain_aliases").select("official_domain").eq("brand_id", brand_id).eq("is_active", True).execute()
        result = [row["official_domain"].lower() for row in alias_resp.data]
        self._brand_alias_cache.set(brand_name, result)
        return result

    async def list_brand_domains(self) -> dict[str, str]:
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

    async def set_brand_domain(self, brand_id: str, official_domain: str) -> dict:
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
        self._brand_alias_cache.invalidate()
        return response.data[0]

    async def clear_brand_domain(self, brand_id: str) -> None:
        db = await get_supabase()
        await db.table("brand_domain_aliases").delete().eq("brand_id", brand_id).execute()
        self._brand_alias_cache.invalidate()

    async def set_trusted_secondary_source_priority(self, source_id: str, priority: int) -> dict:
        db = await get_supabase()
        response = await db.table("trusted_secondary_sources").update(
            {"priority": priority}
        ).eq("id", source_id).execute()
        if not response.data:
            raise ValueError("Source not found")
        return response.data[0]

    async def get_active_trusted_secondary_sources(self) -> list[dict]:
        db = await get_supabase()
        response = await db.table("trusted_secondary_sources").select("*").eq("is_active", True).order("priority").execute()
        return response.data

    async def list_all_trusted_secondary_sources(self) -> list[dict]:
        db = await get_supabase()
        response = await db.table("trusted_secondary_sources").select("*").order("priority").execute()
        return response.data

    async def create_trusted_secondary_source(self, domain: str, label: str, priority: int = 0) -> dict:
        db = await get_supabase()
        response = await db.table("trusted_secondary_sources").insert(
            {"domain": domain, "label": label, "priority": priority}
        ).execute()
        return response.data[0]

    async def set_trusted_secondary_source_active(self, source_id: str, is_active: bool) -> dict:
        db = await get_supabase()
        response = await db.table("trusted_secondary_sources").update(
            {"is_active": is_active}
        ).eq("id", source_id).execute()
        return response.data[0]

sources_repo = SourcesRepository()
