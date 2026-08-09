import time
from typing import Any, Optional


class TTLCache:
    """
    Minimal in-process TTL cache, same pattern as SettingsRepository's
    (app/db/repositories/settings.py) -- used by the taxonomy-adjacent repos
    (brands, categories, category schemas, warranty matrix, brand domain
    aliases). This data is edited by hand in the Taxonomy Manager and changes
    rarely, but is read repeatedly PER PRODUCT: intake_triage (3 calls),
    writer_node (3 calls, once per Writer/Reviewer retry -- up to 3x),
    deterministic_builders_node (3), csv_row_assembler_node (3) -- 12-18
    Supabase round-trips per product on data that cannot change mid-batch.
    Each round-trip is tens of ms; across a 10-product batch this is the
    dominant chunk of the measured ~38s startup/per-product overhead.

    Bounded staleness by design, same trade-off SettingsRepository already
    makes: a write invalidates the relevant cache immediately (see each
    repo's create/update override), so within one process a Taxonomy Manager
    edit applies on the very next read. The Docker CMD here runs a single
    uvicorn worker, so there is no other process to see a stale value.
    """

    def __init__(self, ttl_seconds: float = 30.0):
        self._ttl = ttl_seconds
        self._store: dict[Any, tuple[Any, float]] = {}

    def get(self, key: Any) -> tuple[bool, Any]:
        """Returns (hit, value). `hit` is False on a miss OR an expired entry."""
        entry = self._store.get(key)
        if entry is None:
            return False, None
        value, expires_at = entry
        if expires_at <= time.monotonic():
            self._store.pop(key, None)
            return False, None
        return True, value

    def set(self, key: Any, value: Any) -> None:
        self._store[key] = (value, time.monotonic() + self._ttl)

    def invalidate(self, key: Optional[Any] = None) -> None:
        """Drops one cached key, or everything when `key` is omitted."""
        if key is None:
            self._store.clear()
        else:
            self._store.pop(key, None)
