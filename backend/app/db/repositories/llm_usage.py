from datetime import datetime

from app.db.supabase_client import get_supabase


class LLMUsageRepository:
    def __init__(self):
        self.table_name = "llm_usage_log"

    async def get_monthly_spend(self) -> float:
        # Start of current month
        start_of_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        
        # We sum estimated_cost_usd
        # Supabase/Postgrest doesn't have a direct sum() via RPC easily without custom function,
        # but for V1 we can fetch and sum here, or use a RPC if we had one.
        # Since I can't add RPCs easily now, I'll fetch and sum.
        # In production, a database function (RPC) would be better.
        db = await get_supabase()
        response = await db.table(self.table_name).select("estimated_cost_usd").gte("created_at", start_of_month).execute()

        total = sum(float(row["estimated_cost_usd"]) for row in response.data)
        return total

    async def log_usage(self, data: dict):
        db = await get_supabase()
        await db.table(self.table_name).insert(data).execute()

llm_usage_repo = LLMUsageRepository()
