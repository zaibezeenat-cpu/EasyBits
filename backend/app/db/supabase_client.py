from app.core.config import settings

from supabase import AsyncClient, acreate_client

_client: AsyncClient | None = None

async def get_supabase() -> AsyncClient:
    """
    Every repository in this codebase calls `await supabase.table(...).execute()`,
    which requires the ASYNC client (`acreate_client`). The sync `create_client`
    returns a plain, non-awaitable response object -- `await`ing its `.execute()`
    raises `TypeError: 'APIResponse' object can't be awaited` at the first real
    DB call, which nothing caught until this was run against a real database for
    the first time (every prior test/boot check only exercised code paths that
    never actually hit Supabase).
    """
    global _client
    if _client is None:
        _client = await acreate_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
    return _client
