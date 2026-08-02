"""
Tests for the app_settings TTL cache.

app_settings is read on nearly every pipeline step; each uncached read is a
network round-trip to Supabase. These lock that the cache serves repeat reads
without hitting the DB, reflects writes immediately, and expires.
"""
import pytest

from app.db.repositories import settings as module


class _FakeQuery:
    def __init__(self, sink, value):
        self._sink = sink
        self._value = value
        self._is_write = False

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def upsert(self, row):
        self._is_write = True
        self._sink["writes"].append(row)
        return self

    async def execute(self):
        if not self._is_write:
            self._sink["reads"] += 1
        return type("R", (), {"data": [{"value": self._value}]})()


class _FakeDB:
    def __init__(self, sink, value):
        self._sink = sink
        self._value = value

    def table(self, _name):
        return _FakeQuery(self._sink, self._value)


@pytest.fixture
def repo(monkeypatch):
    sink = {"reads": 0, "writes": []}

    async def fake_get_supabase():
        return _FakeDB(sink, "priority")

    monkeypatch.setattr(module, "get_supabase", fake_get_supabase)
    r = module.SettingsRepository()
    return r, sink


@pytest.mark.asyncio
async def test_repeat_reads_hit_the_cache_not_the_db(repo):
    r, sink = repo
    assert await r.get_setting("source_mode") == "priority"
    assert await r.get_setting("source_mode") == "priority"
    assert await r.get_setting("source_mode") == "priority"
    assert sink["reads"] == 1, "only the first read should touch the DB"


@pytest.mark.asyncio
async def test_write_is_reflected_immediately_no_stale_read(repo):
    r, sink = repo
    await r.get_setting("source_mode")            # caches "priority"
    await r.update_setting("source_mode", "strict")
    assert await r.get_setting("source_mode") == "strict"
    # The read after the write must NOT have gone back to the DB for the value.
    assert sink["reads"] == 1
    assert sink["writes"] == [{"key": "source_mode", "value": "strict"}]


@pytest.mark.asyncio
async def test_cache_expires_after_ttl(repo, monkeypatch):
    r, sink = repo
    t = [1000.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: t[0])
    await r.get_setting("source_mode")
    t[0] += module._TTL_SECONDS + 1  # advance past the TTL
    await r.get_setting("source_mode")
    assert sink["reads"] == 2, "an expired entry must be refetched"


@pytest.mark.asyncio
async def test_invalidate_forces_a_refetch(repo):
    r, sink = repo
    await r.get_setting("source_mode")
    r.invalidate("source_mode")
    await r.get_setting("source_mode")
    assert sink["reads"] == 2
