"""
The pooled browser: one Chromium for the run, a fresh context per fetch.

These pin the three things that make pooling safe rather than a liability. All
three were harmless under the old launch-per-call code and become real bugs the
moment the browser outlives a single fetch:

  * a context leaked on a failed load now leaks for the WHOLE batch
  * two concurrent first-time callers could each launch a browser, orphaning one
  * unbounded contexts are unbounded RAM

No real browser is started -- the Playwright API is faked, so these run in CI.
"""
import asyncio

import pytest

from app.scraping import playwright_client as pc


class _FakePage:
    def __init__(self, owner: "_FakeContext"):
        self._owner = owner

    async def goto(self, url, **kwargs):
        if self._owner.tracker.goto_hangs:
            await asyncio.sleep(0.05)
        if self._owner.tracker.goto_raises:
            raise TimeoutError("Timeout 60000ms exceeded")

    async def content(self):
        return "<html><body>WF-6807 specs</body></html>"


class _FakeContext:
    def __init__(self, tracker: "_Tracker"):
        self.tracker = tracker
        self.closed = False

    async def route(self, pattern, handler):
        self.tracker.routes_registered += 1

    async def new_page(self):
        return _FakePage(self)

    async def close(self):
        self.closed = True
        self.tracker.open_contexts -= 1


class _FakeBrowser:
    def __init__(self, tracker: "_Tracker"):
        self.tracker = tracker

    def is_connected(self):
        return True

    async def new_context(self, **kwargs):
        self.tracker.open_contexts += 1
        self.tracker.peak_contexts = max(
            self.tracker.peak_contexts, self.tracker.open_contexts
        )
        return _FakeContext(self.tracker)

    async def close(self):
        self.tracker.browser_closed = True


class _FakeChromium:
    def __init__(self, tracker: "_Tracker"):
        self.tracker = tracker

    async def launch(self, **kwargs):
        self.tracker.launches += 1
        # A real launch is slow; the await is what lets a second caller
        # interleave here and expose a missing lock.
        await asyncio.sleep(0.01)
        return _FakeBrowser(self.tracker)


class _FakeDriver:
    def __init__(self, tracker: "_Tracker"):
        self.chromium = _FakeChromium(tracker)
        self.tracker = tracker

    async def stop(self):
        self.tracker.driver_stopped = True


class _FakeAsyncPlaywright:
    def __init__(self, tracker: "_Tracker"):
        self.tracker = tracker

    async def start(self):
        return _FakeDriver(self.tracker)


class _Tracker:
    def __init__(self):
        self.launches = 0
        self.open_contexts = 0
        self.peak_contexts = 0
        self.routes_registered = 0
        self.browser_closed = False
        self.driver_stopped = False
        self.goto_raises = False
        self.goto_hangs = False


@pytest.fixture
def tracker(monkeypatch):
    """Fresh fake Playwright plus a reset of the module-level singleton."""
    t = _Tracker()
    monkeypatch.setattr(pc, "async_playwright", lambda: _FakeAsyncPlaywright(t))
    monkeypatch.setattr(pc, "_playwright", None)
    monkeypatch.setattr(pc, "_browser", None)
    yield t
    pc._playwright = None
    pc._browser = None


@pytest.mark.asyncio
async def test_browser_is_reused_across_fetches(tracker):
    """The whole point: N fetches, ONE launch."""
    for _ in range(4):
        await pc.scrape_with_playwright("https://x.pk/p", "WF-6807")

    assert tracker.launches == 1
    assert tracker.open_contexts == 0, "every context must be closed after its fetch"


@pytest.mark.asyncio
async def test_concurrent_first_calls_launch_exactly_one_browser(tracker):
    """
    Without the module-level init lock, both callers see `_browser is None`,
    both launch, and one browser is orphaned with no reference left to close it.
    """
    await asyncio.gather(*(
        pc.scrape_with_playwright(f"https://x.pk/{i}", "WF-6807") for i in range(5)
    ))

    assert tracker.launches == 1


@pytest.mark.asyncio
async def test_context_is_closed_when_page_load_fails(tracker):
    """
    THE LEAK. The old code called browser.close() inside the try, after the goto
    retry loop, so a timeout skipped it -- survivable only because
    `async with async_playwright()` tore the driver down on the way out. With a
    pooled browser that safety net is gone, so the close must be in `finally`.
    """
    tracker.goto_raises = True

    result = await pc.scrape_with_playwright("https://x.pk/slow", "WF-6807")

    assert result.success is False
    assert tracker.open_contexts == 0, "a failed load must not leak its context"


