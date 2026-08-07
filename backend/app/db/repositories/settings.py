import time
from typing import Any

from app.db.supabase_client import get_supabase

# app_settings is read on nearly every pipeline step (trust_level, source_mode,
# search-template cache, budget). Each read is a network round-trip to Supabase
# (~20-100ms), not the 0.1ms the DB reports. Settings change rarely, so a short
# in-process TTL cache removes almost all of those round-trips.
#
# Bounded staleness by design: a write updates this cache immediately, so a
# single-worker deployment (our Docker CMD runs one uvicorn) is always
# consistent. If ever scaled to multiple workers, a peer's write is picked up
# within _TTL_SECONDS -- fine for these low-churn, non-safety-critical settings.
_TTL_SECONDS = 30.0


class SettingsRepository:
    def __init__(self):
        self.table_name = "app_settings"
        self._cache: dict[str, tuple[Any, float]] = {}

    async def get_setting(self, key: str) -> Any:
        cached = self._cache.get(key)
        if cached is not None and cached[1] > time.monotonic():
            return cached[0]

        db = await get_supabase()
        response = await db.table(self.table_name).select("value").eq("key", key).execute()
        value = response.data[0]["value"] if response.data else None
        self._cache[key] = (value, time.monotonic() + _TTL_SECONDS)
        return value

    async def update_setting(self, key: str, value: Any):
        db = await get_supabase()
        await db.table(self.table_name).upsert({"key": key, "value": value}).execute()
        # Write-through: reflect the new value immediately so the next read in
        # this process never returns the pre-write value.
        self._cache[key] = (value, time.monotonic() + _TTL_SECONDS)

    def invalidate(self, key: str | None = None) -> None:
        """Drop a cached key (or all). Exposed for tests and manual refresh."""
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)


settings_repo = SettingsRepository()