@pytest.mark.asyncio
async def test_contexts_are_bounded_by_the_semaphore(tracker):
    """
    Domain-level fan-out is sized for cheap curl requests. If many of those
    escalate to Tier 2 at once, this inner bound is the only thing standing
    between the run and a RAM spike.
    """
    tracker.goto_hangs = True

    await asyncio.gather(*(
        pc.scrape_with_playwright(f"https://x.pk/{i}", "WF-6807") for i in range(10)
    ))

    from app.core.config import settings
    assert tracker.peak_contexts <= settings.MAX_PLAYWRIGHT_CONTEXTS
    assert tracker.open_contexts == 0


@pytest.mark.asyncio
async def test_heavy_resources_are_blocked_per_context(tracker):
    """Images/fonts/CSS never affect extracted text, so they are never fetched."""
    await pc.scrape_with_playwright("https://x.pk/p", "WF-6807")

    assert tracker.routes_registered == 1


@pytest.mark.asyncio
async def test_block_rule_aborts_assets_and_allows_scripts(tracker):
    """The route handler itself: assets aborted, scripts/XHR let through --
    blocking scripts would defeat the entire reason Tier 2 exists."""
    aborted, continued = [], []

    class _Route:
        def __init__(self, resource_type):
            self.request = type("R", (), {"resource_type": resource_type})()

        async def abort(self):
            aborted.append(self.request.resource_type)

        async def continue_(self):
            continued.append(self.request.resource_type)

    for kind in ("image", "font", "stylesheet", "media", "script", "xhr", "document"):
        await pc._block_heavy_resources(_Route(kind))

    assert set(aborted) == {"image", "font", "stylesheet", "media"}
    assert set(continued) == {"script", "xhr", "document"}


@pytest.mark.asyncio
async def test_shutdown_closes_browser_and_driver(tracker):
    await pc.scrape_with_playwright("https://x.pk/p", "WF-6807")
    await pc.shutdown_browser()

    assert tracker.browser_closed
    assert tracker.driver_stopped
    assert pc._browser is None


@pytest.mark.asyncio
async def test_shutdown_is_safe_when_nothing_was_launched(tracker):
    """Called from a `finally`, so it must tolerate a batch that never scraped."""
    await pc.shutdown_browser()

    assert tracker.launches == 0
    assert pc._browser is None


def test_second_event_loop_does_not_break_scraping(monkeypatch):
    """
    REGRESSION. An asyncio primitive binds to the event loop that first BLOCKS on
    it, then raises "is bound to a different event loop" everywhere else. Since
    `asyncio.run()` builds a fresh loop per call, a module-level lock made a
    second batch in the same process fail -- measured at 5 of 6 concurrent
    fetches before the fix.

    It failed silently, which is the dangerous part: `_get_browser` errors are
    caught and returned as success=False, so the sources simply disappeared and
    products escalated to Manual Review with no indication why.

    Deliberately NOT an async test -- the bug only exists ACROSS loops, so the
    test has to own the loops itself.
    """
    t = _Tracker()
    monkeypatch.setattr(pc, "async_playwright", lambda: _FakeAsyncPlaywright(t))
    monkeypatch.setattr(pc, "_playwright", None)
    monkeypatch.setattr(pc, "_browser", None)
    monkeypatch.setattr(pc, "_primitives_loop", None)

    async def one_batch():
        # Mirrors BatchProcessor.run_batch: fetches, then tears the browser down
        # in a finally. That teardown is what makes this bite -- batch 2 starts
        # with no browser, so it must take the init lock, and only a CONTENDED
        # lock touches its event loop. Without the shutdown, the "browser already
        # exists" fast path returns before the lock is ever reached and the bug
        # stays invisible.
        try:
            return await asyncio.gather(*(
                pc.scrape_with_playwright(f"https://x.pk/{i}", "WF-6807") for i in range(6)
            ))
        finally:
            await pc.shutdown_browser()

    try:
        for batch_no in (1, 2):
            results = asyncio.run(one_batch())
            failed = [r for r in results if not r.success]
            assert not failed, (
                f"batch {batch_no}: {len(failed)}/{len(results)} fetches failed -- "
                f"scraper primitives are loop-bound again "
                f"({failed[0].error_message if failed else ''})"
            )
    finally:
        pc._playwright = None
        pc._browser = None
        pc._primitives_loop = None
